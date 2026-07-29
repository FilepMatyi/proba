import cv2
import numpy as np
from ultralytics import FastSAM

# Load FastSAM model globally
# Note: FastSAM-s.pt is downloaded automatically on first run
try:
    _fastsam_model = FastSAM('FastSAM-s.pt')
except Exception as e:
    print(f"Warning: Could not load FastSAM model: {e}")
    _fastsam_model = None

def apply_glass_masking(image_rgba):
    """
    Applies an AI-driven glass masking to the image using FastSAM.
    Finds windows (segments in the upper half of the car) and tints them 
    with a studio reflection gradient.
    """
    if _fastsam_model is None:
        return image_rgba

    # Convert RGBA to RGB for FastSAM
    arr = np.array(image_rgba)
    rgb = cv2.cvtColor(arr, cv2.COLOR_RGBA2RGB)
    alpha = arr[:, :, 3]

    # Find the bounding box of the car
    coords = cv2.findNonZero(alpha)
    if coords is None:
        return image_rgba
        
    x, y, w, h = cv2.boundingRect(coords)
    
    # Run FastSAM
    # We lower confidence to find more segments, and IOU to separate them
    results = _fastsam_model(rgb, device='cpu', retina_masks=True, imgsz=1024, conf=0.4, iou=0.9, verbose=False)
    
    if len(results) == 0 or results[0].masks is None:
        return image_rgba

    masks = results[0].masks.data.cpu().numpy()
    
    # We will accumulate all valid window masks here
    combined_window_mask = np.zeros_like(alpha, dtype=np.uint8)
    
    # Cutoff for what we consider "upper part of car" (windows)
    # Typically windows are in the upper 40-55% of the car body.
    y_cutoff = y + int(h * 0.55)
    
    for i, mask in enumerate(masks):
        # Resize mask to original image shape if needed
        if mask.shape != alpha.shape:
            mask = cv2.resize(mask, (alpha.shape[1], alpha.shape[0]), interpolation=cv2.INTER_NEAREST)
            
        mask_binary = (mask > 0).astype(np.uint8) * 255
        
        # Intersect with the car's alpha mask so we don't select background
        mask_binary = cv2.bitwise_and(mask_binary, alpha)
        
        # If the mask is empty after intersection, skip
        if np.count_nonzero(mask_binary) == 0:
            continue
            
        # Find the center of this mask
        M = cv2.moments(mask_binary)
        if M["m00"] != 0:
            cy = int(M["m01"] / M["m00"])
            cx = int(M["m10"] / M["m00"])
            
            # Heuristic: Is it in the upper half?
            if cy < y_cutoff:
                # Also ensure it's not the ENTIRE car (area check)
                area = np.count_nonzero(mask_binary)
                car_area = np.count_nonzero(alpha)
                if 0.01 < (area / car_area) < 0.3:
                    # It's a localized segment in the upper half -> likely a window
                    combined_window_mask = cv2.bitwise_or(combined_window_mask, mask_binary)
                    
    # Now that we have a combined window mask, we apply a gradient tint
    if np.count_nonzero(combined_window_mask) > 0:
        # Create a gradient for the studio reflection
        # Top of window is dark, bottom is slightly lighter blue
        window_coords = cv2.findNonZero(combined_window_mask)
        wx, wy, ww, wh = cv2.boundingRect(window_coords)
        
        for row in range(wy, wy + wh):
            # 0.0 at top, 1.0 at bottom
            t = (row - wy) / max(1, wh)
            
            # Dark charcoal at top (15, 20, 25), lighter blue-gray at bottom (40, 50, 65)
            r = int(15 * (1 - t) + 40 * t)
            g = int(20 * (1 - t) + 50 * t)
            b = int(25 * (1 - t) + 65 * t)
            
            row_mask = combined_window_mask[row, :] == 255
            
            # Blend with original
            alpha_blend = 0.85 # 85% opaque tint
            
            arr[row, row_mask, 0] = arr[row, row_mask, 0] * (1 - alpha_blend) + r * alpha_blend
            arr[row, row_mask, 1] = arr[row, row_mask, 1] * (1 - alpha_blend) + g * alpha_blend
            arr[row, row_mask, 2] = arr[row, row_mask, 2] * (1 - alpha_blend) + b * alpha_blend
            # Ensure it's opaque in the final alpha channel so we don't see the background through it
            arr[row, row_mask, 3] = 255

    from PIL import Image
    return Image.fromarray(arr, 'RGBA')
