import math

import cv2
import numpy as np


MASK_THRESHOLD = 10
DEFAULT_TARGET_CENTER = (0.5, 0.58)


def target_crop_box(width, height, top_ratio=0.16, bottom_ratio=0.96):
    """Return the capture-guide ROI used by the target-isolation retry."""
    if width <= 0 or height <= 0:
        raise ValueError('Image dimensions must be positive')

    top = max(0.0, min(float(top_ratio), 0.8))
    bottom = max(top + 0.1, min(float(bottom_ratio), 1.0))
    return 0, int(round(height * top)), width, int(round(height * bottom))


def mask_profile(alpha, threshold=MASK_THRESHOLD):
    """Describe a mask without assuming that its largest region is the target."""
    alpha_arr = np.asarray(alpha, dtype=np.uint8)
    if alpha_arr.ndim != 2:
        raise ValueError('Alpha mask must be a two-dimensional array')

    height, width = alpha_arr.shape
    binary = alpha_arr > threshold
    ys, xs = np.where(binary)
    if not len(xs):
        return {
            'empty': True,
            'coverage': 0.0,
            'bbox': None,
            'bboxWidthRatio': 0.0,
            'bboxHeightRatio': 0.0,
            'touchesLeft': False,
            'touchesTop': False,
            'touchesRight': False,
            'touchesBottom': False,
            'edgeCount': 0,
            'centerDistance': 1.0,
        }

    x0, y0 = int(xs.min()), int(ys.min())
    x1, y1 = int(xs.max()) + 1, int(ys.max()) + 1
    touches_left = x0 <= 2
    touches_top = y0 <= 2
    touches_right = x1 >= width - 2
    touches_bottom = y1 >= height - 2
    center_x = ((x0 + x1) / 2) / max(width, 1)
    center_y = ((y0 + y1) / 2) / max(height, 1)
    center_distance = math.hypot(
        center_x - DEFAULT_TARGET_CENTER[0],
        center_y - DEFAULT_TARGET_CENTER[1],
    )

    return {
        'empty': False,
        'coverage': float(binary.mean()),
        'bbox': (x0, y0, x1, y1),
        'bboxWidthRatio': (x1 - x0) / max(width, 1),
        'bboxHeightRatio': (y1 - y0) / max(height, 1),
        'touchesLeft': touches_left,
        'touchesTop': touches_top,
        'touchesRight': touches_right,
        'touchesBottom': touches_bottom,
        'edgeCount': sum((touches_left, touches_top, touches_right, touches_bottom)),
        'centerDistance': center_distance,
    }


def mask_needs_refinement(profile):
    """Flag masks that are more likely to contain scenery than one vehicle."""
    if profile['empty']:
        return True
    if profile['coverage'] > 0.62:
        return True
    if profile['bboxHeightRatio'] > 0.9:
        return True
    if profile['touchesTop'] and profile['touchesBottom']:
        return True
    return profile['edgeCount'] >= 3


def _profile_score(profile):
    if profile['empty']:
        return -100.0

    coverage = profile['coverage']
    coverage_score = 2.0 if 0.06 <= coverage <= 0.58 else -4.0
    height_score = 1.0 if 0.16 <= profile['bboxHeightRatio'] <= 0.88 else -2.0
    center_score = 3.0 * max(0.0, 1.0 - profile['centerDistance'] / 0.75)
    edge_penalty = profile['edgeCount'] * 0.9
    vertical_span_penalty = 2.5 if profile['touchesTop'] and profile['touchesBottom'] else 0.0
    return coverage_score + height_score + center_score - edge_penalty - vertical_span_penalty


def should_use_refined_mask(base_profile, refined_profile, crop_boundary_touched=False):
    """Accept a retry only when it is safer than the original segmentation."""
    if refined_profile['empty'] or crop_boundary_touched:
        return False
    return _profile_score(refined_profile) >= _profile_score(base_profile) + 0.75


def select_primary_component(alpha, target_center=DEFAULT_TARGET_CENTER):
    """Keep the foreground component most likely to be the framed vehicle.

    Area still matters, but a slightly smaller component inside the capture guide
    beats a larger car or building at the edge of the frame.
    """
    alpha_arr = np.asarray(alpha, dtype=np.uint8)
    binary = (alpha_arr > MASK_THRESHOLD).astype(np.uint8)
    label_count, labels, stats, centroids = cv2.connectedComponentsWithStats(
        binary, connectivity=8
    )
    component_count = max(0, label_count - 1)
    if component_count <= 1:
        return alpha_arr.copy(), {
            'componentCount': component_count,
            'selectedLabel': 1 if component_count else 0,
        }

    height, width = binary.shape
    target_x = int(round(max(0.0, min(1.0, target_center[0])) * (width - 1)))
    target_y = int(round(max(0.0, min(1.0, target_center[1])) * (height - 1)))
    target_label = int(labels[target_y, target_x])
    max_area = max(int(stats[label, cv2.CC_STAT_AREA]) for label in range(1, label_count))

    best_label = 1
    best_score = float('-inf')
    for label in range(1, label_count):
        area = int(stats[label, cv2.CC_STAT_AREA])
        area_score = math.sqrt(area / max(max_area, 1)) * 2.0
        cx = float(centroids[label, 0]) / max(width, 1)
        cy = float(centroids[label, 1]) / max(height, 1)
        distance = math.hypot(cx - target_center[0], cy - target_center[1])
        proximity_score = max(0.0, 1.0 - distance / 0.75) * 3.0

        x = int(stats[label, cv2.CC_STAT_LEFT])
        y = int(stats[label, cv2.CC_STAT_TOP])
        component_width = int(stats[label, cv2.CC_STAT_WIDTH])
        component_height = int(stats[label, cv2.CC_STAT_HEIGHT])
        contains_target_box = (
            x <= target_x < x + component_width
            and y <= target_y < y + component_height
        )
        touches = sum((
            x <= 2,
            y <= 2,
            x + component_width >= width - 2,
            y + component_height >= height - 2,
        ))
        score = (
            area_score
            + proximity_score
            + (4.0 if label == target_label else 0.0)
            + (0.75 if contains_target_box else 0.0)
            - touches * 0.45
        )
        if score > best_score:
            best_score = score
            best_label = label

    selected = np.where(labels == best_label, alpha_arr, 0).astype(np.uint8)
    return selected, {
        'componentCount': component_count,
        'selectedLabel': best_label,
    }
