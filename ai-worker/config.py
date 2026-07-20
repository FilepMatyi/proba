import os
from dotenv import load_dotenv

load_dotenv()

MINIO_ENDPOINT = os.getenv('MINIO_ENDPOINT', 'localhost')
MINIO_PORT = int(os.getenv('MINIO_PORT', '9000'))
MINIO_ACCESS_KEY = os.getenv('MINIO_ACCESS_KEY', 'minioadmin')
MINIO_SECRET_KEY = os.getenv('MINIO_SECRET_KEY', 'minioadmin')
MINIO_USE_SSL = os.getenv('MINIO_USE_SSL', 'false').lower() == 'true'

REDIS_URL = os.getenv('REDIS_URL', 'redis://localhost:6379')

WEBHOOK_URL = os.getenv('WEBHOOK_URL', 'http://localhost:3001/webhook')

RAW_BUCKET = 'vehicle-photos-raw'
PROCESSED_BUCKET = 'vehicle-photos-processed'
