from rembg import new_session, remove
from rembg.sessions import sessions_class
from PIL import Image
import io
import os
import cv2
import numpy as np
import onnxruntime as ort

from processing.target_lock import (
    DEFAULT_TARGET_CENTER,
    mask_needs_refinement,
    mask_profile,
    select_primary_component,
    should_use_refined_mask,
    target_crop_box,
)

# ─── Configuration ───────────────────────────────────────────────────
MODEL_NAME = os.getenv('REMBG_MODEL', 'birefnet-general-lite')
ENABLE_ALPHA_MATTING = os.getenv('ENABLE_ALPHA_MATTING', 'false').lower() == 'true'
ENABLE_GLASS_REPAIR = os.getenv('ENABLE_GLASS_REPAIR', 'false').lower() == 'true'
ENABLE_GLASS_MASKING = os.getenv('ENABLE_GLASS_MASKING', 'false').lower() == 'true'
ENABLE_TARGET_LOCK = os.getenv('ENABLE_TARGET_LOCK', 'true').lower() == 'true'
TARGET_LOCK_CROP_TOP = float(os.getenv('TARGET_LOCK_CROP_TOP', '0.16'))
TARGET_LOCK_CROP_BOTTOM = float(os.getenv('TARGET_LOCK_CROP_BOTTOM', '0.96'))
DISABLE_CPU_MEMORY_ARENA = os.getenv('ONNX_DISABLE_CPU_ARENA', 'true').lower() == 'true'


def _create_model_session():
    """Create a bounded-memory ONNX session for Docker Desktop deployments."""
    if not DISABLE_CPU_MEMORY_ARENA:
        return new_session(MODEL_NAME)

    session_options = ort.SessionOptions()
    session_options.enable_cpu_mem_arena = False
    session_options.enable_mem_pattern = False
    thread_count = max(1, int(os.getenv('OMP_NUM_THREADS', '4')))
    session_options.inter_op_num_threads = thread_count
    session_options.intra_op_num_threads = thread_count
    session_class = next(
        (candidate for candidate in sessions_class if candidate.name() == MODEL_NAME),
        None,
    )
    if session_class is None:
        raise ValueError(f'Unsupported rembg model: {MODEL_NAME}')
    return session_class(MODEL_NAME, session_options)


_session = _create_model_session()

# Coverage thresholds — outside this range flags a frame for manual review
COVERAGE_MIN = 0.10   # 10%
COVERAGE_MAX = 0.55   # 55%

# Window tinting color (deep charcoal with blue tint = realistic tinted glass)
GLASS_R, GLASS_G, GLASS_B = 22, 28, 35


def _cleanup_mask(image_rgba, photo_index=0, target_center=DEFAULT_TARGET_CENTER, log_quality=True):
    """
    Post-process the alpha mask using OpenCV to remove background remnants.

    Steps:
    1. Threshold the alpha channel to find solid foreground.
    2. Target-aware connected component selection keeps the framed vehicle,
       even when another car or background object is slightly larger.
    Note: We removed the morphological OPEN/CLOSE because they eroded fine 
    details like side mirrors and antennas.
    """
    arr = np.array(image_rgba)
    alpha = arr[:, :, 3]

    # Binarise alpha: > 10 → foreground
    _, binary = cv2.threshold(alpha, 10, 255, cv2.THRESH_BINARY)

    selected_alpha, component_details = select_primary_component(
        alpha, target_center=target_center
    )
    arr[:, :, 3] = selected_alpha

    # ── Coverage ratio logging ──
    total_px = binary.shape[0] * binary.shape[1]
    fg_px = int(np.count_nonzero(selected_alpha > 10))
    ratio = fg_px / total_px

    if log_quality and (ratio < COVERAGE_MIN or ratio > COVERAGE_MAX):
        print(
            f"⚠️  WARNING: frame {photo_index} coverage {ratio:.1%} "
            f"outside [{COVERAGE_MIN:.0%}-{COVERAGE_MAX:.0%}] — may need manual review"
        )
    elif log_quality:
        print(f"   Frame {photo_index} coverage: {ratio:.1%}")

    return Image.fromarray(arr, 'RGBA'), component_details


def _run_model(image_bytes):
    if ENABLE_ALPHA_MATTING:
        try:
            return remove(
                image_bytes,
                session=_session,
                alpha_matting=True,
                alpha_matting_foreground_threshold=240,
                alpha_matting_background_threshold=10,
                alpha_matting_erode_size=3,
                post_process_mask=True,
            )
        except Exception as error:
            print(f"Alpha matting failed, falling back: {error}")
    return remove(image_bytes, session=_session, post_process_mask=True)


def _target_locked_retry(source, base_image, photo_index, target_center):
    base_profile = mask_profile(np.array(base_image.getchannel('A')))
    if not ENABLE_TARGET_LOCK or not mask_needs_refinement(base_profile):
        return base_image, False, base_profile

    width, height = source.size
    crop_box = target_crop_box(
        width,
        height,
        top_ratio=TARGET_LOCK_CROP_TOP,
        bottom_ratio=TARGET_LOCK_CROP_BOTTOM,
    )
    crop = source.crop(crop_box)
    crop_buffer = io.BytesIO()
    crop.save(crop_buffer, format='JPEG', quality=95, subsampling=0)

    crop_bytes = _run_model(crop_buffer.getvalue())
    crop_image = Image.open(io.BytesIO(crop_bytes)).convert('RGBA')
    crop_height = max(crop_box[3] - crop_box[1], 1)
    crop_target_center = (
        target_center[0],
        (target_center[1] * height - crop_box[1]) / crop_height,
    )
    crop_image, _ = _cleanup_mask(
        crop_image,
        photo_index=photo_index,
        target_center=crop_target_center,
        log_quality=False,
    )
    local_profile = mask_profile(np.array(crop_image.getchannel('A')))
    crop_boundary_touched = bool(
        local_profile['touchesTop'] or local_profile['touchesBottom']
    )

    refined = Image.new('RGBA', source.size, (0, 0, 0, 0))
    refined.paste(crop_image, crop_box[:2])
    refined_profile = mask_profile(np.array(refined.getchannel('A')))
    if should_use_refined_mask(
        base_profile,
        refined_profile,
        crop_boundary_touched=crop_boundary_touched,
    ):
        print(f"   Frame {photo_index}: target-lock retry accepted")
        return refined, True, refined_profile

    print(f"   Frame {photo_index}: target-lock retry rejected; preserving full-frame mask")
    return base_image, False, base_profile


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


def remove_background(
    image_bytes,
    photo_index=0,
    target_center=DEFAULT_TARGET_CENTER,
    return_metadata=False,
):
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
    output_bytes = _run_model(image_bytes)
    image = Image.open(io.BytesIO(output_bytes)).convert('RGBA')

    # ── 2. Target-aware cleanup and guarded retry ──
    image, component_details = _cleanup_mask(
        image, photo_index, target_center=target_center
    )
    with Image.open(io.BytesIO(image_bytes)) as source_image:
        source = source_image.convert('RGB').copy()
    image, target_lock_applied, profile = _target_locked_retry(
        source, image, photo_index, target_center
    )

    # Glass repair changes visible vehicle details, so it is opt-in. The default
    # production path preserves the source pixels for marketplace trust.
    if ENABLE_GLASS_REPAIR:
        image = _darken_windows_and_holes(image)
    
    # ── 4. AI-driven Glass Masking (FastSAM) ──
    if ENABLE_GLASS_MASKING:
        try:
            from processing.glass_masking import apply_glass_masking
            image = apply_glass_masking(image)
        except Exception as e:
            print(f"FastSAM glass masking failed: {e}")

    metadata = {
        **component_details,
        'targetLockApplied': target_lock_applied,
        'maskCoverage': round(profile['coverage'], 4),
    }
    return (image, metadata) if return_metadata else image
