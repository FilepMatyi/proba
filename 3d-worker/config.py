import os
from dotenv import load_dotenv

load_dotenv()

MINIO_ENDPOINT = os.getenv('MINIO_ENDPOINT', 'localhost')
MINIO_PORT = os.getenv('MINIO_PORT', '9000')
MINIO_ACCESS_KEY = os.getenv('MINIO_ACCESS_KEY', 'minioadmin')
MINIO_SECRET_KEY = os.getenv('MINIO_SECRET_KEY', 'minioadmin')
MINIO_USE_SSL = os.getenv('MINIO_USE_SSL', 'false').lower() == 'true'
REDIS_URL = os.getenv('REDIS_URL', 'redis://localhost:6379')
BACKEND_URL = os.getenv('BACKEND_URL', 'http://localhost:3000')
RAW_BUCKET = os.getenv('RAW_BUCKET', 'vehicleshoot-raw')
PROCESSED_BUCKET = os.getenv('PROCESSED_BUCKET', 'vehicleshoot-processed')

# 3D reconstruction settings
OPENSPLAT_ITERS = int(os.getenv('OPENSPLAT_ITERS', '7000'))
OPENSPLAT_DOWNSCALES = int(os.getenv('OPENSPLAT_DOWNSCALES', '2'))
