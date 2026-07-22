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
        studio_image.save(img_byte_arr, format='JPEG', quality=97, subsampling=0, optimize=True)
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
        
        # Notify backend about processed frame
        notify_backend_frame_processed(vehicle_id, photo_index)
        
        print(f"Photo {photo_index} processed successfully")
            
    except S3Error as e:
        print(f"MinIO error processing photo {photo_index}: {e}")
        raise
    except Exception as e:
        print(f"Error processing photo {photo_index}: {e}")
        raise


def notify_backend_frame_processed(vehicle_id, photo_index):
    """
    Notify backend that a frame has been processed.
    The backend will update the database and trigger webhook if all frames are done.
    
    Args:
        vehicle_id: Vehicle identifier
        photo_index: Photo sequence number
    """
    try:
        backend_url = os.getenv('BACKEND_URL', 'http://localhost:3000')
        response = requests.patch(
            f"{backend_url}/internal/vehicles/{vehicle_id}/frame-processed",
            json={'photoIndex': photo_index},
            timeout=10
        )
        print(f"Notified backend about frame {photo_index}: {response.status_code}")
    except Exception as e:
        print(f"Error notifying backend about frame {photo_index}: {e}")


def initialize_consumer_group():
    """
    Initialize the Redis Streams consumer group.
    """
    try:
        redis_client.xgroup_create(STREAM_NAME, CONSUMER_GROUP, '0', mkstream=True)
        print(f"Created consumer group: {CONSUMER_GROUP}")
    except redis.ResponseError as e:
        if 'BUSYGROUP' in str(e):
            print(f"Consumer group {CONSUMER_GROUP} already exists")
        else:
            raise


def worker_loop():
    """
    Main worker loop: consume jobs from Redis Streams using XREADGROUP.
    """
    print(f"Starting AI worker as consumer: {CONSUMER_NAME}")
    
    # Initialize consumer group
    initialize_consumer_group()
    
    while True:
        try:
            # Read new messages from the stream
            # BLOCK 5000 = wait up to 5 seconds for new messages
            # COUNT 1 = process one message at a time
            messages = redis_client.xreadgroup(
                CONSUMER_GROUP,
                CONSUMER_NAME,
                {STREAM_NAME: '>'},
                count=1,
                block=5000
            )
            
            if messages:
                for stream, stream_messages in messages:
                    for message_id, fields in stream_messages:
                        print(f"Received message {message_id}: {fields}")
                        
                        job_data = {
                            'vehicleId': fields['vehicleId'],
                            'photoIndex': int(fields['photoIndex']),
                            'objectKey': fields['objectKey']
                        }
                        
                        try:
                            process_photo(job_data)
                            # Acknowledge message after successful processing
                            redis_client.xack(STREAM_NAME, CONSUMER_GROUP, message_id)
                            print(f"Acknowledged message {message_id}")
                        except Exception as e:
                            print(f"Job failed for message {message_id}: {e}")
                            # Message will be retried after delivery timeout (default 1 hour)
                            # For immediate retry, we could move it to pending list
                            time.sleep(1)
                            
        except redis.RedisError as e:
            print(f"Redis error: {e}")
            time.sleep(5)
        except Exception as e:
            print(f"Worker error: {e}")
            time.sleep(5)


if __name__ == "__main__":
    worker_loop()
