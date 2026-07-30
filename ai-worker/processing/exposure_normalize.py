import cv2
import numpy as np
from PIL import Image

def normalize_exposure(images_dict):
    """
    Given a dict {photo_index: PIL.Image (RGBA)}, normalize the exposure
    across all frames using histogram matching to a reference frame.
    
    Strategy:
    1. Convert each image to LAB color space
    2. Calculate the median L channel statistics across all frames
    3. Adjust each frame's L channel to match the median statistics
    4. Return the adjusted images
    """
    if len(images_dict) < 2:
        return images_dict
    
    # Collect L channel stats from all frames
    l_means = []
    l_stds = []
    lab_cache = {}
    
    for idx, img in images_dict.items():
        # Convert RGBA to RGB (ignore alpha for exposure calc)
        rgb = np.array(img.convert('RGB'))
        lab = cv2.cvtColor(rgb, cv2.COLOR_RGB2LAB).astype(np.float64)
        lab_cache[idx] = lab
        l_means.append(lab[:,:,0].mean())
        l_stds.append(lab[:,:,0].std())
    
    # Target: median statistics
    target_mean = np.median(l_means)
    target_std = np.median(l_stds)
    
    result = {}
    for idx, img in images_dict.items():
        lab = lab_cache[idx]
        l_channel = lab[:,:,0]
        
        # Standardize and re-scale to target distribution
        current_mean = l_channel.mean()
        current_std = l_channel.std()
        
        if current_std > 0:
            l_normalized = (l_channel - current_mean) * (target_std / current_std) + target_mean
        else:
            l_normalized = l_channel - current_mean + target_mean
        
        lab[:,:,0] = np.clip(l_normalized, 0, 255)
        
        # Convert back to RGB
        rgb_normalized = cv2.cvtColor(lab.astype(np.uint8), cv2.COLOR_LAB2RGB)
        
        # Reconstruct RGBA with original alpha
        alpha = np.array(img)[:,:,3]
        rgba = np.dstack([rgb_normalized, alpha])
        result[idx] = Image.fromarray(rgba, 'RGBA')
    
    return result
