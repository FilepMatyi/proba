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


def normalize_exposure(images_dict):
    """Normalize visible vehicle pixels without sampling the transparent background."""
    if len(images_dict) < 2:
        return images_dict

    cache = {}
    means = []
    deviations = []
    for index, image in images_dict.items():
        rgba = np.asarray(image.convert('RGBA'))
        alpha = rgba[:, :, 3]
        lab = cv2.cvtColor(rgba[:, :, :3], cv2.COLOR_RGB2LAB).astype(np.float32)
        stats = _foreground_stats(lab[:, :, 0], alpha)
        cache[index] = (image, lab, alpha, stats)
        if stats:
            means.append(stats[0])
            deviations.append(stats[1])

    if not means:
        return images_dict

    target_mean = float(np.median(means))
    target_deviation = max(float(np.median(deviations)), 1.0)
    result = {}

    for index, (image, lab, alpha, stats) in cache.items():
        if not stats:
            result[index] = image
            continue

        current_mean, current_deviation = stats
        visible = alpha > 5
        luminance = lab[:, :, 0]
        mean_shift = float(np.clip(target_mean - current_mean, -18.0, 18.0))
        if current_deviation > 1.0:
            contrast_gain = float(np.clip(target_deviation / current_deviation, 0.82, 1.22))
            adjusted = (luminance - current_mean) * contrast_gain + current_mean + mean_shift
        else:
            adjusted = luminance + mean_shift
        luminance[visible] = np.clip(adjusted[visible], 0, 255)

        normalized_rgb = cv2.cvtColor(lab.astype(np.uint8), cv2.COLOR_LAB2RGB)
        normalized_rgba = np.dstack((normalized_rgb, alpha.astype(np.uint8)))
        result[index] = Image.fromarray(normalized_rgba, 'RGBA')

    return result
