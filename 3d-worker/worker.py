"""
3D Reconstruction Worker
========================
Dedicated worker for 3D Gaussian Splatting reconstruction.
Listens on a separate Redis stream for 3D reconstruction jobs.

Pipeline: COLMAP (camera poses) → OpenSplat (3DGS training) → PLY → SPLAT → MinIO
"""

import redis
import json
import time
import requests
import os
import uuid
import shutil
import tempfile
from minio import Minio
from config import (
    MINIO_ENDPOINT, MINIO_PORT, MINIO_ACCESS_KEY, MINIO_SECRET_KEY,
    MINIO_USE_SSL, REDIS_URL, BACKEND_URL, RAW_BUCKET, PROCESSED_BUCKET
)

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
CONSUMER_GROUP = "3d-processing-group"
CONSUMER_NAME = f"3d-worker-{uuid.uuid4()}"


def handle_3d_reconstruction(fields):
    """
    Full 3D Gaussian Splatting reconstruction from candidate images.
    Uses ALL candidate images (typically 108) for maximum quality.
    """
    vehicle_id = fields['vehicleId']
    frame_count = int(fields.get('frameCount', '108'))
    
    print(f"[{vehicle_id}] ════════════════════════════════════════")
    print(f"[{vehicle_id}] Starting 3D Reconstruction ({frame_count} images)")
    print(f"[{vehicle_id}] ════════════════════════════════════════")
    
    work_dir = tempfile.mkdtemp(prefix='3d-recon-')
    image_dir = os.path.join(work_dir, 'images')
    os.makedirs(image_dir, exist_ok=True)
    
    try:
        # ── Download all candidate images from MinIO ──
        print(f"[{vehicle_id}] Downloading {frame_count} candidate images...")
        downloaded = 0
        
        for i in range(1, frame_count + 1):
            key = f"{vehicle_id}/candidates/frame-{i:03d}.jpg"
            local_path = os.path.join(image_dir, f"frame-{i:03d}.jpg")
            try:
                response = minio_client.get_object(RAW_BUCKET, key)
                with open(local_path, 'wb') as f:
                    for chunk in response.stream(32 * 1024):
                        f.write(chunk)
                response.close()
                response.release_conn()
                downloaded += 1
            except Exception as e:
                # Skip missing frames silently
                pass
        
        print(f"[{vehicle_id}] Downloaded {downloaded}/{frame_count} images")
        
        if downloaded < 10:
            print(f"[{vehicle_id}] ❌ Not enough images for 3D reconstruction (need at least 10, got {downloaded})")
            return
        
        # ── Run 3D reconstruction pipeline ──
        from processing.reconstruction import reconstruct_3d
        splat_path = reconstruct_3d(vehicle_id, image_dir, work_dir)
        
        # ── Upload .splat to MinIO ──
        splat_key = f"{vehicle_id}/model.splat"
        file_size = os.path.getsize(splat_path)
        
        with open(splat_path, 'rb') as f:
            minio_client.put_object(
                PROCESSED_BUCKET,
                splat_key,
                f,
                length=file_size,
                content_type='application/octet-stream'
            )
        
        file_size_mb = file_size / 1024 / 1024
        print(f"[{vehicle_id}] ✅ 3D model uploaded: {splat_key} ({file_size_mb:.1f} MB)")
        
        # ── Notify backend ──
        try:
            requests.post(
                f"{BACKEND_URL}/internal/vehicles/{vehicle_id}/3d-ready",
                json={'splatKey': splat_key, 'fileSize': file_size},
                timeout=10
            )
        except Exception as e:
            print(f"[{vehicle_id}] Warning: Could not notify backend: {e}")
            
    except Exception as e:
        print(f"[{vehicle_id}] ❌ 3D reconstruction failed: {e}")
        import traceback
        traceback.print_exc()
    finally:
        # Cleanup
        shutil.rmtree(work_dir, ignore_errors=True)
        print(f"[{vehicle_id}] Cleaned up work directory")


def initialize_consumer_group():
    """Create the consumer group if it doesn't exist."""
    try:
        redis_client.xgroup_create(STREAM_NAME, CONSUMER_GROUP, '0', mkstream=True)
        print(f"Created consumer group: {CONSUMER_GROUP}")
    except redis.ResponseError as e:
        if 'BUSYGROUP' in str(e):
            print(f"Consumer group {CONSUMER_GROUP} already exists")
        else:
            raise


def worker_loop():
    """Main worker loop — listens for 3D reconstruction jobs."""
    print("=" * 60)
    print(f"  3D Reconstruction Worker starting")
    print(f"  Consumer: {CONSUMER_NAME}")
    print(f"  Stream:   {STREAM_NAME}")
    print(f"  Group:    {CONSUMER_GROUP}")
    print("=" * 60)
    
    initialize_consumer_group()
    
    while True:
        try:
            messages = redis_client.xreadgroup(
                CONSUMER_GROUP, CONSUMER_NAME, 
                {STREAM_NAME: '>'}, 
                count=1, block=5000
            )
            
            if messages:
                for stream, stream_messages in messages:
                    for message_id, fields in stream_messages:
                        job_type = fields.get('type', '')
                        
                        # Only handle 3D reconstruction jobs
                        if job_type == 'process-3d-reconstruction':
                            print(f"\n{'='*60}")
                            print(f"Received 3D reconstruction job: {message_id}")
                            print(f"{'='*60}")
                            
                            try:
                                handle_3d_reconstruction(fields)
                                redis_client.xack(STREAM_NAME, CONSUMER_GROUP, message_id)
                            except Exception as e:
                                print(f"Job failed for message {message_id}: {e}")
                                time.sleep(5)
                        else:
                            # Not our job type — acknowledge to not block the stream
                            redis_client.xack(STREAM_NAME, CONSUMER_GROUP, message_id)
                            
        except redis.RedisError as e:
            print(f"Redis error: {e}")
            time.sleep(5)
        except Exception as e:
            print(f"Worker error: {e}")
            time.sleep(5)


if __name__ == "__main__":
    worker_loop()
