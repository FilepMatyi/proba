import io
import math
import os

import cv2
import numpy as np
from PIL import Image, ImageOps


MAX_ROLL_CORRECTION = float(os.getenv('MAX_ROLL_CORRECTION', '3.5'))
MAX_VEHICLE_ROLL_CORRECTION = float(os.getenv('MAX_VEHICLE_ROLL_CORRECTION', '2.5'))
MAX_PERSPECTIVE_WARP = float(os.getenv('MAX_PERSPECTIVE_WARP', '0.9'))
TARGET_CONTACT_ANGLE_DEGREES = float(os.getenv('TARGET_CONTACT_ANGLE_DEGREES', '1.0'))
MIN_WHEEL_PAIR_ASPECT_RATIO = float(os.getenv('MIN_WHEEL_PAIR_ASPECT_RATIO', '1.0'))
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
    return {
        index: apply_roll_correction(image, corrections.get(index, 0.0))
        for index, image in images.items()
    }


def apply_sequence_alignment_plan(images, corrections, perspective_warps):
    """Apply combined roll and anchored perspective rectification once."""
    return {
        index: apply_vehicle_transform(
            image,
            corrections.get(index, 0.0),
            perspective_warps.get(index, 0.0),
        )
        for index, image in images.items()
    }


def combine_scene_and_vehicle_roll(scene_plan, vehicle_plan, direct_vehicle_indexes=None):
    """Add scene roll and the small perspective-normalized vehicle residual.

    ``direct_vehicle_indexes`` is retained for compatibility with older callers,
    but it no longer changes the arithmetic. A wheel-contact slope is not a
    replacement for scene roll: in a three-quarter view it mostly describes
    perspective, not a tilted camera.
    """
    indexes = set(scene_plan) | set(vehicle_plan)
    return {
        index: float(scene_plan.get(index, 0.0)) + float(vehicle_plan.get(index, 0.0))
        for index in indexes
    }


def apply_roll_correction(image, correction):
    """Apply one loss-minimising expanded rotation to an RGBA frame."""
    return apply_vehicle_transform(image, correction, 0.0)


def apply_vehicle_transform(image, correction=0.0, perspective_warp=0.0):
    """Rotate and apply an anchored vertical perspective warp in one resample.

    The warp scales each image column around a horizon near the roof. Wheel
    contacts can therefore move substantially while the roofline moves only a
    little and every door pillar remains vertical. This is the safe 2D
    approximation of lowering the camera toward vehicle eye level.
    """
    image = image.convert('RGBA')
    bbox = image.getbbox()
    if bbox:
        image = image.crop(bbox)
    correction = float(correction)
    perspective_warp = float(perspective_warp)
    if abs(correction) < 0.04 and abs(perspective_warp) < 0.001:
        return image.copy()

    rgba = np.asarray(image)
    height, width = rgba.shape[:2]
    center_x = (width - 1) / 2.0
    center_y = (height - 1) / 2.0
    rotation = np.vstack((
        cv2.getRotationMatrix2D((center_x, center_y), correction, 1.0),
        (0.0, 0.0, 1.0),
    ))
    anchor_y = height * 0.28

    def apply_perspective(points):
        x_values = points[0]
        y_values = points[1]
        scales = 1.0 + perspective_warp * (x_values - center_x) / max(width, 1)
        return np.vstack((
            x_values,
            anchor_y + (y_values - anchor_y) * scales,
            np.ones_like(x_values),
        ))

    corners = np.asarray((
        (0.0, 0.0, 1.0),
        (width - 1.0, 0.0, 1.0),
        (0.0, height - 1.0, 1.0),
        (width - 1.0, height - 1.0, 1.0),
    )).T
    transformed = apply_perspective(rotation @ corners)
    min_x, min_y = np.floor(transformed[:2].min(axis=1))
    max_x, max_y = np.ceil(transformed[:2].max(axis=1))
    output_width = max(1, int(max_x - min_x + 1))
    output_height = max(1, int(max_y - min_y + 1))

    # Premultiply before interpolation to prevent coloured source-background
    # pixels from bleeding into the transparent vehicle edge.
    work = rgba.astype(np.float32)
    alpha = work[:, :, 3:4] / 255.0
    work[:, :, :3] *= alpha
    output_x, output_y = np.meshgrid(
        np.arange(output_width, dtype=np.float32) + np.float32(min_x),
        np.arange(output_height, dtype=np.float32) + np.float32(min_y),
    )
    column_scale = (
        1.0
        + perspective_warp * (output_x - np.float32(center_x)) / max(width, 1)
    )
    column_scale = np.where(
        np.abs(column_scale) >= 0.08,
        column_scale,
        np.where(column_scale < 0, -0.08, 0.08),
    )
    intermediate_y = (
        np.float32(anchor_y)
        + (output_y - np.float32(anchor_y)) / column_scale
    )
    inverse_rotation = np.linalg.inv(rotation)
    map_x = (
        inverse_rotation[0, 0] * output_x
        + inverse_rotation[0, 1] * intermediate_y
        + inverse_rotation[0, 2]
    ).astype(np.float32)
    map_y = (
        inverse_rotation[1, 0] * output_x
        + inverse_rotation[1, 1] * intermediate_y
        + inverse_rotation[1, 2]
    ).astype(np.float32)
    warped = cv2.remap(
        work,
        map_x,
        map_y,
        interpolation=cv2.INTER_CUBIC,
        borderMode=cv2.BORDER_CONSTANT,
        borderValue=(0, 0, 0, 0),
    )
    warped_alpha = np.clip(warped[:, :, 3:4], 0.0, 255.0)
    safe_alpha = np.maximum(warped_alpha / 255.0, 1.0 / 255.0)
    warped[:, :, :3] = np.where(
        warped_alpha > 0.5,
        warped[:, :, :3] / safe_alpha,
        0.0,
    )
    warped[:, :, 3:4] = warped_alpha
    return Image.fromarray(np.clip(warped, 0, 255).astype(np.uint8), 'RGBA')


def _estimate_wheel_contact_roll(
    vehicle_image,
    minimum_aspect_ratio=MIN_WHEEL_PAIR_ASPECT_RATIO,
):
    """Measure roll from the two visible tire contact points.

    Circle detection is used only to locate the wheels horizontally. The
    contact Y values then come from the alpha silhouette directly below each
    detected wheel, so bright rims, perspective-scaled wheels and dark body
    trim do not move the ground reference. Returning zero confidence lets the
    caller fall back to the silhouette estimator for front/rear views where a
    separated wheel pair is not visible.
    """
    image = vehicle_image.convert('RGBA')
    rgba = np.asarray(image)
    alpha = rgba[:, :, 3]
    ys, xs = np.where(alpha >= 128)
    if xs.size < 400:
        return {'angle': 0.0, 'confidence': 0.0, 'contactDelta': 0.0, 'method': 'wheels'}

    x0, x1 = int(xs.min()), int(xs.max()) + 1
    y0, y1 = int(ys.min()), int(ys.max()) + 1
    crop = rgba[y0:y1, x0:x1]
    height, width = crop.shape[:2]
    if width < 120 or height < 80:
        return {'angle': 0.0, 'confidence': 0.0, 'contactDelta': 0.0, 'method': 'wheels'}
    aspect_ratio = width / max(height, 1)
    # Below this ratio the car is too close to a head-on/rear view for two
    # classical wheel circles to be distinguished reliably from grille and
    # bumper arcs. Those frames are filled from neighbouring wheel anchors.
    if aspect_ratio < float(minimum_aspect_ratio):
        return {
            'angle': 0.0,
            'confidence': 0.0,
            'contactDelta': 0.0,
            'method': 'wheels',
            'aspectRatio': round(aspect_ratio, 4),
        }

    scale = min(1.0, 960.0 / max(width, height))
    if scale < 1.0:
        work_w = max(1, int(round(width * scale)))
        work_h = max(1, int(round(height * scale)))
        rgb = cv2.resize(crop[:, :, :3], (work_w, work_h), interpolation=cv2.INTER_AREA)
        work_alpha = cv2.resize(crop[:, :, 3], (work_w, work_h), interpolation=cv2.INTER_AREA)
    else:
        rgb = crop[:, :, :3].copy()
        work_alpha = crop[:, :, 3].copy()
        work_h, work_w = height, width

    # Transparent pixels are made white so the cutout boundary cannot become
    # a false dark circle. Wheels live in the lower 58% of the vehicle bbox.
    rgb[work_alpha < 32] = 255
    lower_top = int(round(work_h * 0.42))
    lower_rgb = rgb[lower_top:]
    gray = cv2.cvtColor(lower_rgb, cv2.COLOR_RGB2GRAY)
    gray = cv2.GaussianBlur(gray, (7, 7), 1.5)
    # Keep enough range for the far wheel in strong three-quarter views. The
    # later neutral-dark, edge-density and contact-depth gates reject small
    # grille/bumper circles more reliably than an aggressive radius cutoff.
    min_radius = max(7, int(round(work_h * 0.035)))
    max_radius = max(min_radius + 2, int(round(work_h * 0.24)))
    # A tight alpha crop cuts exactly through the outer tire tangent. Padding
    # only the Hough workspace lets the far wheel at the image edge form a full
    # circle without changing any returned source coordinates.
    hough_padding = max(18, int(round(max_radius * 0.85)))
    hough_gray = cv2.copyMakeBorder(
        gray,
        0,
        0,
        hough_padding,
        hough_padding,
        cv2.BORDER_CONSTANT,
        value=255,
    )
    circles = cv2.HoughCircles(
        hough_gray,
        cv2.HOUGH_GRADIENT,
        dp=1.2,
        minDist=max(24, int(round(work_w * 0.16))),
        param1=90,
        param2=18,
        minRadius=min_radius,
        maxRadius=max_radius,
    )
    if circles is None:
        return {'angle': 0.0, 'confidence': 0.0, 'contactDelta': 0.0, 'method': 'wheels'}

    def alpha_contact(cx, radius):
        # Use the deepest solid alpha columns near the detected wheel center.
        # The 86th percentile rejects isolated segmentation whiskers while
        # preserving the real tire footprint across perspective changes.
        half_width = max(int(round(radius * 0.52)), int(round(work_w * 0.022)))
        start = max(0, int(round(cx)) - half_width)
        end = min(work_w, int(round(cx)) + half_width + 1)
        bottoms = []
        for column_index in range(start, end):
            column = np.flatnonzero(work_alpha[:, column_index] >= 128)
            if column.size:
                bottoms.append(float(column[-1]))
        if len(bottoms) < max(6, int(round(half_width * 0.35))):
            return None
        return float(np.percentile(bottoms, 96))

    candidates = []
    yy, xx = np.ogrid[:work_h, :work_w]
    full_gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    full_hsv = cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV)
    full_edges = cv2.Canny(full_gray, 55, 135)
    for padded_cx, local_cy, radius in circles[0]:
        cx = float(padded_cx - hough_padding)
        cy = float(local_cy + lower_top)
        radius = float(radius)
        # In strong rear/front three-quarter views the far wheel can sit almost
        # on the tight alpha crop edge. Keep it eligible; later appearance and
        # contact-depth checks still reject mirrors and bumper arcs.
        if not (work_w * 0.01 <= cx <= work_w * 0.99):
            continue
        if not (work_h * 0.42 <= cy <= work_h * 0.94):
            continue

        distance = np.sqrt((xx - cx) ** 2 + (yy - cy) ** 2)
        ring = (distance >= radius * 0.62) & (distance <= radius * 1.16)
        ring_alpha = work_alpha[ring]
        opaque = ring_alpha >= 80
        ring_alpha_coverage = float(np.mean(opaque))
        if opaque.size < 40 or ring_alpha_coverage < 0.42:
            continue
        ring_pixels = full_gray[ring][opaque]
        if ring_pixels.size < 30:
            continue
        darkness = 1.0 - float(np.mean(ring_pixels)) / 255.0
        contrast = min(1.0, float(np.std(ring_pixels)) / 70.0)
        if darkness < 0.34:
            continue

        disk = (distance <= radius * 0.96) & (work_alpha >= 80)
        if int(np.count_nonzero(disk)) < 80:
            continue
        disk_saturation = full_hsv[:, :, 1][disk]
        disk_value = full_hsv[:, :, 2][disk]
        neutral_dark = float(np.mean((disk_saturation < 92) & (disk_value < 185)))
        edge_density = float(np.mean(full_edges[disk] > 0))
        neutral_dark_map = (
            (full_hsv[:, :, 1] < 92)
            & (full_hsv[:, :, 2] < 185)
            & (work_alpha >= 80)
        )
        ring_neutral_dark = float(np.mean(neutral_dark_map[ring]))
        angular_hits = []
        for theta in np.linspace(0.0, math.tau, 28, endpoint=False):
            hit = False
            for radial_ratio in (0.72, 0.88, 1.04):
                sample_x = int(round(cx + math.cos(theta) * radius * radial_ratio))
                sample_y = int(round(cy + math.sin(theta) * radius * radial_ratio))
                if not (1 <= sample_x < work_w - 1 and 1 <= sample_y < work_h - 1):
                    continue
                if np.any(neutral_dark_map[sample_y - 1:sample_y + 2, sample_x - 1:sample_x + 2]):
                    hit = True
                    break
            angular_hits.append(hit)
        angular_dark_coverage = float(np.mean(angular_hits)) if angular_hits else 0.0
        # Tires and alloy wheels are predominantly neutral dark material with
        # dense circular/spoke edges. Painted doors and smooth bumpers may
        # trigger Hough, but fail one or both of these appearance checks.
        if neutral_dark < 0.28 or edge_density < 0.055:
            continue

        contact = alpha_contact(cx, radius)
        if contact is None:
            continue
        contact_depth = contact - cy
        # A real tire contact lies roughly one detected radius below its
        # centre. This rejects circles found in bumpers, grilles and lights,
        # whose local silhouette bottom is much farther away.
        if not (radius * 0.68 <= contact_depth <= radius * 2.8):
            continue
        if contact < work_h * 0.71:
            continue

        # Prefer the outer tire circle over smaller rim circles returned for
        # the same wheel. Perspective may legitimately make one radius smaller.
        radius_score = min(1.0, radius / max(work_h * 0.15, 1.0))
        vertical_score = 1.0 - min(1.0, abs(cy - work_h * 0.72) / max(work_h * 0.28, 1.0))
        score = (
            darkness * 0.30
            + contrast * 0.12
            + radius_score * 0.18
            + vertical_score * 0.12
            + min(1.0, neutral_dark / 0.7) * 0.16
            + min(1.0, edge_density / 0.13) * 0.12
        )
        candidates.append({
            'x': cx,
            'y': cy,
            'radius': radius,
            'contact': contact,
            'score': score,
            'neutralDark': neutral_dark,
            'edgeDensity': edge_density,
            'ringAlphaCoverage': ring_alpha_coverage,
            'ringNeutralDark': ring_neutral_dark,
            'angularDarkCoverage': angular_dark_coverage,
        })

    if len(candidates) < 2:
        return {
            'angle': 0.0,
            'confidence': 0.0,
            'contactDelta': 0.0,
            'method': 'wheels',
            'candidateCount': len(candidates),
            'wheelCandidates': [
                {
                    'x': round(x0 + item['x'] / max(scale, 1e-6), 1),
                    'y': round(y0 + item['y'] / max(scale, 1e-6), 1),
                    'contact': round(y0 + item['contact'] / max(scale, 1e-6), 1),
                    'radius': round(item['radius'] / max(scale, 1e-6), 1),
                    'score': round(item['score'], 3),
                }
                for item in candidates
            ],
        }

    best_pair = None
    best_pair_score = -1.0
    for left_index, first in enumerate(candidates):
        for second in candidates[left_index + 1:]:
            left, right = sorted((first, second), key=lambda item: item['x'])
            separation = right['x'] - left['x']
            if separation < work_w * 0.36:
                continue
            if left['x'] > work_w * 0.58 or right['x'] < work_w * 0.42:
                continue
            radius_ratio = max(left['radius'], right['radius']) / max(
                min(left['radius'], right['radius']), 1.0
            )
            if radius_ratio > 4.0:
                continue
            separation_score = min(1.0, separation / max(work_w * 0.62, 1.0))
            pair_score = left['score'] + right['score'] + separation_score * 0.45
            if pair_score > best_pair_score:
                best_pair = (left, right)
                best_pair_score = pair_score

    if best_pair is None:
        return {'angle': 0.0, 'confidence': 0.0, 'contactDelta': 0.0, 'method': 'wheels'}

    left, right = best_pair
    left_contact = left['contact']
    right_contact = right['contact']

    dx = right['x'] - left['x']
    dy = right_contact - left_contact
    angle = math.degrees(math.atan2(dy, dx))
    confidence = min(1.0, max(0.0, (best_pair_score - 0.9) / 1.55))
    if abs(angle) > 18.0:
        confidence *= 0.25
    return {
        'angle': round(float(np.clip(angle, -18.0, 18.0)), 4),
        'confidence': round(confidence, 4),
        'contactDelta': round(float(dy / max(scale, 1e-6)), 2),
        'method': 'wheels',
        'aspectRatio': round(aspect_ratio, 4),
        'wheelContacts': [
            (
                round(x0 + left['x'] / max(scale, 1e-6), 1),
                round(y0 + left_contact / max(scale, 1e-6), 1),
            ),
            (
                round(x0 + right['x'] / max(scale, 1e-6), 1),
                round(y0 + right_contact / max(scale, 1e-6), 1),
            ),
        ],
        'wheelCenters': [
            (
                round(x0 + left['x'] / max(scale, 1e-6), 1),
                round(y0 + left['y'] / max(scale, 1e-6), 1),
            ),
            (
                round(x0 + right['x'] / max(scale, 1e-6), 1),
                round(y0 + right['y'] / max(scale, 1e-6), 1),
            ),
        ],
        'wheelRadii': [
            round(left['radius'] / max(scale, 1e-6), 1),
            round(right['radius'] / max(scale, 1e-6), 1),
        ],
        'candidateCount': len(candidates),
        'wheelCandidates': [
            {
                'x': round(x0 + item['x'] / max(scale, 1e-6), 1),
                'y': round(y0 + item['y'] / max(scale, 1e-6), 1),
                'contact': round(y0 + item['contact'] / max(scale, 1e-6), 1),
                'radius': round(item['radius'] / max(scale, 1e-6), 1),
                'score': round(item['score'], 3),
            }
            for item in candidates
        ],
        'wheelFeatures': [
            {
                'neutralDark': round(left['neutralDark'], 3),
                'edgeDensity': round(left['edgeDensity'], 3),
                'ringAlphaCoverage': round(left['ringAlphaCoverage'], 3),
                'ringNeutralDark': round(left['ringNeutralDark'], 3),
                'angularDarkCoverage': round(left['angularDarkCoverage'], 3),
                'radius': round(left['radius'], 1),
                'contactDepthRatio': round(
                    (left['contact'] - left['y']) / max(left['radius'], 1.0), 3
                ),
            },
            {
                'neutralDark': round(right['neutralDark'], 3),
                'edgeDensity': round(right['edgeDensity'], 3),
                'ringAlphaCoverage': round(right['ringAlphaCoverage'], 3),
                'ringNeutralDark': round(right['ringNeutralDark'], 3),
                'angularDarkCoverage': round(right['angularDarkCoverage'], 3),
                'radius': round(right['radius'], 1),
                'contactDepthRatio': round(
                    (right['contact'] - right['y']) / max(right['radius'], 1.0), 3
                ),
            },
        ],
    }


def estimate_wheel_contacts(
    vehicle_image,
    minimum_aspect_ratio=MIN_WHEEL_PAIR_ASPECT_RATIO,
):
    """Return reliable per-wheel contact geometry in source-image pixels.

    The two contact rows intentionally remain different in perspective views.
    They are compositor anchors, not a request to rotate the whole vehicle.
    """
    measurement = _estimate_wheel_contact_roll(
        vehicle_image,
        minimum_aspect_ratio=minimum_aspect_ratio,
    )
    contacts = measurement.get('wheelContacts') or []
    radii = measurement.get('wheelRadii') or []
    confidence = float(measurement.get('confidence', 0.0))
    if confidence < MIN_LINE_CONFIDENCE or len(contacts) != 2 or len(radii) != 2:
        return []
    return [
        {
            'x': float(point[0]),
            'y': float(point[1]),
            'radius': float(radius),
            'confidence': confidence,
        }
        for point, radius in zip(contacts, radii)
    ]


def estimate_vehicle_roll(vehicle_image):
    """Estimate the vehicle's own ground line from its two lower contact zones.

    This deliberately ignores the central underside, tow bars and isolated mask
    noise. It works for side, three-quarter, front and rear views without
    requiring vehicle-specific wheel landmark weights.
    """
    wheel_estimate = _estimate_wheel_contact_roll(vehicle_image)
    if wheel_estimate['confidence'] >= MIN_LINE_CONFIDENCE:
        return wheel_estimate

    image = vehicle_image.convert('RGBA')
    alpha = np.asarray(image.getchannel('A'))
    binary = alpha >= 128
    ys, xs = np.where(binary)
    if xs.size < 200:
        return {'angle': 0.0, 'confidence': 0.0, 'contactDelta': 0.0, 'method': 'silhouette'}

    x0, x1 = int(xs.min()), int(xs.max()) + 1
    y0, y1 = int(ys.min()), int(ys.max()) + 1
    width = x1 - x0
    height = y1 - y0
    if width < 40 or height < 30:
        return {'angle': 0.0, 'confidence': 0.0, 'contactDelta': 0.0, 'method': 'silhouette'}
    aspect_ratio = width / max(height, 1)

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
        return {
            'angle': 0.0,
            'confidence': 0.0,
            'contactDelta': 0.0,
            'method': 'silhouette',
            'aspectRatio': round(aspect_ratio, 4),
        }

    dx = right[0] - left[0]
    dy = right[1] - left[1]
    if dx < width * 0.28:
        return {
            'angle': 0.0,
            'confidence': 0.0,
            'contactDelta': round(dy, 2),
            'method': 'silhouette',
            'aspectRatio': round(aspect_ratio, 4),
        }

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
        'method': 'silhouette',
        'aspectRatio': round(aspect_ratio, 4),
    }


def _fit_orbit_wheel_roll(measurements):
    """Fit the smooth perspective slope shared by a 360° wheel orbit.

    The projected ground line crosses zero at side/front/rear views and repeats
    twice during one revolution. A robust second-harmonic fit supplies safe
    corrections for views where the two wheels overlap or grille arcs make
    direct detection ambiguous. Direct wheel measurements still win wherever
    both contacts are genuinely visible.
    """
    count = len(measurements)
    reliable = [
        (index, item)
        for index, item in enumerate(measurements)
        if item.get('method') == 'wheels'
        and float(item.get('confidence', 0.0)) >= MIN_LINE_CONFIDENCE
    ]
    if count < 12 or len(reliable) < 6:
        return {}, 0.0

    positions = np.asarray([index for index, _ in reliable], dtype=np.float64)
    angles = np.asarray([float(item.get('angle', 0.0)) for _, item in reliable])
    base_weights = np.asarray([
        max(MIN_LINE_CONFIDENCE, float(item.get('confidence', 0.0)))
        for _, item in reliable
    ])
    phase = math.tau * 2.0 * positions / count
    design = np.column_stack((np.sin(phase), np.cos(phase)))
    weights = base_weights.copy()
    coefficients = np.zeros(2, dtype=np.float64)
    for _ in range(4):
        weighted_design = design * np.sqrt(weights)[:, None]
        weighted_angles = angles * np.sqrt(weights)
        coefficients, *_ = np.linalg.lstsq(weighted_design, weighted_angles, rcond=None)
        residual = angles - design @ coefficients
        scale = max(0.8, float(np.median(np.abs(residual))) * 1.4826)
        robust = np.minimum(1.0, (2.2 * scale) / np.maximum(np.abs(residual), 1e-6))
        weights = base_weights * robust

    amplitude = min(12.0, float(np.linalg.norm(coefficients)))
    raw_amplitude = max(float(np.linalg.norm(coefficients)), 1e-6)
    coefficients *= amplitude / raw_amplitude
    all_positions = np.arange(count, dtype=np.float64)
    all_phase = math.tau * 2.0 * all_positions / count
    predictions = (
        np.sin(all_phase) * coefficients[0]
        + np.cos(all_phase) * coefficients[1]
    )
    return {
        index + 1: float(prediction)
        for index, prediction in enumerate(predictions)
    }, amplitude


def build_vehicle_alignment_plan(images):
    """Plan conservative roll plus an eye-level anchored perspective warp.

    In a three-quarter view the far wheel is naturally higher in the image.
    Treating that wheel-contact slope as camera roll tilts the entire body. A
    robust two-cycle orbit fit models that expected perspective first; only the
    small residual around it is eligible for correction.
    """
    if not images:
        return {}, {}, {
            'vehicleLeveling': True,
            'vehicleCorrectedFrames': 0,
            'maximumVehicleCorrectionDegrees': 0.0,
            'maximumPerspectiveWarp': 0.0,
            'contactDeltaBefore': 0.0,
            'contactDeltaAfter': 0.0,
        }

    indexes = sorted(images)
    measurement_images = {}
    for index in indexes:
        image = images[index].convert('RGBA')
        bbox = image.getbbox()
        measurement_images[index] = image.crop(bbox) if bbox else image
    measurements = [
        estimate_vehicle_roll(measurement_images[index])
        for index in indexes
    ]
    perspective_plan, orbit_amplitude = _fit_orbit_wheel_roll(measurements)
    perspective_available = bool(perspective_plan)
    residual_measurements = []
    reliable_indexes = set()
    for index, measurement in zip(indexes, measurements):
        reliable = (
            perspective_available
            and measurement.get('method') == 'wheels'
            and float(measurement.get('confidence', 0.0)) >= MIN_LINE_CONFIDENCE
        )
        if reliable:
            reliable_indexes.add(index)
            residual_measurements.append({
                **measurement,
                'angle': float(measurement.get('angle', 0.0))
                - float(perspective_plan.get(index, 0.0)),
            })
        else:
            # Front/rear and short/incomplete sequences are deliberately left to
            # the scene-line estimate. Guessing from one wheel or a bumper arc is
            # exactly what produced the former large body tilts.
            residual_measurements.append({
                **measurement,
                'angle': 0.0,
                'confidence': 0.0,
            })

    smoothed = smooth_roll_measurements(
        residual_measurements,
        radius=2,
        max_correction=MAX_VEHICLE_ROLL_CORRECTION,
    )
    # Wheel geometry is excellent for grounding, but frame-local wheel slopes
    # still contain perspective. Scene lines already carry per-frame camera
    # roll, so the vehicle layer may only contribute one robust sequence-wide
    # residual. This prevents the car body from rocking as the viewer rotates.
    global_vehicle_correction = (
        float(np.median([
            float(item['correction'])
            for index, item in zip(indexes, smoothed)
            if index in reliable_indexes
        ]))
        if reliable_indexes else 0.0
    )
    if abs(global_vehicle_correction) < 0.04:
        global_vehicle_correction = 0.0
    corrections = {
        index: global_vehicle_correction if perspective_available else 0.0
        for index in indexes
    }

    # A wheel-plane slope is useful for eye-level rectification, but applying it
    # as rotation tilts doors, pillars and the roof. Scale each image column
    # around a roof-height horizon instead: the ground plane moves strongly,
    # while the roofline and upright pillars stay visually stable.
    raw_warps = []
    for index, measurement in zip(indexes, measurements):
        if not perspective_available:
            raw_warps.append(0.0)
            continue
        if index not in reliable_indexes:
            # Missing views are filled circularly from their nearest measured
            # neighbours. The old sinusoid-only fallback could pick the wrong
            # sign on non-uniform handheld orbits and increase wheel lift.
            raw_warps.append(None)
            continue

        source_angle = float(measurement.get('angle', 0.0)) - corrections[index]
        target_angle = float(np.clip(
            source_angle,
            -TARGET_CONTACT_ANGLE_DEGREES,
            TARGET_CONTACT_ANGLE_DEGREES,
        ))
        image_width, image_height = measurement_images[index].size
        contacts = measurement.get('wheelContacts') or []
        if index in reliable_indexes and len(contacts) == 2:
            left, right = sorted(contacts, key=lambda point: point[0])
            dx = float(right[0] - left[0])
            observed_dy = math.tan(math.radians(source_angle)) * dx
            target_dy = math.tan(math.radians(target_angle)) * dx
            anchor_y = image_height * 0.28
            center_x = image_width / 2.0
            denominator = (
                (float(right[1]) - anchor_y)
                * ((float(right[0]) - center_x) / max(image_width, 1))
                - (float(left[1]) - anchor_y)
                * ((float(left[0]) - center_x) / max(image_width, 1))
            )
            warp = (
                (target_dy - observed_dy) / denominator
                if abs(denominator) > image_height * 0.015 else 0.0
            )
        else:
            # With overlapping wheels, turn the orbit baseline into a modest
            # normalized column-scale estimate. Direct two-wheel frames above
            # remain the precise anchors for strong 3/4 views.
            slope_delta = (
                math.tan(math.radians(source_angle))
                - math.tan(math.radians(target_angle))
            )
            aspect_ratio = image_width / max(image_height, 1)
            warp = -slope_delta * aspect_ratio / 0.58
        raw_warps.append(float(np.clip(warp, -MAX_PERSPECTIVE_WARP, MAX_PERSPECTIVE_WARP)))

    raw_warps = _circular_fill_missing(raw_warps)
    smoothed_warps = _smooth_perspective_warps(raw_warps)
    smoothed_warps = np.clip(
        smoothed_warps,
        -MAX_PERSPECTIVE_WARP,
        MAX_PERSPECTIVE_WARP,
    )
    perspective_warps = {
        index: float(value) if perspective_available else 0.0
        for index, value in zip(indexes, smoothed_warps)
    }
    residual_before = [
        abs(float(item.get('angle', 0.0)))
        for index, item in zip(indexes, residual_measurements)
        if index in reliable_indexes
    ]
    residual_after = [
        abs(float(item.get('angle', 0.0)) - corrections[index])
        for index, item in zip(indexes, residual_measurements)
        if index in reliable_indexes
    ]
    contact_deltas_before = []
    contact_deltas_after = []
    for index, measurement in zip(indexes, measurements):
        contacts = measurement.get('wheelContacts') or []
        if len(contacts) == 2:
            left, right = sorted(contacts, key=lambda point: point[0])
            contact_deltas_before.append(abs(float(right[1]) - float(left[1])))
            transformed = _transform_contact_pair(
                left,
                right,
                measurement_images[index].size,
                corrections[index],
                perspective_warps[index],
            )
            contact_deltas_after.append(abs(transformed[1][1] - transformed[0][1]))
        elif abs(float(measurement.get('contactDelta', 0.0))) > 0.0:
            contact_deltas_before.append(abs(float(measurement['contactDelta'])))
    initially_unmeasurable = set(indexes) - reliable_indexes
    report = {
        'vehicleLeveling': True,
        'vehicleCorrectedFrames': sum(
            abs(corrections[index]) >= 0.04 or abs(perspective_warps[index]) >= 0.01
            for index in indexes
        ),
        'rotationCorrectedFrames': sum(abs(value) >= 0.04 for value in corrections.values()),
        'perspectiveCorrectedFrames': sum(
            abs(value) >= 0.01 for value in perspective_warps.values()
        ),
        'maximumVehicleCorrectionDegrees': round(
            max((abs(value) for value in corrections.values()), default=0.0), 3
        ),
        'vehicleLimitedFrames': int(
            abs(global_vehicle_correction) >= MAX_VEHICLE_ROLL_CORRECTION - 1e-6
        ) * len(indexes),
        'sequenceWideVehicleCorrectionDegrees': round(global_vehicle_correction, 3),
        'directResidualFrames': len(reliable_indexes),
        'unmeasurableVehicleFrames': len(initially_unmeasurable),
        'wheelMeasuredFrames': len(reliable_indexes),
        'wheelInterpolatedFrames': len(initially_unmeasurable) if perspective_available else 0,
        'directMeasurementIndexes': sorted(reliable_indexes),
        'orbitPerspectiveAmplitudeDegrees': round(orbit_amplitude, 3),
        'perspectiveBaselineUsed': perspective_available,
        'perspectiveGroundPlaneRectified': perspective_available,
        'perspectiveTargetAngleDegrees': TARGET_CONTACT_ANGLE_DEGREES,
        'maximumPerspectiveWarp': round(
            max((abs(value) for value in perspective_warps.values()), default=0.0), 4
        ),
        'vehicleLevelingPasses': 1,
        'contactDeltaBefore': round(
            float(np.median(contact_deltas_before)) if contact_deltas_before else 0.0,
            2,
        ),
        'contactDeltaAfter': round(
            float(np.median(contact_deltas_after)) if contact_deltas_after else 0.0,
            2,
        ),
        'medianResidualAngleDegrees': round(
            float(np.median(residual_after)) if residual_after else 0.0, 3
        ),
        'maximumResidualAngleDegrees': round(
            max(residual_after, default=0.0), 3
        ),
        'medianPerspectiveResidualBeforeDegrees': round(
            float(np.median(residual_before)) if residual_before else 0.0, 3
        ),
    }
    return corrections, perspective_warps, report


def build_vehicle_roll_plan(images):
    """Compatibility wrapper returning only the rotational part of alignment."""
    corrections, _, report = build_vehicle_alignment_plan(images)
    return corrections, report


def stabilize_vehicle_sequence(images):
    """Apply roll and perspective-aware eye-level alignment to a sequence."""
    corrections, perspective_warps, report = build_vehicle_alignment_plan(images)
    return apply_sequence_alignment_plan(images, corrections, perspective_warps), report


def _transform_contact_pair(left, right, image_size, correction, perspective_warp):
    """Project two measured contacts through the planned combined transform."""
    width, height = image_size
    center_x = (width - 1) / 2.0
    center_y = (height - 1) / 2.0
    rotation = np.vstack((
        cv2.getRotationMatrix2D((center_x, center_y), float(correction), 1.0),
        (0.0, 0.0, 1.0),
    ))
    points = np.asarray((
        (float(left[0]), float(left[1]), 1.0),
        (float(right[0]), float(right[1]), 1.0),
    )).T
    rotated = rotation @ points
    anchor_y = height * 0.28
    scale = 1.0 + float(perspective_warp) * (
        rotated[0] - center_x
    ) / max(width, 1)
    projected_y = anchor_y + (rotated[1] - anchor_y) * scale
    return (
        (float(rotated[0, 0]), float(projected_y[0])),
        (float(rotated[0, 1]), float(projected_y[1])),
    )


def _circular_fill_missing(values):
    """Linearly fill missing values around a closed 360-degree sequence."""
    array = np.asarray([
        np.nan if value is None else float(value)
        for value in values
    ], dtype=np.float64)
    count = array.size
    if count == 0:
        return array
    valid = np.flatnonzero(np.isfinite(array))
    if valid.size == 0:
        return np.zeros(count, dtype=np.float64)
    if valid.size == 1:
        return np.full(count, float(array[valid[0]]), dtype=np.float64)

    result = array.copy()
    for index in np.flatnonzero(~np.isfinite(result)):
        previous_distances = (index - valid) % count
        next_distances = (valid - index) % count
        previous_position = int(valid[np.argmin(np.where(previous_distances > 0, previous_distances, count + 1))])
        next_position = int(valid[np.argmin(np.where(next_distances > 0, next_distances, count + 1))])
        previous_distance = (index - previous_position) % count
        next_distance = (next_position - index) % count
        span = previous_distance + next_distance
        if span <= 0:
            result[index] = result[previous_position]
        else:
            fraction = previous_distance / span
            result[index] = (
                result[previous_position] * (1.0 - fraction)
                + result[next_position] * fraction
            )
    return result


def _smooth_perspective_warps(values):
    """Reject isolated wheel-pair mistakes, then lightly smooth the orbit."""
    values = np.asarray(values, dtype=np.float64)
    if values.size < 5:
        return values.copy()

    neighbour_one = (np.roll(values, 1) + np.roll(values, -1)) / 2.0
    neighbour_two = (np.roll(values, 2) + np.roll(values, -2)) / 2.0
    # Clamp only truly isolated spikes. A strong but real three-quarter view can
    # change quickly near front/rear, so disagreement between the one- and
    # two-step predictions deliberately widens the allowed envelope.
    predictor_disagreement = np.abs(neighbour_one - neighbour_two)
    allowed = np.where(
        predictor_disagreement < 0.08,
        0.14,
        np.clip(0.10 + predictor_disagreement * 1.35, 0.16, 0.34),
    )
    corrected = np.clip(values, neighbour_one - allowed, neighbour_one + allowed)
    return (
        np.roll(corrected, 1) * 0.10
        + corrected * 0.80
        + np.roll(corrected, -1) * 0.10
    )


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
