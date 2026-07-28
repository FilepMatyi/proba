from ultralytics import FastSAM
from ultralytics.models.fastsam import FastSAMPrompt
import cv2

model = FastSAM('FastSAM-s.pt')
IMAGE_PATH = 'car.png'

# Run inference on an image
results = model(IMAGE_PATH, device='cpu', retina_masks=True, imgsz=1024, conf=0.4, iou=0.9)

# Process results
prompt_process = FastSAMPrompt(IMAGE_PATH, results, device='cpu')

# Text prompt
ann = prompt_process.text_prompt(text='windshield, car window, glass')

if len(ann) > 0:
    print(f"Found {len(ann)} masks for text prompt.")
    # Ann contains the mask(s)
else:
    print("No masks found for text prompt.")
