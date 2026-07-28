from ultralytics import FastSAM
import urllib.request
import os

url = "https://freepngimg.com/thumb/car/3-2-car-free-download-png.png"
if not os.path.exists("car.png"):
    urllib.request.urlretrieve(url, "car.png")

print("Loading FastSAM...")
model = FastSAM('FastSAM-s.pt')
print("Running inference...")
results = model('car.png', device='cpu', retina_masks=True, imgsz=1024, conf=0.4, iou=0.9)

# FastSAM doesn't natively support text prompts in the main call in all versions.
# We might need to use the `prompt` method.
prompt_process = results[0]
print(prompt_process)
