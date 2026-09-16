import cv2
import numpy as np
from PIL import Image


def _foreground_stats(l_channel, alpha):
    solid_foreground = alpha >= 128
    values = l_channel[solid_foreground]
    if values.size < 100:
        values = l_channel[alpha > 10]
    if values.size == 0:
        return None
    return float(values.mean()), float(values.std())


def measure_exposure(image):
    """Return foreground-only LAB luminance statistics for one RGBA image."""
    rgba = np.asarray(image.convert('RGBA'))
    alpha = rgba[:, :, 3]
    lab = cv2.cvtColor(rgba[:, :, :3], cv2.COLOR_RGB2LAB)
    return _foreground_stats(lab[:, :, 0], alpha)


def build_exposure_plan(images_dict):
    """Build small per-frame parameters so full-resolution images need not be cached."""
    stats_by_index = {
        index: measure_exposure(image)
        for index, image in images_dict.items()
    }
    valid = [stats for stats in stats_by_index.values() if stats]
    if not valid:
        return {index: None for index in images_dict}

    target_mean = float(np.median([stats[0] for stats in valid]))
    target_deviation = max(float(np.median([stats[1] for stats in valid])), 1.0)
    plan = {}
    for index, stats in stats_by_index.items():
        if not stats:
            plan[index] = None
            continue
        current_mean, current_deviation = stats
        plan[index] = {
            'sourceMean': current_mean,
            'meanShift': float(np.clip(target_mean - current_mean, -18.0, 18.0)),
            'contrastGain': (
                float(np.clip(target_deviation / current_deviation, 0.82, 1.22))
                if current_deviation > 1.0 else 1.0
            ),
        }
    return plan


def apply_exposure_plan(image, plan):
    """Apply a previously measured exposure plan to one image."""
    if not plan:
        return image.convert('RGBA').copy()

    rgba = np.asarray(image.convert('RGBA'))
    alpha = rgba[:, :, 3]
    lab = cv2.cvtColor(rgba[:, :, :3], cv2.COLOR_RGB2LAB).astype(np.float32)
    luminance = lab[:, :, 0]
    visible = alpha > 5
    adjusted = (
        (luminance - plan['sourceMean']) * plan['contrastGain']
        + plan['sourceMean']
        + plan['meanShift']
    )
    luminance[visible] = np.clip(adjusted[visible], 0, 255)
    normalized_rgb = cv2.cvtColor(lab.astype(np.uint8), cv2.COLOR_LAB2RGB)
    return Image.fromarray(np.dstack((normalized_rgb, alpha.astype(np.uint8))), 'RGBA')


def normalize_exposure(images_dict):
    """Normalize visible vehicle pixels without sampling the transparent background."""
    if len(images_dict) < 2:
        return images_dict

    plan = build_exposure_plan(images_dict)
    return {
        index: apply_exposure_plan(image, plan.get(index))
        for index, image in images_dict.items()
    }
