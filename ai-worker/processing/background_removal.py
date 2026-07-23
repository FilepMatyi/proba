from rembg import new_session, remove
from PIL import Image, ImageDraw, ImageFilter
import io
import os
import numpy as np

# Create ONNX session once at module import time to avoid reloading model on every call
MODEL_NAME = "isnet-general-use"
_session = new_session(MODEL_NAME)

# Alpha matting is very slow on CPU (~2-5 min per image).
# Enable only when running on GPU instances.
ENABLE_ALPHA_MATTING = os.getenv('ENABLE_ALPHA_MATTING', 'false').lower() == 'true'


def _darken_windows(image_rgba):
    """
    Automatically detects and darkens car windows/glass areas.

    How it works:
    - After background removal, windows appear as semi-transparent pixels
      (alpha 30-170) — the background bleeds through them.
    - We find those semi-transparent pixels, tint them dark blue-gray
      (like real tinted glass), and bring alpha up to near-opaque.
    - This turns ugly transparent/ghostly glass into realistic dark windows.

    Args:
        image_rgba: PIL Image in RGBA mode with background removed

    Returns:
        PIL Image RGBA with darkened windows
    """
    if image_rgba.mode != 'RGBA':
        image_rgba = image_rgba.convert('RGBA')

    arr = np.array(image_rgba, dtype=np.uint8)

    r, g, b, a = arr[:, :, 0], arr[:, :, 1], arr[:, :, 2], arr[:, :, 3]

    # Semi-transparent pixels are windows/glass (alpha between 30 and 175)
    # Fully opaque pixels (alpha > 175) are car body
    # Fully transparent pixels (alpha < 30) are removed background
    window_mask = (a >= 30) & (a <= 175)

    # Target: dark tinted glass — deep charcoal with a slight blue tint
    GLASS_R, GLASS_G, GLASS_B = 22, 28, 35

    if window_mask.any():
        # Blend toward tinted glass color based on how transparent they are:
        # More transparent = more glass visible = stronger tint effect
        blend = (175 - a[window_mask].astype(np.float32)) / 145.0  # 0.0 to 1.0
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

        # Bring alpha to near-opaque so windows look solid
        arr[:, :, 3][window_mask] = np.clip(
            a[window_mask] + 120, 0, 245
        ).astype(np.uint8)

    return Image.fromarray(arr, 'RGBA')


def _fill_internal_holes(image_rgba):
    """
    Fill small internal transparent holes inside the car silhouette.
    This catches missed interior details the model didn't fully fill.

    Args:
        image_rgba: PIL Image in RGBA mode

    Returns:
        PIL Image RGBA with holes filled
    """
    import numpy as np
    from scipy import ndimage

    arr = np.array(image_rgba)
    alpha = arr[:, :, 3]

    # Binary mask: 1 where we have car, 0 where transparent
    solid = (alpha > 50).astype(np.uint8)

    # Flood-fill from all edges to find background
    background = ndimage.binary_fill_holes(solid).astype(np.uint8)

    # Pixels that are inside the car hull but transparent = holes to fill
    holes = (background == 1) & (alpha < 50)
    if holes.any():
        arr[:, :, 3][holes] = 220  # Fill with near-opaque
        # Use nearby color for these pixels
        from PIL import Image as _PIL
        filled = _PIL.fromarray(arr, 'RGBA')
        return filled

    return image_rgba


def remove_background(image_bytes):
    """
    Remove background from image using rembg with IS-Net model.
    After removal, applies window tinting and hole filling for a clean result.

    Args:
        image_bytes: Raw image bytes

    Returns:
        PIL Image with transparent background, darkened windows
    """
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
            print(f"Alpha matting failed, falling back to standard removal: {e}")
            output_bytes = remove(image_bytes, session=_session, post_process_mask=True)
    else:
        output_bytes = remove(image_bytes, session=_session, post_process_mask=True)

    image = Image.open(io.BytesIO(output_bytes)).convert('RGBA')

    # Step 1: Darken windows / glass areas
    image = _darken_windows(image)

    # Step 2: Try to fill internal holes (optional, requires scipy)
    try:
        image = _fill_internal_holes(image)
    except Exception as e:
        print(f"Hole filling skipped: {e}")

    return image
