from rembg import new_session, remove
from PIL import Image
import io
import os
import cv2
import numpy as np

# ─── Configuration ───────────────────────────────────────────────────
MODEL_NAME = os.getenv('REMBG_MODEL', 'isnet-general-use')
_session = new_session(MODEL_NAME)
ENABLE_ALPHA_MATTING = os.getenv('ENABLE_ALPHA_MATTING', 'false').lower() == 'true'

# Coverage thresholds — outside this range flags a frame for manual review
COVERAGE_MIN = 0.10   # 10%
COVERAGE_MAX = 0.55   # 55%

# Window tinting color (deep charcoal with blue tint = realistic tinted glass)
GLASS_R, GLASS_G, GLASS_B = 22, 28, 35


def _cleanup_mask(image_rgba, photo_index=0):
    """
    Post-process the alpha mask using OpenCV to remove background remnants.

    Steps:
    1. Morphological CLOSE — fills small holes inside the car silhouette
    2. Morphological OPEN  — removes small noise blobs around the edges
    3. Largest connected component — keeps ONLY the car, drops isolated
       background fragments (buildings, fences, etc. that rembg missed)
    4. Logs coverage ratio and warns if outside expected range

    Args:
        image_rgba: PIL RGBA Image with rembg output
        photo_index: frame number for logging

    Returns:
        PIL RGBA Image with cleaned mask
    """
    arr = np.array(image_rgba)
    alpha = arr[:, :, 3]

    # Binarise alpha: > 50 → foreground
    _, binary = cv2.threshold(alpha, 50, 255, cv2.THRESH_BINARY)

    # Morphological cleanup
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7))
    binary = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, kernel, iterations=3)
    binary = cv2.morphologyEx(binary, cv2.MORPH_OPEN, kernel, iterations=2)

    # Keep only the largest connected component (= the car)
    num_labels, labels, stats, _ = cv2.connectedComponentsWithStats(
        binary, connectivity=8
    )
    if num_labels > 2:
        # Label 0 = background; find the largest foreground label
        areas = stats[1:, cv2.CC_STAT_AREA]
        largest_label = 1 + int(np.argmax(areas))
        binary = np.where(labels == largest_label, 255, 0).astype(np.uint8)

    # Apply the cleaned binary mask back:
    # - Where binary says "car": keep the original alpha
    # - Where binary says "not car": force alpha → 0
    arr[:, :, 3] = np.where(binary > 0, alpha, 0)

    # ── Coverage ratio logging ──
    total_px = binary.shape[0] * binary.shape[1]
    fg_px = int(np.count_nonzero(binary))
    ratio = fg_px / total_px

    if ratio < COVERAGE_MIN or ratio > COVERAGE_MAX:
        print(
            f"⚠️  WARNING: frame {photo_index} coverage {ratio:.1%} "
            f"outside [{COVERAGE_MIN:.0%}-{COVERAGE_MAX:.0%}] — may need manual review"
        )
    else:
        print(f"   Frame {photo_index} coverage: {ratio:.1%}")

    return Image.fromarray(arr, 'RGBA')


def _darken_windows(image_rgba):
    """
    Detect semi-transparent pixels (windows / glass) and tint them
    dark charcoal-blue so they look like real tinted car glass instead
    of transparent holes.

    Semi-transparent = alpha in [30, 175]. Fully opaque (> 175) is car
    body; fully transparent (< 30) is removed background.
    """
    arr = np.array(image_rgba, dtype=np.uint8)
    r, g, b, a = arr[:, :, 0], arr[:, :, 1], arr[:, :, 2], arr[:, :, 3]

    window_mask = (a >= 30) & (a <= 175)

    if window_mask.any():
        blend = (175 - a[window_mask].astype(np.float32)) / 145.0
        blend = np.clip(blend, 0.0, 1.0)

        arr[:, :, 0][window_mask] = (
            r[window_mask] * (1 - blend) + GLASS_R * blend
        ).astype(np.uint8)
        arr[:, :, 1][window_mask] = (
            g[window_mask] * (1 - blend) + GLASS_G * blend
        ).astype(np.uint8)
        arr[:, :, 2][window_mask] = (
            b[window_mask] * (1 - blend) + GLASS_B * blend
        ).astype(np.uint8)

        arr[:, :, 3][window_mask] = np.clip(
            a[window_mask].astype(np.int16) + 120, 0, 245
        ).astype(np.uint8)

    return Image.fromarray(arr, 'RGBA')


def remove_background(image_bytes, photo_index=0):
    """
    Full background removal pipeline:
      1. rembg neural net segmentation
      2. OpenCV morphological mask cleanup + largest-component filtering
      3. Window/glass darkening

    Args:
        image_bytes: Raw JPEG bytes
        photo_index: Frame number (for logging)

    Returns:
        PIL RGBA Image with clean mask and darkened windows
    """
    # ── 1. Neural net background removal ──
    if ENABLE_ALPHA_MATTING:
        try:
            output_bytes = remove(
                image_bytes,
                session=_session,
                alpha_matting=True,
                alpha_matting_foreground_threshold=230,
                alpha_matting_background_threshold=20,
                alpha_matting_erode_size=8,
                post_process_mask=True,
            )
        except Exception as e:
            print(f"Alpha matting failed, falling back: {e}")
            output_bytes = remove(
                image_bytes, session=_session, post_process_mask=True
            )
    else:
        output_bytes = remove(
            image_bytes, session=_session, post_process_mask=True
        )

    image = Image.open(io.BytesIO(output_bytes)).convert('RGBA')

    # ── 2. Morphological mask cleanup ──
    image = _cleanup_mask(image, photo_index)

    # ── 3. Window / glass tinting ──
    image = _darken_windows(image)

    return image
