import io
import json
import os
import time
import uuid

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
from processing.background_removal import remove_background
from processing.frame_selector import analyze_image_quality, select_optimal_frames
from processing.studio_compose import create_studio_image


STREAM_NAME = 'photo-processing-stream'
CONSUMER_GROUP = 'photo-processing-group'
CONSUMER_NAME = f'worker-{uuid.uuid4()}'
DEAD_LETTER_STREAM = 'photo-processing-dead-letter'
MAX_ATTEMPTS = 3
STALE_AFTER_MS = 30 * 60 * 1000
STATE_TTL_SECONDS = 24 * 60 * 60

minio_client = Minio(
    f'{MINIO_ENDPOINT}:{MINIO_PORT}',
    access_key=MINIO_ACCESS_KEY,
    secret_key=MINIO_SECRET_KEY,
    secure=MINIO_USE_SSL,
)
redis_client = redis.from_url(REDIS_URL, decode_responses=True)


def _download_bytes(bucket, object_key):
    response = minio_client.get_object(bucket, object_key)
    try:
        return response.read()
    finally:
        response.close()
        response.release_conn()


def _expire_state_keys(vehicle_id):
    for suffix in ('heights', 'mask_quality', 'bg_done', 'studio_queued', 'studio_done'):
        redis_client.expire(f'vehicle:{vehicle_id}:{suffix}', STATE_TTL_SECONDS)


def _rounded_metrics(metrics):
    return {
        key: round(float(value), 4)
        for key, value in metrics.items()
    }


def _selection_report(selected_details, sensor_assisted, frame_count):
    scores = [item['quality']['score'] for item in selected_details]
    brightness = [item['quality']['brightness'] for item in selected_details]
    clipping = [
        item['quality']['black_clip_ratio'] + item['quality']['white_clip_ratio']
        for item in selected_details
    ]
    selected_indexes = [item['candidateIndex'] for item in selected_details]
    ideal_gap = frame_count / max(len(selected_details), 1)
    gaps = [right - left for left, right in zip(selected_indexes, selected_indexes[1:])]
    cadence_deviation = (
        sum(abs(gap - ideal_gap) for gap in gaps) / max(len(gaps) * ideal_gap, 1)
    )

    score = round(max(0, min(100, sum(scores) / len(scores) - min(cadence_deviation * 10, 12))))
    warnings = []
    weak_frames = sum(value < 55 for value in scores)
    if weak_frames >= 4:
        warnings.append(f'{weak_frames} kiválasztott nézet fényessége vagy élessége gyengébb az ideálisnál.')
    if sum(brightness) / len(brightness) < 76:
        warnings.append('A felvétel összességében sötét; egyenletesebb megvilágítás ajánlott.')
    elif sum(brightness) / len(brightness) > 190:
        warnings.append('A felvétel összességében túl világos; kerüld a közvetlen ellenfényt.')
    if sum(clipping) / len(clipping) > 0.12:
        warnings.append('Több nézetben elveszhetnek részletek a mély árnyékokban vagy csúcsfényekben.')
    if cadence_deviation > 0.38:
        warnings.append('A körbejárás sebessége egyenetlen volt; lassabb, egyenletes tempó javítja a forgást.')
    return score, warnings, {
        'selection': {
            'sensorAssisted': sensor_assisted,
            'candidateFrames': frame_count,
            'selectedFrames': len(selected_details),
            'averageFrameScore': round(sum(scores) / len(scores), 2),
            'minimumFrameScore': round(min(scores), 2),
            'cadenceDeviation': round(cadence_deviation, 4),
        }
    }


def handle_select_frames(fields):
    vehicle_id = fields['vehicleId']
    frame_count = int(fields['frameCount'])
    target_frames = min(int(fields.get('targetFrames', TARGET_FRAMES)), frame_count)
    has_sensor_data = fields.get('hasSensorData', 'false').lower() == 'true'

    if target_frames < TARGET_FRAMES:
        raise ValueError(f'Only {frame_count} candidates are available for {TARGET_FRAMES} output frames')

    sensor_data = None
    if has_sensor_data:
        try:
            sensor_data = json.loads(
                _download_bytes(RAW_BUCKET, f'{vehicle_id}/candidates/sensorData.json')
            )
        except Exception as error:
            print(f'[{vehicle_id}] Sensor data unavailable, using temporal selection: {error}')

    candidate_keys = [
        f'{vehicle_id}/candidates/frame-{index:03d}.jpg'
        for index in range(1, frame_count + 1)
    ]
    candidate_groups, median_beta, median_gamma = select_optimal_frames(
        sensor_data, candidate_keys, target_frames
    )

    selected = set()
    selected_details = []
    quality_cache = {}
    last_selected = -1
    for output_offset, group in enumerate(candidate_groups):
        expected_index = (output_offset + 0.5) * frame_count / target_frames - 0.5
        ranked_candidates = {item['index']: {**item, 'rank': rank} for rank, item in enumerate(group)}
        for index in sorted(range(frame_count), key=lambda item: abs(item - expected_index))[:7]:
            ranked_candidates.setdefault(index, {
                'index': index,
                'beta': median_beta,
                'gamma': median_gamma,
                'rank': 7,
            })

        remaining_after = target_frames - output_offset - 1
        max_allowed = frame_count - remaining_after - 1
        available = [
            item for item in ranked_candidates.values()
            if last_selected < item['index'] <= max_allowed and item['index'] not in selected
        ]
        if not available:
            available = [{
                'index': index,
                'beta': median_beta,
                'gamma': median_gamma,
                'rank': 8,
            } for index in range(last_selected + 1, max_allowed + 1)]

        best_index = None
        best_score = float('-inf')
        best_quality = None
        for candidate in available:
            candidate_index = candidate['index']
            try:
                if candidate_index not in quality_cache:
                    image_bytes = _download_bytes(RAW_BUCKET, candidate_keys[candidate_index])
                    quality_cache[candidate_index] = analyze_image_quality(image_bytes)
                quality = quality_cache[candidate_index]
                tilt = abs(candidate.get('beta', median_beta) - median_beta)
                roll = abs(candidate.get('gamma', median_gamma) - median_gamma)
                cadence_weight = 0.18 if candidate['rank'] < 7 else 0.7
                cadence_penalty = min(abs(candidate_index - expected_index) * cadence_weight, 18)
                score = quality['score'] - (tilt + roll) * 0.35 - cadence_penalty - candidate['rank'] * 0.65
                if score > best_score:
                    best_score = score
                    best_index = candidate_index
                    best_quality = quality
            except Exception as error:
                print(f'[{vehicle_id}] Candidate {candidate_index + 1} could not be scored: {error}')

        if best_index is None:
            raise RuntimeError(f'No readable candidate for output frame {output_offset + 1}')

        selected.add(best_index)
        last_selected = best_index
        selected_details.append({
            'outputIndex': output_offset + 1,
            'candidateIndex': best_index,
            'quality': _rounded_metrics(best_quality),
        })

    sensor_assisted = bool(
        sensor_data
        and any(abs(item.get('unwrapped_alpha', 0.0)) > 0.0 for group in candidate_groups for item in group)
    )
    quality_score, warnings, metrics = _selection_report(
        selected_details, sensor_assisted, frame_count
    )
    notify_backend_quality(vehicle_id, quality_score, warnings, metrics)

    for output_offset, selected_detail in enumerate(selected_details):
        best_index = selected_detail['candidateIndex']
        redis_client.xadd(STREAM_NAME, {
            'type': 'process-bg-removal',
            'vehicleId': vehicle_id,
            'photoIndex': str(output_offset + 1),
            'candidateKey': candidate_keys[best_index],
        })

    print(f'[{vehicle_id}] Selected and queued {len(selected)} unique frames')


def handle_bg_removal(fields):
    vehicle_id = fields['vehicleId']
    photo_index = int(fields['photoIndex'])
    image_bytes = _download_bytes(RAW_BUCKET, fields['candidateKey'])

    if os.getenv('ENABLE_UPSCALE', 'false').lower() == 'true':
        try:
            from processing.upscaler import upscale_image
            image_bytes = upscale_image(image_bytes)
        except Exception as error:
            print(f'[{vehicle_id}] Upscale skipped for frame {photo_index}: {error}')

    vehicle_image = remove_background(image_bytes, photo_index=photo_index)
    bounding_box = vehicle_image.getbbox()
    vehicle_height = bounding_box[3] - bounding_box[1] if bounding_box else vehicle_image.height
    if bounding_box:
        bbox_width = (bounding_box[2] - bounding_box[0]) / max(vehicle_image.width, 1)
        bbox_height = vehicle_height / max(vehicle_image.height, 1)
        touches_edge = (
            bounding_box[0] <= 2 or bounding_box[1] <= 2
            or bounding_box[2] >= vehicle_image.width - 2
            or bounding_box[3] >= vehicle_image.height - 2
        )
    else:
        bbox_width, bbox_height, touches_edge = 0.0, 0.0, False
    alpha_histogram = vehicle_image.getchannel('A').histogram()
    alpha_coverage = sum(alpha_histogram[16:]) / max(vehicle_image.width * vehicle_image.height, 1)

    transparent_buffer = io.BytesIO()
    vehicle_image.save(transparent_buffer, format='PNG', optimize=True)
    transparent_buffer.seek(0)
    transparent_key = f'{vehicle_id}/transparent-{photo_index}.png'
    minio_client.put_object(
        RAW_BUCKET,
        transparent_key,
        transparent_buffer,
        length=transparent_buffer.getbuffer().nbytes,
        content_type='image/png',
    )

    redis_client.hset(f'vehicle:{vehicle_id}:heights', str(photo_index), str(vehicle_height))
    redis_client.hset(f'vehicle:{vehicle_id}:mask_quality', str(photo_index), json.dumps({
        'bboxWidthRatio': round(bbox_width, 4),
        'bboxHeightRatio': round(bbox_height, 4),
        'alphaCoverage': round(alpha_coverage, 4),
        'touchesEdge': touches_edge,
    }))
    redis_client.sadd(f'vehicle:{vehicle_id}:bg_done', str(photo_index))
    _expire_state_keys(vehicle_id)

    done_count = redis_client.scard(f'vehicle:{vehicle_id}:bg_done')
    queue_lock = f'vehicle:{vehicle_id}:studio_queued'
    if done_count >= TARGET_FRAMES and redis_client.set(queue_lock, '1', nx=True, ex=STATE_TTL_SECONDS):
        summarize_mask_quality(vehicle_id)
        normalize_transparent_frames(vehicle_id)
        for index in range(1, TARGET_FRAMES + 1):
            redis_client.xadd(STREAM_NAME, {
                'type': 'process-studio',
                'vehicleId': vehicle_id,
                'photoIndex': str(index),
                'transparentKey': f'{vehicle_id}/transparent-{index}.png',
            })
        print(f'[{vehicle_id}] Queued {TARGET_FRAMES} studio compositions')


def summarize_mask_quality(vehicle_id):
    raw_metrics = redis_client.hgetall(f'vehicle:{vehicle_id}:mask_quality')
    metrics = []
    for value in raw_metrics.values():
        try:
            metrics.append(json.loads(value))
        except (TypeError, ValueError):
            continue
    if not metrics:
        return

    edge_frames = sum(bool(item.get('touchesEdge')) for item in metrics)
    small_frames = sum(item.get('bboxWidthRatio', 0) < 0.32 for item in metrics)
    warnings = []
    if edge_frames:
        warnings.append(f'{edge_frames} nézetben a jármű közel került a képszélhez; ellenőrzés ajánlott.')
    if small_frames >= 4:
        warnings.append('A jármű több nézetben túl kicsi a képen; a következő felvételnél menj közelebb.')

    notify_backend_quality(vehicle_id, None, warnings, {
        'segmentation': {
            'edgeTouchingFrames': edge_frames,
            'smallVehicleFrames': small_frames,
            'averageAlphaCoverage': round(
                sum(item.get('alphaCoverage', 0) for item in metrics) / len(metrics), 4
            ),
        }
    })


def normalize_transparent_frames(vehicle_id):
    try:
        from processing.exposure_normalize import normalize_exposure

        images = {}
        for index in range(1, TARGET_FRAMES + 1):
            image_bytes = _download_bytes(RAW_BUCKET, f'{vehicle_id}/transparent-{index}.png')
            with Image.open(io.BytesIO(image_bytes)) as image:
                images[index] = image.convert('RGBA').copy()

        for index, image in normalize_exposure(images).items():
            output = io.BytesIO()
            image.save(output, format='PNG', optimize=True)
            output.seek(0)
            minio_client.put_object(
                RAW_BUCKET,
                f'{vehicle_id}/transparent-{index}.png',
                output,
                length=output.getbuffer().nbytes,
                content_type='image/png',
            )
    except Exception as error:
        print(f'[{vehicle_id}] Exposure normalization skipped: {error}')


def handle_studio(fields):
    vehicle_id = fields['vehicleId']
    photo_index = int(fields['photoIndex'])
    heights = redis_client.hgetall(f'vehicle:{vehicle_id}:heights')
    ordered_heights = sorted(int(value) for value in heights.values())
    reference_index = round((len(ordered_heights) - 1) * 0.9) if ordered_heights else 0
    reference_height = ordered_heights[reference_index] if ordered_heights else 1000

    image_bytes = _download_bytes(RAW_BUCKET, fields['transparentKey'])
    with Image.open(io.BytesIO(image_bytes)) as image:
        vehicle_image = image.convert('RGBA').copy()

    studio_image = create_studio_image(vehicle_image, global_max_h=reference_height)
    output = io.BytesIO()
    studio_image.save(output, format='JPEG', quality=94, subsampling=0, optimize=True)
    output.seek(0)
    minio_client.put_object(
        PROCESSED_BUCKET,
        f'{vehicle_id}/processed-{photo_index}.jpg',
        output,
        length=output.getbuffer().nbytes,
        content_type='image/jpeg',
    )

    preview_image = studio_image.resize((1280, 720), Image.Resampling.LANCZOS)
    preview_output = io.BytesIO()
    preview_image.save(preview_output, format='JPEG', quality=86, optimize=True, progressive=True)
    preview_output.seek(0)
    minio_client.put_object(
        PROCESSED_BUCKET,
        f'{vehicle_id}/preview-{photo_index}.jpg',
        preview_output,
        length=preview_output.getbuffer().nbytes,
        content_type='image/jpeg',
    )

    notify_backend_frame_processed(vehicle_id, photo_index)
    redis_client.sadd(f'vehicle:{vehicle_id}:studio_done', str(photo_index))
    _expire_state_keys(vehicle_id)


def notify_backend_frame_processed(vehicle_id, photo_index):
    response = requests.patch(
        f'{BACKEND_URL}/internal/vehicles/{vehicle_id}/frame-processed',
        json={'photoIndex': photo_index},
        headers={'x-internal-token': INTERNAL_API_TOKEN},
        timeout=15,
    )
    response.raise_for_status()


def notify_backend_quality(vehicle_id, quality_score, warnings, metrics):
    try:
        payload = {'warnings': warnings, 'metrics': metrics}
        if quality_score is not None:
            payload['qualityScore'] = quality_score
        response = requests.post(
            f'{BACKEND_URL}/internal/vehicles/{vehicle_id}/quality',
            json=payload,
            headers={'x-internal-token': INTERNAL_API_TOKEN},
            timeout=15,
        )
        response.raise_for_status()
    except Exception as error:
        print(f'[{vehicle_id}] Could not report quality metrics: {error}')


def notify_backend_failed(vehicle_id):
    try:
        response = requests.post(
            f'{BACKEND_URL}/internal/vehicles/{vehicle_id}/failed',
            json={'error': 'A képfeldolgozó három próbálkozás után sem tudta befejezni a feladatot.'},
            headers={'x-internal-token': INTERNAL_API_TOKEN},
            timeout=15,
        )
        response.raise_for_status()
    except Exception as notify_error:
        print(f'[{vehicle_id}] Could not report terminal failure: {notify_error}')


def initialize_consumer_group():
    try:
        redis_client.xgroup_create(STREAM_NAME, CONSUMER_GROUP, '0', mkstream=True)
    except redis.ResponseError as error:
        if 'BUSYGROUP' not in str(error):
            raise


def process_message(message_id, fields):
    job_type = fields.get('type')
    handlers = {
        'select-frames': handle_select_frames,
        'process-bg-removal': handle_bg_removal,
        'process-studio': handle_studio,
    }

    handler = handlers.get(job_type)
    if handler is None:
        print(f'Ignoring unsupported job type: {job_type}')
        redis_client.xack(STREAM_NAME, CONSUMER_GROUP, message_id)
        return

    try:
        handler(fields)
        redis_client.xack(STREAM_NAME, CONSUMER_GROUP, message_id)
        redis_client.hdel('photo-processing-attempts', message_id)
    except Exception as error:
        attempts = redis_client.hincrby('photo-processing-attempts', message_id, 1)
        print(f"Job {message_id} ({job_type}) failed, attempt {attempts}: {error}")
        if attempts >= MAX_ATTEMPTS:
            redis_client.xadd(DEAD_LETTER_STREAM, {
                **fields,
                'originalMessageId': message_id,
                'error': str(error)[:500],
            })
            notify_backend_failed(fields.get('vehicleId', ''))
            redis_client.xack(STREAM_NAME, CONSUMER_GROUP, message_id)
            redis_client.hdel('photo-processing-attempts', message_id)


def claim_stale_messages():
    try:
        result = redis_client.xautoclaim(
            STREAM_NAME,
            CONSUMER_GROUP,
            CONSUMER_NAME,
            min_idle_time=STALE_AFTER_MS,
            start_id='0-0',
            count=5,
        )
        return result[1] if result and len(result) > 1 else []
    except redis.RedisError as error:
        print(f'Could not claim stale messages: {error}')
        return []


def worker_loop():
    print(f'Starting 36-frame worker: {CONSUMER_NAME}')
    initialize_consumer_group()
    last_claim = 0

    while True:
        try:
            now = time.time()
            if now - last_claim > 60:
                for message_id, fields in claim_stale_messages():
                    process_message(message_id, fields)
                last_claim = now

            streams = redis_client.xreadgroup(
                CONSUMER_GROUP,
                CONSUMER_NAME,
                {STREAM_NAME: '>'},
                count=1,
                block=5000,
            )
            for _, messages in streams:
                for message_id, fields in messages:
                    process_message(message_id, fields)
        except redis.RedisError as error:
            print(f'Redis error: {error}')
            time.sleep(5)
        except Exception as error:
            print(f'Worker loop error: {error}')
            time.sleep(5)


if __name__ == '__main__':
    worker_loop()
