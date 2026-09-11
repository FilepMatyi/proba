import cv2
import numpy as np
import os
import time

# Lazy-load the model to avoid slow startup
_upsampler = None

def _get_upsampler():
    """Initialize Real-ESRGAN upsampler on first use (lazy loading)."""
    global _upsampler
    if _upsampler is not None:
        return _upsampler
    
    try:
        from realesrgan import RealESRGANer
        from basicsr.archs.rrdbnet_arch import RRDBNet
        
        # Use RealESRGAN_x2plus for 2x upscale (faster, still great quality)
        # x4plus is available but much slower on CPU
        scale = int(os.getenv('ESRGAN_SCALE', '2'))
        
        if scale == 4:
            model = RRDBNet(num_in_ch=3, num_out_ch=3, num_feat=64, num_block=23, num_grow_ch=32, scale=4)
            model_name = 'RealESRGAN_x4plus'
        else:
            model = RRDBNet(num_in_ch=3, num_out_ch=3, num_feat=64, num_block=23, num_grow_ch=32, scale=2)
            model_name = 'RealESRGAN_x2plus'
        
        _upsampler = RealESRGANer(
            scale=scale,
            model_path=None,  # Auto-download
            model=model,
            tile=256,         # Tile size for memory efficiency on CPU
            tile_pad=10,
            pre_pad=0,
            half=False,       # CPU doesn't support half precision
            device='cpu'
        )
        
        print(f"Real-ESRGAN initialized: {model_name} (scale={scale}, device=cpu)")
        return _upsampler
        
    except Exception as e:
        print(f"Failed to initialize Real-ESRGAN: {e}")
        return None


def upscale_image(image_bytes):
    """
    Upscale a raw JPEG image using Real-ESRGAN.
    
    Args:
        image_bytes: Raw JPEG bytes
        
    Returns:
        Upscaled JPEG bytes, or original bytes if upscaling fails
    """
    upsampler = _get_upsampler()
    if upsampler is None:
        return image_bytes
    
    try:
        start = time.time()
        
        # Decode image
        np_arr = np.frombuffer(image_bytes, np.uint8)
        img = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
        
        if img is None:
            return image_bytes
        
        # Upscale
        output, _ = upsampler.enhance(img, outscale=upsampler.scale)
        
        # Encode back to JPEG
        _, encoded = cv2.imencode('.jpg', output, [cv2.IMWRITE_JPEG_QUALITY, 97])
        
        elapsed = time.time() - start
        h, w = img.shape[:2]
        oh, ow = output.shape[:2]
        print(f"  Real-ESRGAN: {w}x{h} → {ow}x{oh} in {elapsed:.1f}s")
        
        return encoded.tobytes()
        
    except Exception as e:
        print(f"Real-ESRGAN upscale failed: {e}")
        return image_bytes
