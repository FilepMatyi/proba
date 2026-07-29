import redis
import json
import time
import requests
from minio import Minio
from minio.error import S3Error
import io
import os
import uuid
from config import (
    MINIO_ENDPOINT, MINIO_PORT, MINIO_ACCESS_KEY, MINIO_SECRET_KEY,
    MINIO_USE_SSL, REDIS_URL, WEBHOOK_URL, RAW_BUCKET, PROCESSED_BUCKET
)
from processing.background_removal import remove_background
from processing.studio_compose import create_studio_image
from processing.frame_selector import select_optimal_frames, calculate_sharpness
from PIL import Image

# Initialize MinIO client
minio_client = Minio(
    f"{MINIO_ENDPOINT}:{MINIO_PORT}",
    access_key=MINIO_ACCESS_KEY,
    secret_key=MINIO_SECRET_KEY,
    secure=MINIO_USE_SSL
)

# Initialize Redis client
redis_client = redis.from_url(REDIS_URL, decode_responses=True)

# Redis Streams configuration
STREAM_NAME = "photo-processing-stream"
CONSUMER_GROUP = "photo-processing-group"
CONSUMER_NAME = f"worker-{uuid.uuid4()}"


def handle_select_frames(fields):
    """
    STAGE 1: Given 108 candidate frames, use sensor data to pick the best 36 based on angles and sharpness.
    """
    vehicle_id = fields['vehicleId']
    frame_count = int(fields['frameCount'])
    has_sensor_data = fields['hasSensorData'] == 'true'
    
    print(f"[{vehicle_id}] STAGE 1: Selecting best 36 frames out of {frame_count} candidates")
    
    sensor_data = None
    if has_sensor_data:
        try:
            response = minio_client.get_object(RAW_BUCKET, f"{vehicle_id}/candidates/sensorData.json")
            sensor_data = json.loads(response.read())
            response.close()
            response.release_conn()
        except Exception as e:
            print(f"Error loading sensor data: {e}")
            
    # List candidate objects
    candidates = []
    for i in range(frame_count):
        candidates.append(f"{vehicle_id}/candidates/frame-{(i+1):03d}.jpg")
        
    num_target_frames = 36
    
    if not sensor_data:
        print("No sensor data, falling back to evenly spaced selection")
        step = len(candidates) / num_target_frames
        selected_indices = [int(i * step) for i in range(num_target_frames)]
        
        for i, idx in enumerate(selected_indices):
            photo_index = i + 1
            redis_client.xadd(STREAM_NAME, {
                'type': 'process-bg-removal',
                'vehicleId': vehicle_id,
                'photoIndex': photo_index,
                'candidateKey': candidates[idx]
            })
        print(f"Queued {num_target_frames} bg-removal tasks")
        return

    # Use frame selector
    candidate_groups, median_beta, median_gamma = select_optimal_frames(sensor_data, candidates, num_target_frames)
    
    for i, group in enumerate(candidate_groups):
        photo_index = i + 1
        best_idx = None
        best_score = -float('inf')
        
        # Download and evaluate the 3 closest candidates for this angle
        for candidate_info in group:
            idx = candidate_info['index']
            object_key = candidates[idx]
            
            try:
                response = minio_client.get_object(RAW_BUCKET, object_key)
                img_bytes = response.read()
                response.close()
                response.release_conn()
                
                sharpness = calculate_sharpness(img_bytes)
                
                # Score combines sharpness and levelness (penalty for deviating from median beta/gamma)
                tilt_penalty = abs(candidate_info['beta'] - median_beta) + abs(candidate_info['gamma'] - median_gamma)
                
                # Weights: we want sharp images, but avoid heavily tilted ones.
                # Sharpness usually ranges from 100 to 1000+. Tilt is in degrees.
                score = sharpness - (tilt_penalty * 20)
                
                if score > best_score:
                    best_score = score
                    best_idx = idx
            except Exception as e:
                print(f"Error evaluating candidate {idx}: {e}")
                if best_idx is None: best_idx = idx
        
        # Queue background removal for the winner
        redis_client.xadd(STREAM_NAME, {
            'type': 'process-bg-removal',
            'vehicleId': vehicle_id,
            'photoIndex': photo_index,
            'candidateKey': candidates[best_idx]
        })
        
    print(f"[{vehicle_id}] Queued {num_target_frames} bg-removal tasks based on sharpness/angles")


def handle_bg_removal(fields):
    """
    STAGE 2: Remove background and store bounding box size in Redis.
    """
    vehicle_id = fields['vehicleId']
    photo_index = int(fields['photoIndex'])
    candidate_key = fields['candidateKey']
    
    print(f"[{vehicle_id}] STAGE 2: Removing bg for frame {photo_index}")
    
    # Download raw image
    response = minio_client.get_object(RAW_BUCKET, candidate_key)
    image_bytes = response.read()
    response.close()
    response.release_conn()
    
    # Remove background
    vehicle_image = remove_background(image_bytes, photo_index=photo_index)
    
    # Get bounding box height
    bbox = vehicle_image.getbbox()
    vh = bbox[3] - bbox[1] if bbox else vehicle_image.height
    
    # Store the height in Redis
    redis_client.hset(f"vehicle:{vehicle_id}:heights", str(photo_index), str(vh))
    
    # Save the transparent image to MinIO
    img_byte_arr = io.BytesIO()
    vehicle_image.save(img_byte_arr, format='PNG', optimize=True)
    img_byte_arr.seek(0)
    
    transparent_key = f"{vehicle_id}/transparent-{photo_index}.png"
    minio_client.put_object(
        RAW_BUCKET,
        transparent_key,
        img_byte_arr,
        length=img_byte_arr.getbuffer().nbytes,
        content_type='image/png'
    )
    
    # Check if all 36 frames are done
    count = redis_client.incr(f"vehicle:{vehicle_id}:bg_removed")
    if count == 36:
        print(f"[{vehicle_id}] All 36 backgrounds removed. Queuing Stage 3 (Studio Compose) for all frames.")
        for i in range(1, 37):
            redis_client.xadd(STREAM_NAME, {
                'type': 'process-studio',
                'vehicleId': vehicle_id,
                'photoIndex': i,
                'transparentKey': f"{vehicle_id}/transparent-{i}.png"
            })


def handle_studio(fields):
    """
    STAGE 3: Compose studio using a GLOBAL max height to prevent breathing.
    """
    vehicle_id = fields['vehicleId']
    photo_index = int(fields['photoIndex'])
    transparent_key = fields['transparentKey']
    
    print(f"[{vehicle_id}] STAGE 3: Studio compose for frame {photo_index}")
    
    # Get global max height
    heights_dict = redis_client.hgetall(f"vehicle:{vehicle_id}:heights")
    if not heights_dict:
        print(f"Warning: No heights found for {vehicle_id}, using fallback.")
        global_max_h = 1000
    else:
        global_max_h = max([int(v) for v in heights_dict.values()])
        
    # Download transparent image
    response = minio_client.get_object(RAW_BUCKET, transparent_key)
    vehicle_image = Image.open(io.BytesIO(response.read()))
    
    # Create studio composition
    studio_image = create_studio_image(vehicle_image, global_max_h=global_max_h)
    
    # Convert to bytes
    img_byte_arr = io.BytesIO()
    studio_image.save(img_byte_arr, format='JPEG', quality=97, subsampling=0, optimize=True)
    img_byte_arr.seek(0)
    
    # Upload processed image to MinIO
    processed_key = f"{vehicle_id}/processed-{photo_index}.jpg"
    minio_client.put_object(
        PROCESSED_BUCKET,
        processed_key,
        img_byte_arr,
        length=img_byte_arr.getbuffer().nbytes,
        content_type='image/jpeg'
    )
    
    # Notify backend about processed frame
    notify_backend_frame_processed(vehicle_id, photo_index)


def notify_backend_frame_processed(vehicle_id, photo_index):
    try:
        backend_url = os.getenv('BACKEND_URL', 'http://localhost:3000')
        requests.patch(
            f"{backend_url}/internal/vehicles/{vehicle_id}/frame-processed",
            json={'photoIndex': photo_index},
            timeout=10
        )
    except Exception as e:
        print(f"Error notifying backend about frame {photo_index}: {e}")


def initialize_consumer_group():
    try:
        redis_client.xgroup_create(STREAM_NAME, CONSUMER_GROUP, '0', mkstream=True)
        print(f"Created consumer group: {CONSUMER_GROUP}")
    except redis.ResponseError as e:
        if 'BUSYGROUP' in str(e):
            print(f"Consumer group {CONSUMER_GROUP} already exists")
        else:
            raise


def worker_loop():
    print(f"Starting AI worker as consumer: {CONSUMER_NAME}")
    initialize_consumer_group()
    
    while True:
        try:
            messages = redis_client.xreadgroup(
                CONSUMER_GROUP, CONSUMER_NAME, {STREAM_NAME: '>'}, count=1, block=5000
            )
            
            if messages:
                for stream, stream_messages in messages:
                    for message_id, fields in stream_messages:
                        job_type = fields.get('type', 'process-photo') # Fallback to old name
                        print(f"Received job '{job_type}': {message_id}")
                        
                        try:
                            if job_type == 'select-frames':
                                handle_select_frames(fields)
                            elif job_type == 'process-bg-removal':
                                handle_bg_removal(fields)
                            elif job_type == 'process-studio':
                                handle_studio(fields)
                            elif job_type == 'process-photo':
                                # Legacy fallback
                                print("Warning: Received legacy 'process-photo' task, ignoring or mapping to new pipeline")
                                
                            redis_client.xack(STREAM_NAME, CONSUMER_GROUP, message_id)
                        except Exception as e:
                            print(f"Job failed for message {message_id}: {e}")
                            time.sleep(1)
                            
        except redis.RedisError as e:
            print(f"Redis error: {e}")
            time.sleep(5)
        except Exception as e:
            print(f"Worker error: {e}")
            time.sleep(5)

if __name__ == "__main__":
    worker_loop()
