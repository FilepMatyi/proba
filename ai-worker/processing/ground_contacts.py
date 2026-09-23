"""Perspective-tolerant tire footprints from the lower cutout silhouette.

Unlike circle detection, these anchors also work for narrow, foreshortened
wheels and for two visible wheels in the same half of a three-quarter view.
Silhouette anchors alone are not evidence of camera roll.
"""
import cv2
import numpy as np


def silhouette_contacts(alpha, limit=2):
    height, width = alpha.shape
    if width < 80 or height < 60:
        return []
    mask = cv2.morphologyEx(
        (alpha >= 160).astype(np.uint8), cv2.MORPH_OPEN,
        cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3)),
    )
    present = mask.any(axis=0)
    bottom = height - 1 - np.argmax(mask[::-1], axis=0)
    bottom = np.where(present, bottom, 0).astype(np.float32)
    smooth_width = max(3, int(width * .009) | 1)
    smooth = np.median(np.lib.stride_tricks.sliding_window_view(
        np.pad(bottom, smooth_width // 2, mode='edge'), smooth_width,
    ), axis=1)
    local_width = max(9, int(width * .065) | 1)
    maxima = cv2.dilate(smooth.reshape(1, -1), np.ones((1, local_width), np.uint8)).reshape(-1)
    peaks = (smooth >= maxima - .5) & (smooth > height * .50) & present
    transitions = np.diff(np.r_[0, peaks.astype(np.int8), 0])
    contacts = []
    reach = max(12, int(width * .14))
    for start, end in zip(np.where(transitions == 1)[0], np.where(transitions == -1)[0]):
        x = int(round((start + end - 1) / 2))
        y = float(smooth[x])
        left = smooth[max(0, x-reach):x]
        right = smooth[x+1:min(width, x+reach+1)]
        if not left.size or not right.size:
            continue
        prominence = y - max(float(left.min()), float(right.min()))
        if prominence < max(3, height * .005):
            continue
        threshold = y - min(prominence * .65, height * .065)
        a, b = x, x
        while a > 0 and smooth[a-1] >= threshold:
            a -= 1
        while b < width-1 and smooth[b+1] >= threshold:
            b += 1
        footprint_width = b-a+1
        if not width * .03 <= footprint_width <= width * .26:
            continue
        # Thin hooks/segmentation tails have insufficient solid tire material.
        band = mask[max(0, int(y-height*.14)):int(y)+1, a:b+1]
        if not band.size or float(band.mean()) < .80:
            continue
        contacts.append({
            'x': float(x), 'y': y,
            'radius': float(np.clip(footprint_width * .85, height*.045, height*.26)),
            'confidence': .18, 'prominence': prominence,
        })
    # Adjacent maxima on the same tread are one footprint, not two wheels.
    selected = []
    for item in sorted(contacts, key=lambda item: item['prominence'], reverse=True):
        if all(abs(item['x']-other['x']) >= width*.15 for other in selected):
            selected.append(item)
    return sorted(selected[:limit], key=lambda item: item['x'])




def tire_contacts(image):
    """Validate silhouette lobes against dark tire material and local detail."""
    rgba = np.asarray(image.convert('RGBA'))
    original_h, original_w = rgba.shape[:2]
    scale = min(1., 960 / max(original_h, original_w))
    if scale < 1:
        rgba = cv2.resize(rgba, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    rgb, alpha = rgba[:, :, :3], rgba[:, :, 3]
    hsv = cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV)
    edges = cv2.Canny(cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY), 45, 130)
    result = []
    for item in silhouette_contacts(alpha, limit=5):
        x, y, radius = item['x'], item['y'], item['radius']
        a, b = max(0, int(x-radius*.55)), min(alpha.shape[1], int(x+radius*.55)+1)
        top, bottom = max(0, int(y-radius*1.65)), int(y-radius*.15)+1
        valid = alpha[top:bottom, a:b] >= 160
        if valid.sum() < 50:
            continue
        pixels = hsv[top:bottom, a:b][valid]
        neutral = float(np.mean((pixels[:, 1] < 105) & (pixels[:, 2] < 190)))
        detail = float(np.mean(edges[top:bottom, a:b][valid] > 0))
        upper = hsv[max(0, int(y-alpha.shape[0]*.20)):max(0, int(y-alpha.shape[0]*.12)), a:b]
        upper_alpha = alpha[max(0, int(y-alpha.shape[0]*.20)):max(0, int(y-alpha.shape[0]*.12)), a:b]
        upper_neutral = float(np.mean((upper[:, :, 1] < 105) & (upper[:, :, 2] < 190) & (upper_alpha >= 160))) if upper.size else 0.
        if neutral < .40 or detail < .045 or upper_neutral < .45:
            continue
        result.append({**item, 'x': x/scale, 'y': y/scale, 'radius': radius/scale,
                       'confidence': min(.8, .35+detail), 'neutralDark': neutral,
                       'edgeDensity': detail, 'upperNeutral': upper_neutral})
    return sorted(sorted(result, key=lambda item: item['confidence'], reverse=True)[:2], key=lambda item: item['x'])
