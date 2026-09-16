import io
import json

import cv2
import numpy as np
from PIL import Image

from config import RAW_BUCKET
from processing.stabilization import (
    _estimate_wheel_contact_roll,
    build_vehicle_alignment_plan,
    estimate_vehicle_roll,
)
from worker import minio_client


vehicle_id = 'car-test-5-premium-v2'
for index in range(1, 1):
    response = minio_client.get_object(
        RAW_BUCKET,
        f'{vehicle_id}/transparent-{index}.png',
    )
    try:
        image = Image.open(io.BytesIO(response.read())).convert('RGBA')
        bbox = image.getbbox()
        if bbox:
            image = image.crop(bbox)
        image.thumbnail((960, 960), Image.Resampling.LANCZOS)
    finally:
        response.close()
        response.release_conn()
    wheel_result = _estimate_wheel_contact_roll(image, minimum_aspect_ratio=0.0)
    silhouette_result = estimate_vehicle_roll(image)
    print(index, json.dumps({'wheel': wheel_result, 'fallback': silhouette_result}))
    rgba = np.asarray(image)
    alpha = rgba[:, :, 3]
    hsv = cv2.cvtColor(rgba[:, :, :3], cv2.COLOR_RGB2HSV)
    mask = (
        (hsv[:, :, 1] < 110)
        & (hsv[:, :, 2] < 170)
        & (alpha >= 80)
    ).astype(np.uint8) * 255
    mask[:int(mask.shape[0] * 0.42)] = 0
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    count, _, stats, centroids = cv2.connectedComponentsWithStats(mask)
    components = []
    for component in range(1, count):
        x, y, width, height, area = stats[component]
        if area < 80:
            continue
        components.append({
            'x': int(x), 'y': int(y), 'w': int(width), 'h': int(height),
            'area': int(area), 'cx': round(float(centroids[component][0]), 1),
            'cy': round(float(centroids[component][1]), 1),
        })
    if False:
        print('components', json.dumps(components))

planning = {}
for index in range(1, 37):
    response = minio_client.get_object(RAW_BUCKET, f'{vehicle_id}/transparent-{index}.png')
    try:
        image = Image.open(io.BytesIO(response.read())).convert('RGBA')
        bbox = image.getbbox()
        if bbox:
            image = image.crop(bbox)
        image.thumbnail((960, 960), Image.Resampling.LANCZOS)
        planning[index] = image.copy()
    finally:
        response.close()
        response.release_conn()

corrections, warps, report = build_vehicle_alignment_plan(planning)
print('corrections', json.dumps(corrections))
print('warps', json.dumps(warps))
print('report', json.dumps(report))
