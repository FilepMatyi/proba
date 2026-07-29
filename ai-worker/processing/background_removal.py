from rembg import new_session, remove
from PIL import Image
import io
import os
import cv2
import numpy as np

# ─── Configuration ───────────────────────────────────────────────────
MODEL_NAME = os.getenv('REMBG_MODEL', 'u2net')
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
    1. Threshold the alpha channel to find solid foreground.
    2. Largest connected component — keeps ONLY the car, drops isolated
       background fragments (buildings, fences, etc. that rembg missed).
    Note: We removed the morphological OPEN/CLOSE because they eroded fine 
    details like side mirrors and antennas.
    """
    arr = np.array(image_rgba)
    alpha = arr[:, :, 3]

    # Binarise alpha: > 10 → foreground
    _, binary = cv2.threshold(alpha, 10, 255, cv2.THRESH_BINARY)

    # Keep only the largest connected component (= the car)
    num_labels, labels, stats, _ = cv2.connectedComponentsWithStats(
        binary, connectivity=8
    )
    if num_labels > 2:
        # Label 0 = background; find the largest foreground label
        areas = stats[1:, cv2.CC_STAT_AREA]
        largest_label = 1 + int(np.argmax(areas))
        
        # Where it's the largest component, keep original alpha, else 0
        arr[:, :, 3] = np.where(labels == largest_label, alpha, 0)

    # ── Coverage ratio logging ──
    total_px = binary.shape[0] * binary.shape[1]
    fg_px = int(np.count_nonzero(labels == largest_label if num_labels > 2 else binary))
    ratio = fg_px / total_px

    if ratio < COVERAGE_MIN or ratio > COVERAGE_MAX:
        print(
            f"⚠️  WARNING: frame {photo_index} coverage {ratio:.1%} "
            f"outside [{COVERAGE_MIN:.0%}-{COVERAGE_MAX:.0%}] — may need manual review"
        )
    else:
        print(f"   Frame {photo_index} coverage: {ratio:.1%}")

    return Image.fromarray(arr, 'RGBA')


def _darken_windows_and_holes(image_rgba):
    """
    1. Detects completely transparent internal holes (windows, wheel spokes)
       and fills them with dark tint (blueish for windows, dark gray for rims).
    2. Detects semi-transparent pixels (reflections) and tints them.
    """
    arr = np.array(image_rgba, dtype=np.uint8)
    alpha = arr[:, :, 3].copy()
    
    # 1. Fill completely transparent internal holes
    binary = (alpha > 10).astype(np.uint8) * 255
    contours, hierarchy = cv2.findContours(binary, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_SIMPLE)
    
    if hierarchy is not None:
        x, y, w, h = cv2.boundingRect(binary)
        cutoff_y = y + int(h * 0.55) # Upper 55% is window territory
        
        for i in range(len(contours)):
            # If contour has a parent (hierarchy[0][i][3] != -1), it's an internal hole
            if hierarchy[0][i][3] != -1: 
                hole_mask = np.zeros_like(alpha)
                cv2.drawContours(hole_mask, contours, i, 255, -1)
                
                # Exclude pixels that already have high alpha (just in case)
                hole_mask = cv2.bitwise_and(hole_mask, cv2.bitwise_not(binary))
                
                if np.count_nonzero(hole_mask) == 0:
                    continue
                
                # Find vertical center of the hole
                M = cv2.moments(contours[i])
                if M["m00"] != 0:
                    cy = int(M["m01"] / M["m00"])
                else:
                    cy = cutoff_y
                    
                is_window = cy < cutoff_y
                
                fill_r = GLASS_R if is_window else 15
                fill_g = GLASS_G if is_window else 15
                fill_b = GLASS_B if is_window else 15
                
                # Apply fill where the hole mask is active
                active = hole_mask == 255
                arr[:, :, 0][active] = fill_r
                arr[:, :, 1][active] = fill_g
                arr[:, :, 2][active] = fill_b
                arr[:, :, 3][active] = 245

    # 2. Tint semi-transparent pixels (original logic)
    window_mask = (alpha >= 30) & (alpha <= 175)

    if window_mask.any():
        blend = (175 - alpha[window_mask].astype(np.float32)) / 145.0
        blend = np.clip(blend, 0.0, 1.0)

        arr[:, :, 0][window_mask] = (
            arr[:, :, 0][window_mask] * (1 - blend) + GLASS_R * blend
        ).astype(np.uint8)
        arr[:, :, 1][window_mask] = (
            arr[:, :, 1][window_mask] * (1 - blend) + GLASS_G * blend
        ).astype(np.uint8)
        arr[:, :, 2][window_mask] = (
            arr[:, :, 2][window_mask] * (1 - blend) + GLASS_B * blend
        ).astype(np.uint8)

        arr[:, :, 3][window_mask] = np.clip(
            alpha[window_mask].astype(np.int16) + 120, 0, 245
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
                alpha_matting_foreground_threshold=240,
                alpha_matting_background_threshold=10,
                alpha_matting_erode_size=3,
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

    # ── 3. Window / glass tinting (Heuristics) ──
    image = _darken_windows_and_holes(image)
    
    # ── 4. AI-driven Glass Masking (FastSAM) ──
    try:
        from glass_masking import apply_glass_masking
        image = apply_glass_masking(image)
    except Exception as e:
        print(f"FastSAM glass masking failed: {e}")

    return image
