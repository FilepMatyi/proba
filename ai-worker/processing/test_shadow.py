import urllib.request
from PIL import Image, ImageDraw, ImageFilter
import numpy as np
import cv2
import os

# Download a sample car PNG with transparent background
url = "https://freepngimg.com/thumb/car/3-2-car-free-download-png.png"
if not os.path.exists("car.png"):
    urllib.request.urlretrieve(url, "car.png")

vehicle = Image.open("car.png").convert("RGBA")
# Resize for faster processing
vehicle.thumbnail((800, 800))
vw, vh = vehicle.size

# Extract alpha channel
alpha = np.array(vehicle)[:, :, 3]

# Create a larger canvas for the shadow
pad = 400
canvas_w, canvas_h = vw + pad * 2, vh + pad * 2

# Pad the alpha channel
alpha_padded = np.zeros((canvas_h, canvas_w), dtype=np.uint8)
alpha_padded[pad:pad+vh, pad:pad+vw] = alpha

# 1. We want to shear it (offset X by Y) and squash it vertically (scale Y)
src_pts = np.float32([[pad, pad], [pad+vw, pad], [pad, pad+vh]])

scale_y = 0.15
offset_y = vh * 0.45  # Push it down so it sits under the tires

dst_pts = np.float32([
    [pad - 50, pad * scale_y + offset_y + pad], # Top-left skewed
    [pad+vw + 50, pad * scale_y + offset_y + pad], # Top-right skewed
    [pad, (pad+vh) * scale_y + offset_y + pad]  # Bottom-left 
])

M = cv2.getAffineTransform(src_pts, dst_pts)
shadow_cv = cv2.warpAffine(alpha_padded, M, (canvas_w, canvas_h))

# Convert back to PIL
shadow_img = Image.fromarray(shadow_cv, mode='L')

# Contact shadow (dark, tight)
blur1 = shadow_img.filter(ImageFilter.GaussianBlur(5))
blur1 = blur1.point(lambda p: p * 0.9)

# Mid shadow
blur2 = shadow_img.filter(ImageFilter.GaussianBlur(15))
blur2 = blur2.point(lambda p: p * 0.5)

# Ambient shadow (wide)
blur3 = shadow_img.filter(ImageFilter.GaussianBlur(35))
blur3 = blur3.point(lambda p: p * 0.3)

from PIL import ImageChops
shadow_final = ImageChops.add(blur1, blur2)
shadow_final = ImageChops.add(shadow_final, blur3)

# Create an RGBA shadow image
shadow_rgba = Image.new('RGBA', (canvas_w, canvas_h), (0,0,0,0))
shadow_rgba.putalpha(shadow_final)

# Create a white background
final = Image.new('RGB', (canvas_w, canvas_h), (255,255,255))
final.paste(shadow_rgba, (0,0), shadow_rgba)
final.paste(vehicle, (pad, pad), vehicle)

final.save("shadow_out.jpg")
print("Saved shadow_out.jpg")
