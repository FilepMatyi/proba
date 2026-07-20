from PIL import Image, ImageDraw, ImageFilter
import io


def create_studio_image(vehicle_image):
    """
    Place vehicle on white canvas with realistic shadow under wheels.
    
    Args:
        vehicle_image: PIL Image with transparent background
        
    Returns:
        PIL Image on white canvas with shadow
    """
    # Create white canvas (1920x1080 or based on vehicle size)
    width, height = vehicle_image.size
    canvas_width = max(width + 200, 1920)
    canvas_height = max(height + 200, 1080)
    
    canvas = Image.new('RGB', (canvas_width, canvas_height), (255, 255, 255))
    
    # Calculate center position
    x_offset = (canvas_width - width) // 2
    y_offset = (canvas_height - height) // 2
    
    # Create shadow layer
    shadow_layer = Image.new('RGBA', (canvas_width, canvas_height), (0, 0, 0, 0))
    shadow_draw = ImageDraw.Draw(shadow_layer)
    
    # Create elliptical shadow under the vehicle (simulating wheel shadows)
    # Shadow is darker and more blurred at the bottom
    shadow_color = (0, 0, 0, 60)  # Semi-transparent black
    
    # Main shadow ellipse under the vehicle
    shadow_width = int(width * 0.8)
    shadow_height = int(height * 0.15)
    shadow_x = x_offset + (width - shadow_width) // 2
    shadow_y = y_offset + height - int(height * 0.2)
    
    shadow_draw.ellipse(
        [shadow_x, shadow_y, shadow_x + shadow_width, shadow_y + shadow_height],
        fill=shadow_color
    )
    
    # Blur the shadow for realism
    shadow_layer = shadow_layer.filter(ImageFilter.GaussianBlur(radius=15))
    
    # Composite shadow onto canvas
    canvas.paste(shadow_layer, (0, 0), shadow_layer)
    
    # Paste vehicle onto canvas
    if vehicle_image.mode == 'RGBA':
        canvas.paste(vehicle_image, (x_offset, y_offset), vehicle_image)
    else:
        canvas.paste(vehicle_image, (x_offset, y_offset))
    
    return canvas
