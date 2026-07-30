import cv2
import numpy as np
import json
import math

def calculate_sharpness(img_bytes):
    """Calculate the Laplacian variance of an image as a measure of sharpness."""
    np_arr = np.frombuffer(img_bytes, np.uint8)
    img = cv2.imdecode(np_arr, cv2.IMREAD_GRAYSCALE)
    if img is None:
        return 0
    return cv2.Laplacian(img, cv2.CV_64F).var()

def select_optimal_frames(sensor_data, frame_keys, num_frames=36):
    """
    Select the optimal 36 frames based on angle distribution (alpha) and sharpness.
    
    Args:
        sensor_data: List of dicts with {time, alpha, beta, gamma}
        frame_keys: List of MinIO object keys for the candidate frames (e.g., 108 frames)
    
    Returns:
        List of selected frame indices (0-based) to keep
    """
    if not sensor_data or len(sensor_data) == 0:
        # Fallback if no sensor data: just pick evenly spaced frames
        step = len(frame_keys) / num_frames
        return [[{'index': int(i * step), 'alpha': 0, 'beta': 0, 'gamma': 0, 'unwrapped_alpha': 0}] for i in range(num_frames)], 0, 0
        
    # Map each candidate frame to its approximate timestamp
    total_time = sensor_data[-1]['time']
    frame_interval = total_time / len(frame_keys)
    
    frame_metrics = []
    
    for i in range(len(frame_keys)):
        frame_time = i * frame_interval
        
        # Find closest sensor reading
        closest_sensor = min(sensor_data, key=lambda x: abs(x['time'] - frame_time))
        
        frame_metrics.append({
            'index': i,
            'time': frame_time,
            'alpha': closest_sensor.get('alpha', 0) or 0,
            'beta': closest_sensor.get('beta', 0) or 0,
            'gamma': closest_sensor.get('gamma', 0) or 0,
            'sharpness': 0 # Will be populated for candidates
        })
        
    # Calculate median beta and gamma to penalize tilted frames
    valid_betas = [m['beta'] for m in frame_metrics]
    valid_gammas = [m['gamma'] for m in frame_metrics]
    median_beta = sorted(valid_betas)[len(valid_betas)//2]
    median_gamma = sorted(valid_gammas)[len(valid_gammas)//2]
    
    # We want 36 evenly spaced angles
    # Handle alpha wraparound (0-360)
    # First, let's unwrap the alpha values to get continuous rotation
    unwrapped_alphas = [frame_metrics[0]['alpha']]
    for i in range(1, len(frame_metrics)):
        diff = frame_metrics[i]['alpha'] - frame_metrics[i-1]['alpha']
        if diff > 180: diff -= 360
        elif diff < -180: diff += 360
        unwrapped_alphas.append(unwrapped_alphas[-1] + diff)
        
    for i, alpha in enumerate(unwrapped_alphas):
        frame_metrics[i]['unwrapped_alpha'] = alpha
        
    total_rotation = unwrapped_alphas[-1] - unwrapped_alphas[0]
    # Normalize to exactly one full rotation (360°)
    # If user walked more or less than 360°, we map to one clean lap
    if abs(total_rotation) < 30:
        # Almost no rotation detected — fallback to even spacing
        step = len(frame_keys) / num_frames
        return [[{'index': int(i * step), 'alpha': 0, 'beta': median_beta, 'gamma': median_gamma, 'unwrapped_alpha': 0}] for i in range(num_frames)], median_beta, median_gamma
    direction = 1 if total_rotation > 0 else -1
    total_rotation = 360.0 * direction
    angle_step = total_rotation / num_frames
    
    selected_indices = []
    
    # For each of the 36 target angles, find the best candidate frame
    for i in range(num_frames):
        target_angle = unwrapped_alphas[0] + (i * angle_step)
        
        # Find frames within a reasonable angular window (e.g. +/- 0.5 * angle_step)
        # To ensure we get exactly 1 frame per bucket, we find the 3 closest frames
        # and then we will later evaluate their sharpness
        candidates = sorted(frame_metrics, key=lambda x: abs(x['unwrapped_alpha'] - target_angle))[:3]
        
        # We will let the worker download these specific candidate images and score them
        selected_indices.append(candidates)
        
    return selected_indices, median_beta, median_gamma
