from rembg import new_session, remove
from PIL import Image
import io
import os

# Create ONNX session once at module import time to avoid reloading model on every call
MODEL_NAME = "isnet-general-use"
_session = new_session(MODEL_NAME)

# Alpha matting is very slow on CPU (~2-5 min per image).
# Enable only when running on GPU instances.
ENABLE_ALPHA_MATTING = os.getenv('ENABLE_ALPHA_MATTING', 'false').lower() == 'true'


def remove_background(image_bytes):
    """
    Remove background from image using rembg with IS-Net model.
    Uses post_process_mask for cleaner edges (fast on CPU).
    Alpha matting can be enabled via ENABLE_ALPHA_MATTING=true env var
    for GPU deployments where the extra quality is worth the compute time.

    Args:
        image_bytes: Raw image bytes

    Returns:
        PIL Image with transparent background
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
        # Fast path: post_process_mask applies morphological cleanup to the mask
        # which smooths edges without the heavy alpha matting computation.
        output_bytes = remove(image_bytes, session=_session, post_process_mask=True)

    # Convert to PIL Image
    image = Image.open(io.BytesIO(output_bytes))

    return image
