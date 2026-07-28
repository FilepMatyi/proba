import urllib.request
import os
from ultralytics import YOLO
from PIL import Image

url = "https://freepngimg.com/thumb/car/3-2-car-free-download-png.png"
if not os.path.exists("car.png"):
    urllib.request.urlretrieve(url, "car.png")

# Use a YOLOv8 segmentation model trained on car parts, e.g. from huggingface
# Since we don't have a direct URL to a standard ultralytics pt file for car parts,
# we might need to load one or use a heuristic. 
# For now, let's just see if YOLOv8n-seg can detect the windshield.
model = YOLO('yolov8n-seg.pt')
results = model('car.png')

# The default yolov8n-seg only detects "car" as a whole. It doesn't segment windows.
# We need a specialized model for windows.
# "https://huggingface.co/harpreetsahota/car-dd-segmentation-yolov11/resolve/main/best.pt"
# Let's try to download a car parts segmentation model.

print("Default YOLO classes:", model.names)
