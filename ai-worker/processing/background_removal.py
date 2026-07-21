from rembg import new_session, remove
from PIL import Image
import io

# Create ONNX session once at module import time to avoid reloading model on every call
MODEL_NAME = "isnet-general-use"
_session = new_session(MODEL_NAME)


def remove_background(image_bytes):
    """
    Remove background from image using rembg with IS-Net model.

    Args:
        image_bytes: Raw image bytes

    Returns:
        PIL Image with transparent background
    """
    # Remove background using rembg with reusable session
    output_bytes = remove(image_bytes, session=_session)

    # Convert to PIL Image
    image = Image.open(io.BytesIO(output_bytes))

    return image
