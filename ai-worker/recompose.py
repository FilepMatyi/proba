"""Reapply sequence stabilization and studio composition without AI inference."""

import argparse
import io
import json

import redis
import requests
from minio import Minio
from PIL import Image

from config import (
    BACKEND_URL,
    INTERNAL_API_TOKEN,
    MINIO_ACCESS_KEY,
    MINIO_ENDPOINT,
    MINIO_PORT,
    MINIO_SECRET_KEY,
    MINIO_USE_SSL,
    PROCESSED_BUCKET,
    RAW_BUCKET,
    REDIS_URL,
    TARGET_FRAMES,
)
from processing.exposure_normalize import normalize_exposure
from processing.stabilization import build_sequence_layout, stabilize_vehicle_sequence
from processing.studio_compose import create_studio_image


minio_client = Minio(
    f'{MINIO_ENDPOINT}:{MINIO_PORT}',
    access_key=MINIO_ACCESS_KEY,
    secret_key=MINIO_SECRET_KEY,
    secure=MINIO_USE_SSL,
)
redis_client = redis.from_url(REDIS_URL, decode_responses=True)


def _download_image(object_key):
    response = minio_client.get_object(RAW_BUCKET, object_key)
    try:
        with Image.open(io.BytesIO(response.read())) as image:
            return image.convert('RGBA').copy()
    finally:
        response.close()
        response.release_conn()


def _upload_image(bucket, object_key, image, image_format, **save_options):
    output = io.BytesIO()
    image.save(output, format=image_format, **save_options)
    output.seek(0)
    content_type = 'image/png' if image_format == 'PNG' else 'image/jpeg'
    minio_client.put_object(
        bucket,
        object_key,
        output,
        length=output.getbuffer().nbytes,
        content_type=content_type,
    )


def recompose_vehicle(vehicle_id):
    images = {
        index: _download_image(f'{vehicle_id}/transparent-{index}.png')
        for index in range(1, TARGET_FRAMES + 1)
    }
    levelled, vehicle_report = stabilize_vehicle_sequence(images)
    normalized = normalize_exposure(levelled)
    layout, layout_report = build_sequence_layout(normalized)
    layout_report.update(vehicle_report)

    redis_client.delete(f'vehicle:{vehicle_id}:layout')
    for index, image in normalized.items():
        _upload_image(
            RAW_BUCKET,
            f'{vehicle_id}/transparent-{index}.png',
            image,
            'PNG',
            optimize=True,
        )
        redis_client.hset(
            f'vehicle:{vehicle_id}:layout',
            str(index),
            json.dumps(layout[index]),
        )

        studio = create_studio_image(
            image,
            target_height_ratio=layout[index]['targetHeightRatio'],
        )
        _upload_image(
            PROCESSED_BUCKET,
            f'{vehicle_id}/processed-{index}.jpg',
            studio,
            'JPEG',
            quality=94,
            subsampling=0,
            optimize=True,
        )
        preview = studio.resize((1280, 720), Image.Resampling.LANCZOS)
        _upload_image(
            PROCESSED_BUCKET,
            f'{vehicle_id}/preview-{index}.jpg',
            preview,
            'JPEG',
            quality=86,
            optimize=True,
            progressive=True,
        )

    redis_client.expire(f'vehicle:{vehicle_id}:layout', 24 * 60 * 60)
    response = requests.post(
        f'{BACKEND_URL}/internal/vehicles/{vehicle_id}/quality',
        json={'metrics': {'stabilization': layout_report}, 'warnings': []},
        headers={'x-internal-token': INTERNAL_API_TOKEN},
        timeout=15,
    )
    response.raise_for_status()
    return layout_report


def main():
    parser = argparse.ArgumentParser(
        description='Restabilize existing transparent frames and rebuild viewer assets.'
    )
    parser.add_argument('vehicle_ids', nargs='+')
    args = parser.parse_args()

    for vehicle_id in args.vehicle_ids:
        report = recompose_vehicle(vehicle_id)
        print(json.dumps({'vehicleId': vehicle_id, **report}, ensure_ascii=False))


if __name__ == '__main__':
    main()
