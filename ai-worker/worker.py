import redis
import json
import time
import requests
from minio import Minio
from minio.error import S3Error
import io
import os
from config import (
    MINIO_ENDPOINT, MINIO_PORT, MINIO_ACCESS_KEY, MINIO_SECRET_KEY,
    MINIO_USE_SSL, REDIS_URL, WEBHOOK_URL, RAW_BUCKET, PROCESSED_BUCKET
)
from processing.background_removal import remove_background
from processing.studio_compose import create_studio_image


# Initialize MinIO client
minio_client = Minio(
    f"{MINIO_ENDPOINT}:{MINIO_PORT}",
    access_key=MINIO_ACCESS_KEY,
    secret_key=MINIO_SECRET_KEY,
    secure=MINIO_USE_SSL
)

# Initialize Redis client
redis_client = redis.from_url(REDIS_URL)

# BullMQ queue name
QUEUE_NAME = "bull:photo-processing"


def process_photo(job_data):
    """
    Process a single photo: download, remove background, compose studio image, upload.
    
    Args:
        job_data: Dictionary with vehicleId, photoIndex, objectKey
    """
    vehicle_id = job_data['vehicleId']
    photo_index = job_data['photoIndex']
    object_key = job_data['objectKey']
    
    print(f"Processing photo {photo_index} for vehicle {vehicle_id}")
    
    try:
        # Download raw image from MinIO
        response = minio_client.get_object(RAW_BUCKET, object_key)
        image_bytes = response.read()
        response.close()
        response.release_conn()
        
        # Remove background
        vehicle_image = remove_background(image_bytes)
        
        # Create studio composition
        studio_image = create_studio_image(vehicle_image)
        
        # Convert to bytes
        img_byte_arr = io.BytesIO()
        studio_image.save(img_byte_arr, format='JPEG', quality=95)
        img_byte_arr.seek(0)
        
        # Upload processed image to MinIO
        processed_key = f"{vehicle_id}/processed-{photo_index}-{object_key.split('/')[-1]}"
        minio_client.put_object(
            PROCESSED_BUCKET,
            processed_key,
            img_byte_arr,
            length=img_byte_arr.getbuffer().nbytes,
            content_type='image/jpeg'
        )
        
        # Increment processed counter
        processed_count = redis_client.incr(f"vehicle:{vehicle_id}:processed")
        
        print(f"Photo {photo_index} processed successfully. Total processed: {processed_count}")
        
        # Check if all 24 photos are processed
        if processed_count == 24:
            send_webhook(vehicle_id)
            
    except S3Error as e:
        print(f"MinIO error processing photo {photo_index}: {e}")
        raise
    except Exception as e:
        print(f"Error processing photo {photo_index}: {e}")
        raise


def send_webhook(vehicle_id):
    """
    Send webhook when all 24 photos are processed.
    
    Args:
        vehicle_id: Vehicle identifier
    """
    try:
        # Get all processed image keys
        processed_keys = []
        objects = minio_client.list_objects(PROCESSED_BUCKET, prefix=f"{vehicle_id}/")
        for obj in objects:
            if obj.object_name.startswith(f"{vehicle_id}/processed-"):
                processed_keys.append(obj.object_name)
        
        # Sort by photo index
        processed_keys.sort(key=lambda x: int(x.split('-')[1]))
        
        # Generate viewer URL
        viewer_url = f"http://localhost:3000/viewer/{vehicle_id}"
        
        payload = {
            'vehicleId': vehicle_id,
            'status': 'completed',
            'processedImages': processed_keys,
            'viewerUrl': viewer_url,
            'iframeCode': f'<iframe src="{viewer_url}" width="100%" height="600" frameborder="0"></iframe>'
        }
        
        response = requests.post(WEBHOOK_URL, json=payload, timeout=10)
        print(f"Webhook sent for vehicle {vehicle_id}: {response.status_code}")
        
    except Exception as e:
        print(f"Error sending webhook for vehicle {vehicle_id}: {e}")


def worker_loop():
    """
    Main worker loop: consume jobs from BullMQ queue using Redis Streams.
    """
    print("Starting AI worker...")
    
    while True:
        try:
            # Use BRPOPLPUSH for FIFO queue behavior
            # This simulates BullMQ job consumption
            job_json = redis_client.brpop(f"{QUEUE_NAME}:waiting", timeout=5)
            
            if job_json:
                queue_name, job_data_json = job_json
                job_data = json.loads(job_data_json)
                
                print(f"Received job: {job_data}")
                
                try:
                    process_photo(job_data)
                    # Remove from processing set
                    redis_client.lrem(f"{QUEUE_NAME}:waiting", 0, job_data_json)
                except Exception as e:
                    print(f"Job failed, will be retried: {e}")
                    # Add back to queue for retry
                    redis_client.lpush(f"{QUEUE_NAME}:waiting", job_data_json)
                    time.sleep(1)
                    
        except redis.RedisError as e:
            print(f"Redis error: {e}")
            time.sleep(5)
        except Exception as e:
            print(f"Worker error: {e}")
            time.sleep(5)


if __name__ == "__main__":
    worker_loop()
