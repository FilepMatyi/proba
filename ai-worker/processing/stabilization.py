import io
import math
import os

import cv2
import numpy as np
from PIL import Image, ImageOps


MAX_ROLL_CORRECTION = float(os.getenv('MAX_ROLL_CORRECTION', '3.5'))
MAX_VEHICLE_ROLL_CORRECTION = float(os.getenv('MAX_VEHICLE_ROLL_CORRECTION', '5.5'))
MAX_PROCESSING_SIDE = max(960, int(os.getenv('MAX_PROCESSING_SIDE', '1920')))
MIN_LINE_CONFIDENCE = 0.08


def _fold_line_angle(angle):
    """Fold an undirected line angle to the [-90, 90) interval."""
    return ((float(angle) + 90.0) % 180.0) - 90.0


def _weighted_median(values, weights):
    values = np.asarray(values, dtype=np.float64)
    weights = np.asarray(weights, dtype=np.float64)
    if values.size == 0:
        return 0.0
    if not np.any(weights > 0):
        return float(np.median(values))

    order = np.argsort(values)
    ordered_values = values[order]
    ordered_weights = weights[order]
    cutoff = ordered_weights.sum() * 0.5
    index = int(np.searchsorted(np.cumsum(ordered_weights), cutoff, side='left'))
    return float(ordered_values[min(index, ordered_values.size - 1)])


def _decode_rgb(image_source):
    if isinstance(image_source, (bytes, bytearray, memoryview)):
        encoded = np.frombuffer(image_source, dtype=np.uint8)
        bgr = cv2.imdecode(encoded, cv2.IMREAD_COLOR)
        if bgr is None:
            raise ValueError('The source image could not be decoded')
        return cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
    if isinstance(image_source, Image.Image):
        return np.asarray(ImageOps.exif_transpose(image_source).convert('RGB'))

    rgb = np.asarray(image_source)
    if rgb.ndim != 3 or rgb.shape[2] < 3:
        raise ValueError('A three-channel source image is required')
    return rgb[:, :, :3].astype(np.uint8, copy=False)


def estimate_visual_roll(image_source):
    """Estimate camera roll from long background horizontals and verticals.

    The centre/lower part of the frame is excluded so changing vehicle body
    perspective cannot dominate the estimate. Positive output means that the
    image content descends towards the right and needs a positive PIL rotation.
    """
    rgb = _decode_rgb(image_source)
    height, width = rgb.shape[:2]
    longest_side = max(height, width)
    if longest_side > 960:
        scale = 960.0 / longest_side
        rgb = cv2.resize(
            rgb,
            (max(2, int(round(width * scale))), max(2, int(round(height * scale)))),
            interpolation=cv2.INTER_AREA,
        )
        height, width = rgb.shape[:2]

    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    gray = cv2.GaussianBlur(gray, (5, 5), 0)
    edges = cv2.Canny(gray, 55, 145, apertureSize=3, L2gradient=True)

    # Prefer scenery around the subject: sky/building horizon above it plus
    # vertical references near the sides. This prevents wheel/body perspective
    # from being mistaken for camera roll at three-quarter viewpoints.
    region = np.zeros_like(edges)
    region[:max(1, int(height * 0.52)), :] = 255
    side_width = max(1, int(width * 0.18))
    region[:, :side_width] = 255
    region[:, width - side_width:] = 255
    edges = cv2.bitwise_and(edges, region)

    minimum_length = max(34, int(min(width, height) * 0.105))
    lines = cv2.HoughLinesP(
        edges,
        1,
        np.pi / 360,
        threshold=max(24, int(minimum_length * 0.55)),
        minLineLength=minimum_length,
        maxLineGap=max(10, int(minimum_length * 0.22)),
    )
    if lines is None:
        return {'angle': 0.0, 'confidence': 0.0, 'lineCount': 0}

    deviations = []
    weights = []
    for x1, y1, x2, y2 in lines[:, 0]:
        dx, dy = float(x2 - x1), float(y2 - y1)
        length = math.hypot(dx, dy)
        angle = _fold_line_angle(math.degrees(math.atan2(dy, dx)))

        if abs(angle) <= 12.0:
            deviation = angle
            orientation_weight = 1.0
        elif abs(abs(angle) - 90.0) <= 10.0:
            deviation = angle - 90.0 if angle > 0 else angle + 90.0
            orientation_weight = 0.86
        else:
            continue

        deviations.append(deviation)
        weights.append((length / max(minimum_length, 1)) ** 1.15 * orientation_weight)

    if len(deviations) < 2:
        return {'angle': 0.0, 'confidence': 0.0, 'lineCount': len(deviations)}

    centre = _weighted_median(deviations, weights)
    residuals = np.abs(np.asarray(deviations) - centre)
    mad = _weighted_median(residuals, weights)
    tolerance = max(1.4, min(4.0, mad * 2.8))
    keep = residuals <= tolerance
    kept_values = np.asarray(deviations)[keep]
    kept_weights = np.asarray(weights)[keep]
    if kept_values.size < 2:
        return {'angle': 0.0, 'confidence': 0.0, 'lineCount': len(deviations)}

    angle = float(np.average(kept_values, weights=kept_weights))
    spread = float(np.average(np.abs(kept_values - angle), weights=kept_weights))
    support = min(1.0, kept_weights.sum() / 8.0)
    consistency = max(0.0, 1.0 - spread / 5.0)
    confidence = support * consistency
    return {
        'angle': round(float(np.clip(angle, -12.0, 12.0)), 4),
        'confidence': round(confidence, 4),
        'lineCount': int(kept_values.size),
    }


def smooth_roll_measurements(measurements, radius=3, max_correction=None):
    """Create a robust circular roll plan, including the last-to-first seam."""
    if not measurements:
        return []

    limit = MAX_ROLL_CORRECTION if max_correction is None else abs(float(max_correction))
    count = len(measurements)
    angles = np.asarray([float(item.get('angle', 0.0)) for item in measurements])
    confidence = np.asarray([
        max(0.0, min(1.0, float(item.get('confidence', 0.0))))
        for item in measurements
    ])
    usable = confidence >= MIN_LINE_CONFIDENCE
    global_angle = _weighted_median(angles[usable], confidence[usable]) if np.any(usable) else 0.0

    planned = []
    for index in range(count):
        local_values = []
        local_weights = []
        for offset in range(-radius, radius + 1):
            neighbour = (index + offset) % count
            if confidence[neighbour] < MIN_LINE_CONFIDENCE:
                continue
            distance_weight = math.exp(-0.5 * (offset / max(radius * 0.72, 0.7)) ** 2)
            local_values.append(angles[neighbour])
            local_weights.append(confidence[neighbour] * distance_weight)

        if local_values:
            local_centre = _weighted_median(local_values, local_weights)
            values = np.asarray(local_values)
            weights = np.asarray(local_weights)
            close = np.abs(values - local_centre) <= 3.5
            smoothed = float(np.average(values[close], weights=weights[close]))
            local_confidence = min(1.0, float(weights[close].sum()))
        else:
            smoothed = global_angle
            local_confidence = 0.0

        planned.append({
            **measurements[index],
            'smoothedAngle': round(smoothed, 4),
            'planConfidence': round(local_confidence, 4),
            'limited': abs(smoothed) > limit + 1e-6,
        })

    # One more gentle circular low-pass prevents visible angular steps when a
    # scene suddenly gains or loses a strong horizon reference.
    corrections = np.clip(
        np.asarray([item['smoothedAngle'] for item in planned]),
        -limit,
        limit,
    )
    plan_confidence = np.asarray([item['planConfidence'] for item in planned])
    for _ in range(2):
        filtered = []
        for index in range(count):
            values = []
            weights = []
            for offset in range(-radius, radius + 1):
                neighbour = (index + offset) % count
                distance_weight = math.exp(-0.5 * (offset / max(radius * 0.72, 0.7)) ** 2)
                values.append(corrections[neighbour])
                weights.append(distance_weight * (0.35 + 0.65 * plan_confidence[neighbour]))
            filtered.append(float(np.average(values, weights=weights)))
        corrections = np.asarray(filtered)

    for item, correction in zip(planned, corrections):
        item['correction'] = round(float(np.clip(correction, -limit, limit)), 4)
    return planned


def _border_fill(rgb):
    height, width = rgb.shape[:2]
    thickness = max(1, min(height, width) // 80)
    border = np.concatenate((
        rgb[:thickness].reshape(-1, 3),
        rgb[-thickness:].reshape(-1, 3),
        rgb[:, :thickness].reshape(-1, 3),
        rgb[:, -thickness:].reshape(-1, 3),
    ))
    return tuple(int(value) for value in np.median(border, axis=0))


def level_source_image(image_bytes, correction):
    """Rotate before segmentation, expanding the canvas so the car is not cropped."""
    correction = float(correction)
    with Image.open(io.BytesIO(image_bytes)) as source:
        source = ImageOps.exif_transpose(source).convert('RGB')
        resized = max(source.size) > MAX_PROCESSING_SIDE
        if resized:
            source.thumbnail(
                (MAX_PROCESSING_SIDE, MAX_PROCESSING_SIDE),
                Image.Resampling.LANCZOS,
            )
        if abs(correction) < 0.04 and not resized:
            return image_bytes
        fill = _border_fill(np.asarray(source))
        levelled = source
        if abs(correction) >= 0.04:
            levelled = source.rotate(
                correction,
                resample=Image.Resampling.BICUBIC,
                expand=True,
                fillcolor=fill,
            )
    output = io.BytesIO()
    levelled.save(output, format='JPEG', quality=96, subsampling=0, optimize=True)
    return output.getvalue()


def apply_sequence_roll_plan(images, corrections):
    """Apply the scene-derived roll plan to transparent images after masking."""
    result = {}
    for index, image in images.items():
        correction = float(corrections.get(index, 0.0))
        image = image.convert('RGBA')
        if abs(correction) >= 0.04:
            image = image.rotate(
                correction,
                resample=Image.Resampling.BICUBIC,
                expand=True,
                fillcolor=(0, 0, 0, 0),
            )
        result[index] = image
    return result


def estimate_vehicle_roll(vehicle_image):
    """Estimate the vehicle's own ground line from its two lower contact zones.

    This deliberately ignores the central underside, tow bars and isolated mask
    noise. It works for side, three-quarter, front and rear views without
    requiring vehicle-specific wheel landmark weights.
    """
    image = vehicle_image.convert('RGBA')
    alpha = np.asarray(image.getchannel('A'))
    binary = alpha >= 128
    ys, xs = np.where(binary)
    if xs.size < 200:
        return {'angle': 0.0, 'confidence': 0.0, 'contactDelta': 0.0}

    x0, x1 = int(xs.min()), int(xs.max()) + 1
    y0, y1 = int(ys.min()), int(ys.max()) + 1
    width = x1 - x0
    height = y1 - y0
    if width < 40 or height < 30:
        return {'angle': 0.0, 'confidence': 0.0, 'contactDelta': 0.0}

    bottom = np.full(alpha.shape[1], np.nan, dtype=np.float64)
    for x in range(x0, x1):
        column = np.flatnonzero(binary[:, x])
        if column.size:
            bottom[x] = float(column[-1])

    def contact_point(start_ratio, end_ratio):
        start = x0 + int(round(width * start_ratio))
        end = x0 + int(round(width * end_ratio))
        columns = np.arange(max(x0, start), min(x1, end))
        values = bottom[columns]
        valid = np.isfinite(values)
        columns, values = columns[valid], values[valid]
        if values.size < max(8, int(width * 0.045)):
            return None

        threshold = float(np.percentile(values, 88))
        contact = values >= threshold
        contact_columns = columns[contact]
        contact_values = values[contact]
        if contact_values.size < 3:
            return None
        return (
            float(np.median(contact_columns)),
            float(np.median(contact_values)),
            int(contact_values.size),
        )

    left = contact_point(0.04, 0.46)
    right = contact_point(0.54, 0.96)
    if left is None or right is None:
        return {'angle': 0.0, 'confidence': 0.0, 'contactDelta': 0.0}

    dx = right[0] - left[0]
    dy = right[1] - left[1]
    if dx < width * 0.28:
        return {'angle': 0.0, 'confidence': 0.0, 'contactDelta': round(dy, 2)}

    angle = math.degrees(math.atan2(dy, dx))
    support = min(1.0, (left[2] + right[2]) / max(width * 0.13, 1.0))
    separation = min(1.0, dx / max(width * 0.62, 1.0))
    confidence = support * separation
    if abs(angle) > 12.0:
        confidence *= 0.15
    return {
        'angle': round(float(np.clip(angle, -12.0, 12.0)), 4),
        'confidence': round(confidence, 4),
        'contactDelta': round(dy, 2),
    }


def stabilize_vehicle_sequence(images):
    """Level transparent vehicles with a circularly smoothed ground-line plan."""
    if not images:
        return images, {
            'vehicleLeveling': True,
            'vehicleCorrectedFrames': 0,
            'maximumVehicleCorrectionDegrees': 0.0,
            'contactDeltaBefore': 0.0,
            'contactDeltaAfter': 0.0,
        }

    indexes = sorted(images)
    measurements = [estimate_vehicle_roll(images[index]) for index in indexes]
    plan = smooth_roll_measurements(
        measurements,
        radius=2,
        max_correction=MAX_VEHICLE_ROLL_CORRECTION,
    )
    result = {}
    for index, item in zip(indexes, plan):
        image = images[index].convert('RGBA')
        correction = float(item['correction'])
        if abs(correction) >= 0.04:
            image = image.rotate(
                correction,
                resample=Image.Resampling.BICUBIC,
                expand=True,
                fillcolor=(0, 0, 0, 0),
            )
        result[index] = image

    after = [estimate_vehicle_roll(result[index]) for index in indexes]
    before_delta = float(np.median([abs(item['contactDelta']) for item in measurements]))
    after_delta = float(np.median([abs(item['contactDelta']) for item in after]))
    report = {
        'vehicleLeveling': True,
        'vehicleCorrectedFrames': sum(abs(item['correction']) >= 0.04 for item in plan),
        'maximumVehicleCorrectionDegrees': round(
            max((abs(item['correction']) for item in plan), default=0.0), 3
        ),
        'vehicleLimitedFrames': sum(bool(item['limited']) for item in plan),
        'contactDeltaBefore': round(before_delta, 2),
        'contactDeltaAfter': round(after_delta, 2),
    }
    return result, report


def _circular_robust_smooth(values, radius=2):
    values = np.asarray(values, dtype=np.float64)
    if values.size < 3:
        return values.copy()

    result = []
    count = values.size
    for index in range(count):
        local = np.asarray([
            values[(index + offset) % count]
            for offset in range(-radius, radius + 1)
        ])
        median = float(np.median(local))
        deviation = max(float(np.median(np.abs(local - median))) * 3.0, 1.0)
        local = np.clip(local, median - deviation, median + deviation)
        weights = np.asarray([
            math.exp(-0.5 * (offset / max(radius * 0.72, 0.7)) ** 2)
            for offset in range(-radius, radius + 1)
        ])
        result.append(float(np.average(local, weights=weights)))
    return np.asarray(result)


def build_sequence_layout(images):
    """Smooth apparent vehicle size across a complete circular 36-frame orbit."""
    if not images:
        return {}, {
            'frameCount': 0,
            'heightJitterBefore': 0.0,
            'heightJitterAfter': 0.0,
        }

    indexes = sorted(images)
    heights = []
    widths = []
    for index in indexes:
        image = images[index].convert('RGBA')
        bbox = image.getbbox()
        if bbox:
            widths.append(max(1, bbox[2] - bbox[0]))
            heights.append(max(1, bbox[3] - bbox[1]))
        else:
            widths.append(max(1, image.width))
            heights.append(max(1, image.height))

    raw_heights = np.asarray(heights, dtype=np.float64)
    smoothed = _circular_robust_smooth(raw_heights, radius=2)
    median_height = max(float(np.median(smoothed)), 1.0)

    # Preserve slow perspective changes, but suppress camera-distance breathing.
    damped = median_height + (smoothed - median_height) * 0.35
    reference_height = max(float(np.percentile(damped, 90)), 1.0)
    target_ratios = np.clip(damped / reference_height, 0.84, 1.02)

    def circular_jitter(values):
        normalized = np.asarray(values, dtype=np.float64) / max(float(np.median(values)), 1.0)
        return float(np.median(np.abs(normalized - np.roll(normalized, 1))))

    layout = {}
    for position, index in enumerate(indexes):
        layout[index] = {
            'sourceWidth': int(widths[position]),
            'sourceHeight': int(heights[position]),
            'smoothedHeight': round(float(smoothed[position]), 2),
            'targetHeightRatio': round(float(target_ratios[position]), 5),
        }

    report = {
        'frameCount': len(indexes),
        'heightJitterBefore': round(circular_jitter(raw_heights), 5),
        'heightJitterAfter': round(circular_jitter(damped), 5),
        'minimumTargetHeightRatio': round(float(target_ratios.min()), 4),
        'maximumTargetHeightRatio': round(float(target_ratios.max()), 4),
        'circularSmoothing': True,
    }
    return layout, report
