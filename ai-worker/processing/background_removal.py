from rembg import remove
from PIL import Image
import io


def remove_background(image_bytes):
    """
    Remove background from image using rembg with IS-Net model.
    
    Args:
        image_bytes: Raw image bytes
        
    Returns:
        PIL Image with transparent background
    """
    # Remove background using rembg
    output_bytes = remove(image_bytes)
    
    # Convert to PIL Image
    image = Image.open(io.BytesIO(output_bytes))
    
    return image
