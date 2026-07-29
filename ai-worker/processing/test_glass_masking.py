import sys
import os

# Ensure the processing directory is in path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

try:
    import background_removal
    print("background_removal imported successfully.")
except Exception as e:
    print(f"Error importing background_removal: {e}")
    sys.exit(1)

from PIL import Image
from glass_masking import apply_glass_masking

image_path = '/app/car.png'
if not os.path.exists(image_path):
    print(f"Warning: {image_path} does not exist. Using dummy image.")
    # create dummy rgba image
    img = Image.new('RGBA', (1024, 1024), (255, 0, 0, 255))
else:
    print(f"Loading {image_path}...")
    img = Image.open(image_path).convert('RGBA')

print("Calling apply_glass_masking...")
try:
    result = apply_glass_masking(img)
    print("apply_glass_masking executed successfully without exceptions.")
    print("Result size:", result.size)
except Exception as e:
    import traceback
    print(f"Error during apply_glass_masking:")
    traceback.print_exc()
    sys.exit(1)
