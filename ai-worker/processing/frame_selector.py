import math


def _clamp(value, minimum=0.0, maximum=1.0):
    return max(minimum, min(maximum, value))


def quality_score(metrics):
    """Turn objective image measurements into a stable 0–100 quality score."""
    focus = _clamp(math.log1p(max(metrics.get('sharpness', 0.0), 0.0)) / math.log1p(650.0))
    exposure = 1.0 - _clamp(abs(metrics.get('brightness', 128.0) - 128.0) / 105.0)
    contrast = _clamp(metrics.get('contrast', 0.0) / 52.0)
    clipped = metrics.get('black_clip_ratio', 0.0) + metrics.get('white_clip_ratio', 0.0)
    clipping = 1.0 - _clamp(clipped / 0.24)
    return round(100.0 * (focus * 0.48 + exposure * 0.22 + contrast * 0.15 + clipping * 0.15), 2)


def analyze_image_quality(image_bytes):
    """Measure focus, exposure, contrast and clipping on a decoded candidate frame."""
    import cv2
    import numpy as np

    encoded = np.frombuffer(image_bytes, np.uint8)
    image = cv2.imdecode(encoded, cv2.IMREAD_GRAYSCALE)
    if image is None:
        return {
            'sharpness': 0.0,
            'brightness': 0.0,
            'contrast': 0.0,
            'black_clip_ratio': 1.0,
            'white_clip_ratio': 0.0,
            'score': 0.0,
        }

    height, width = image.shape
    longest_side = max(height, width)
    if longest_side > 960:
        scale = 960 / longest_side
        image = cv2.resize(image, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)

    metrics = {
        'sharpness': float(cv2.Laplacian(image, cv2.CV_64F).var()),
        'brightness': float(image.mean()),
        'contrast': float(image.std()),
        'black_clip_ratio': float(np.mean(image <= 5)),
        'white_clip_ratio': float(np.mean(image >= 250)),
    }
    metrics['score'] = quality_score(metrics)
    return metrics

def calculate_sharpness(image_bytes):
    """Return a resolution-normalized focus score based on Laplacian variance."""
    return analyze_image_quality(image_bytes)['sharpness']


def _temporal_groups(frame_count, output_count, group_size=7):
    groups = []
    bucket_size = frame_count / output_count

    for output_index in range(output_count):
        center = (output_index + 0.5) * bucket_size - 0.5
        candidates = sorted(
            range(frame_count),
            key=lambda index: abs(index - center),
        )[:group_size]
        groups.append([
            {
                'index': index,
                'alpha': 0.0,
                'beta': 0.0,
                'gamma': 0.0,
                'unwrapped_alpha': 0.0,
            }
            for index in candidates
        ])
    return groups


def _finite_number(value, fallback=0.0):
    try:
        parsed = float(value)
        return parsed if math.isfinite(parsed) else fallback
    except (TypeError, ValueError):
        return fallback


def select_optimal_frames(sensor_data, frame_keys, num_frames=36):
    """Build ordered candidate groups for an even, stable 360-degree spin."""
    frame_count = len(frame_keys)
    if num_frames < 1 or frame_count < num_frames:
        raise ValueError('The candidate count must be at least the requested output count')

    temporal_fallback = _temporal_groups(frame_count, num_frames)
    if not sensor_data or len(sensor_data) < 2:
        return temporal_fallback, 0.0, 0.0

    samples = sorted(
        (
            {
                'time': _finite_number(sample.get('time')),
                'alpha': _finite_number(sample.get('alpha')),
                'beta': _finite_number(sample.get('beta')),
                'gamma': _finite_number(sample.get('gamma')),
            }
            for sample in sensor_data
            if isinstance(sample, dict)
        ),
        key=lambda sample: sample['time'],
    )
    if len(samples) < 2 or samples[-1]['time'] <= samples[0]['time']:
        return temporal_fallback, 0.0, 0.0

    metrics = []
    duration = samples[-1]['time'] - samples[0]['time']
    sensor_cursor = 0
    for frame_index in range(frame_count):
        target_time = samples[0]['time'] + duration * frame_index / max(frame_count - 1, 1)
        while (
            sensor_cursor + 1 < len(samples)
            and abs(samples[sensor_cursor + 1]['time'] - target_time)
            <= abs(samples[sensor_cursor]['time'] - target_time)
        ):
            sensor_cursor += 1

        sample = samples[sensor_cursor]
        metrics.append({'index': frame_index, **sample})

    betas = sorted(metric['beta'] for metric in metrics)
    gammas = sorted(metric['gamma'] for metric in metrics)
    median_beta = betas[len(betas) // 2]
    median_gamma = gammas[len(gammas) // 2]

    unwrapped = [metrics[0]['alpha']]
    for previous, current in zip(metrics, metrics[1:]):
        delta = current['alpha'] - previous['alpha']
        if delta > 180:
            delta -= 360
        elif delta < -180:
            delta += 360
        unwrapped.append(unwrapped[-1] + delta)

    for metric, alpha in zip(metrics, unwrapped):
        metric['unwrapped_alpha'] = alpha

    rotation = unwrapped[-1] - unwrapped[0]
    if abs(rotation) < 180:
        return temporal_fallback, median_beta, median_gamma

    direction = 1 if rotation > 0 else -1
    usable_rotation = min(abs(rotation), 360.0) * direction
    groups = []
    for output_index in range(num_frames):
        target_angle = unwrapped[0] + usable_rotation * output_index / num_frames
        candidates = sorted(
            metrics,
            key=lambda metric: (
                abs(metric['unwrapped_alpha'] - target_angle),
                abs(metric['beta'] - median_beta) + abs(metric['gamma'] - median_gamma),
            ),
        )[:7]
        groups.append(candidates)

    return groups, median_beta, median_gamma
