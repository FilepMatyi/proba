from PIL import Image, ImageDraw, ImageFilter, ImageOps, ImageChops, ImageEnhance
import numpy as np
import os

# ─── Canvas constants ────────────────────────────────────────────────
# Fixed canvas for ALL 36 frames → no jitter when the viewer flips frames.
CANVAS_W = 2400
CANVAS_H = 1350       # 16:9

# The car is scaled so its height fills this fraction of canvas height.
# 0.62 makes the car look significantly larger and more premium.
CAR_HEIGHT_FILL = 0.62

# Turntable geometry (fraction of canvas)
PLATFORM_W_FRAC  = 0.85        # Wider turntable base
PLATFORM_H_FRAC  = 0.085       # Perspective matched height
PLATFORM_CY_FRAC = 0.82        # Lowered to make room for larger car

# Debug overlay — set DEBUG_OVERLAY=true to draw alignment guides
DEBUG_OVERLAY = os.getenv('DEBUG_OVERLAY', 'false').lower() == 'true'

# Background gradient
BG_TOP   = (225, 227, 232)     # Slightly darker/moodier top
BG_FLOOR = (210, 212, 218)     # Slightly darker floor


# ═══════════════════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════════════════

def _find_wheel_bottom(alpha_arr, car_w):
    """
    Scan the alpha channel from bottom to top and return the Y coordinate
    of the first row that has a solid, wide run of pixels.
    By using alpha > 200, we ignore soft shadows left by rembg.
    By requiring a run of at least 5% of car width, we ignore small noise.
    """
    h, w = alpha_arr.shape
    min_run = max(int(car_w * 0.05), 10)

    for y in range(h - 1, -1, -1):
        row = (alpha_arr[y] > 200).astype(np.int8)
        # Efficient longest-run calculation using diff
        padded = np.concatenate([[0], row, [0]])
        diffs = np.diff(padded)
        starts = np.where(diffs == 1)[0]
        ends   = np.where(diffs == -1)[0]
        if len(starts) > 0:
            max_run = int((ends - starts).max())
            if max_run >= min_run:
                return y

    # Fallback
    return h - 1


def _make_background(cw, ch, ground_y):
    """Paint a premium radial-spotlight studio gradient."""
    canvas = Image.new('RGB', (cw, ch), BG_TOP)
    draw   = ImageDraw.Draw(canvas)

    # Paint floor gradient first
    for y in range(ground_y, ch):
        t = (y - ground_y) / max(ch - ground_y, 1)
        r = int(BG_FLOOR[0] - 22 * t)
        g = int(BG_FLOOR[1] - 22 * t)
        b = int(BG_FLOOR[2] - 24 * t)
        draw.line([(0, y), (cw, y)], fill=(max(0, r), max(0, g), max(0, b)))
        
    # Paint top background (radial spotlight behind the car)
    # Fast approach using numpy array
    x = np.linspace(0, cw, cw)
    y = np.linspace(0, ground_y, ground_y)
    X, Y = np.meshgrid(x, y)
    
    # Center of spotlight
    cx, cy = cw / 2, ground_y * 0.6
    
    # Distance from center
    dist = np.sqrt((X - cx)**2 + (Y - cy)**2)
    max_dist = max(cw, ground_y)
    
    # Create soft spotlight effect
    intensity = np.clip(1.0 - (dist / max_dist) * 1.5, 0, 1)
    
    # Base color is BG_TOP, center is brighter
    r = BG_TOP[0] + intensity * 21
    g = BG_TOP[1] + intensity * 19
    b = BG_TOP[2] + intensity * 15
    
    # Build RGB array
    bg_arr = np.zeros((ground_y, cw, 3), dtype=np.uint8)
    bg_arr[:,:,0] = r
    bg_arr[:,:,1] = g
    bg_arr[:,:,2] = b
    
    top_img = Image.fromarray(bg_arr, 'RGB')
    canvas.paste(top_img, (0,0))

    return canvas


def _draw_turntable(canvas, cw, ch):
    """
    Draw a glossy turntable with rim, inner ring, hub, and highlight.
    Returns the Y coordinate of the platform's TOP edge (where wheels sit).
    """
    pcx  = cw // 2
    pcy  = int(ch * PLATFORM_CY_FRAC)
    prw  = int(cw * PLATFORM_W_FRAC / 2)
    prh  = int(ch * PLATFORM_H_FRAC / 2)

    top_y = pcy - prh

    # Drop shadow
    shadow = Image.new('RGBA', (cw, ch), (0, 0, 0, 0))
    ImageDraw.Draw(shadow).ellipse(
        [pcx - prw - 25, pcy - prh + 10,
         pcx + prw + 25, pcy + prh + 35],
        fill=(0, 0, 0, 28)
    )
    shadow = shadow.filter(ImageFilter.GaussianBlur(radius=20))
    canvas.paste(shadow, (0, 0), shadow)

    # Platform layers
    plat = Image.new('RGBA', (cw, ch), (0, 0, 0, 0))
    pd   = ImageDraw.Draw(plat)

    # Outer rim
    pd.ellipse([pcx-prw-4, pcy-prh+3, pcx+prw+4, pcy+prh+4],
               fill=(162, 164, 172, 240))
    # Main surface
    pd.ellipse([pcx-prw, pcy-prh, pcx+prw, pcy+prh],
               fill=(202, 204, 212, 245))
    # Inner ring
    irw, irh = int(prw * 0.80), int(prh * 0.80)
    pd.ellipse([pcx-irw, pcy-irh, pcx+irw, pcy+irh],
               fill=(194, 196, 204, 245))
    # Center hub
    hw, hh = int(prw * 0.07), int(prh * 0.28)
    pd.ellipse([pcx-hw, pcy-hh, pcx+hw, pcy+hh],
               fill=(178, 180, 190, 255))

    # Glossy highlight
    hl = Image.new('RGBA', (cw, ch), (0, 0, 0, 0))
    hlw, hlh = int(prw * 0.50), int(prh * 0.20)
    hly = pcy - int(prh * 0.55)
    ImageDraw.Draw(hl).ellipse(
        [pcx-hlw, hly-hlh, pcx+hlw, hly+hlh],
        fill=(255, 255, 255, 50)
    )
    hl = hl.filter(ImageFilter.GaussianBlur(radius=7))
    plat = Image.alpha_composite(plat, hl)

    canvas.paste(plat, (0, 0), plat)
    return top_y


import cv2

def _draw_generative_shadow(canvas, cw, ch, car_x, car_y, vehicle):
    """
    Project the vehicle's alpha mask to create a realistic drop shadow
    that perfectly matches the silhouette.
    """
    vw, vh = vehicle.size
    
    # 1. Extract the alpha channel as a numpy array
    alpha = np.array(vehicle)[:, :, 3]
    
    # 2. Pad the mask to prevent clipping during shear
    pad = int(cw * 0.2)
    canvas_w, canvas_h = vw + pad * 2, vh + pad * 2
    padded = np.zeros((canvas_h, canvas_w), dtype=np.uint8)
    padded[pad:pad+vh, pad:pad+vw] = alpha
    
    # 3. Affine Transform (Shear and Squash)
    # The car is at (pad, pad). We want to squash it vertically (scale_y = 0.15)
    # and shear it slightly to the right to simulate ambient lighting.
    src_pts = np.float32([[pad, pad], [pad+vw, pad], [pad, pad+vh]])
    
    scale_y = 0.15
    offset_y = vh * 0.35  # Push down so it sits under the tires
    shear_x = 50
    
    dst_pts = np.float32([
        [pad - shear_x, pad * scale_y + offset_y + pad],
        [pad + vw + shear_x, pad * scale_y + offset_y + pad],
        [pad, (pad+vh) * scale_y + offset_y + pad]
    ])
    
    M = cv2.getAffineTransform(src_pts, dst_pts)
    shadow_cv = cv2.warpAffine(padded, M, (canvas_w, canvas_h))
    
    # 4. Convert to PIL
    shadow_img = Image.fromarray(shadow_cv, mode='L')
    
    # 5. Create multiple blurred layers for soft lighting
    # Contact shadow (dark, tight)
    blur1 = shadow_img.filter(ImageFilter.GaussianBlur(10))
    blur1 = blur1.point(lambda p: p * 0.85)
    
    # Mid shadow (medium, softer)
    blur2 = shadow_img.filter(ImageFilter.GaussianBlur(25))
    blur2 = blur2.point(lambda p: p * 0.6)
    
    # Ambient shadow (very wide, faint)
    blur3 = shadow_img.filter(ImageFilter.GaussianBlur(50))
    blur3 = blur3.point(lambda p: p * 0.35)
    
    # Combine layers
    shadow_final = ImageChops.add(blur1, blur2)
    shadow_final = ImageChops.add(shadow_final, blur3)
    
    # 5b. Ambient Occlusion — tight dark shadow directly under the car
    # This simulates the darkness where the car body blocks ambient light
    ao_mask = Image.fromarray(padded, mode='L')  # Original unsheared mask
    # Shift it down slightly and blur tightly
    ao_shifted = Image.new('L', (canvas_w, canvas_h), 0)
    ao_shifted.paste(ao_mask, (0, 8))  # 8px down
    ao_blur = ao_shifted.filter(ImageFilter.GaussianBlur(6))
    ao_blur = ao_blur.point(lambda p: min(255, int(p * 1.2)))  # Intensify
    
    # Combine AO with the projected shadow
    shadow_final = ImageChops.add(shadow_final, ao_blur)
    
    # 6. Paste onto canvas
    shadow_rgba = Image.new('RGBA', (canvas_w, canvas_h), (0,0,0,0))
    shadow_rgba.putalpha(shadow_final)
    
    # The vehicle is pasted at (car_x, car_y) on the main canvas.
    # In our padded shadow image, the top-left of the original vehicle was at (pad, pad).
    # So the top-left of the shadow image should be placed at (car_x - pad, car_y - pad)
    target_x = car_x - pad
    target_y = car_y - pad
    
    canvas.paste(shadow_rgba, (target_x, target_y), shadow_rgba)


def _draw_reflection(canvas, vehicle, car_x, sit_y, wheel_bottom_local):
    """Draw faded floor reflection below the turntable."""
    rw, rh = vehicle.size
    
    # Crop off any empty space or noise BELOW the actual wheels before flipping
    # so the tires in the reflection perfectly touch the real tires.
    clean_vehicle = vehicle.crop((0, 0, rw, min(rh, wheel_bottom_local)))
    refl = ImageOps.flip(clean_vehicle)
    
    rw, rh = refl.size
    crop_h = int(rh * 0.35) # Show more reflection
    if crop_h < 2:
        return
    refl = refl.crop((0, 0, rw, crop_h))

    fade = Image.new('L', (rw, crop_h), 0)
    fd   = ImageDraw.Draw(fade)
    for y in range(crop_h):
        # Stronger reflection fade
        fd.line([(0, y), (rw, y)], fill=int(30 * (1 - y / crop_h)))

    if refl.mode == 'RGBA':
        r, g, b, a = refl.split()
        a = ImageChops.multiply(a, fade)
        refl = Image.merge('RGBA', (r, g, b, a))

    # Paste exactly at sit_y so tires touch
    canvas.paste(refl, (car_x, sit_y), refl)


# ═══════════════════════════════════════════════════════════════════════
# MAIN ENTRY POINT
# ═══════════════════════════════════════════════════════════════════════

def create_studio_image(vehicle_image, global_max_h=None):
    """
    Place vehicle onto a studio turntable.

    Key design decisions:
    - Fixed canvas (2400 × 1350) for all 24 frames → no jitter
    - Car scaled to 52% of canvas height → tires never clip
    - Wheel-bottom row (not bbox bottom) aligned to platform top edge
      → car sits ON the turntable, never floats
    - LANCZOS resampling for sharpest edges

    Args:
        vehicle_image: PIL RGBA Image with transparent background
        global_max_h: The maximum height of the vehicle's bbox across all 36 frames. 
                      Used to scale all frames consistently and prevent "breathing" zooms.

    Returns:
        PIL RGB Image on studio canvas
    """
    if vehicle_image.mode != 'RGBA':
        vehicle_image = vehicle_image.convert('RGBA')

    # Tight crop to non-transparent content
    bbox = vehicle_image.getbbox()
    if bbox:
        vehicle_image = vehicle_image.crop(bbox)

    cw, ch = CANVAS_W, CANVAS_H

    # ── Scale car ──
    vw, vh = vehicle_image.size
    
    # Use global_max_h if provided, otherwise fallback to local vh
    reference_vh = global_max_h if global_max_h else vh
    
    target_h = int(ch * CAR_HEIGHT_FILL)
    
    # Scale factor is based on the REFERENCE height, not the local height.
    # This guarantees that if this frame is slightly smaller than the max frame,
    # it stays proportionally smaller on the canvas, preventing fake zooming!
    scale = target_h / reference_vh
    
    # Ensure the scaled width doesn't exceed 90% of the canvas width
    if (vw * scale) > int(cw * 0.90):
        scale = int(cw * 0.90) / vw
        
    target_w = int(vw * scale)
    local_target_h = int(vh * scale) # The actual height of THIS scaled frame
    
    vehicle_scaled = vehicle_image.resize((target_w, local_target_h), Image.LANCZOS)

    # ── Find the actual wheel-bottom row ──
    alpha_arr = np.array(vehicle_scaled)[:, :, 3]
    wheel_bottom_local = _find_wheel_bottom(alpha_arr, target_w)
    # How many pixels of "dead space" below the wheels?
    bottom_gap = local_target_h - 1 - wheel_bottom_local

    # ── Turntable top-edge Y ──
    plat_top_y = int(ch * PLATFORM_CY_FRAC) - int(ch * PLATFORM_H_FRAC / 2)

    # ── Position car so wheel_bottom row == platform top edge ──
    # car_y + wheel_bottom_local == plat_top_y
    car_y = plat_top_y - wheel_bottom_local
    car_x = (cw - target_w) // 2
    car_cx = cw // 2

    # ── Assemble canvas ──
    canvas = _make_background(cw, ch, plat_top_y)
    _draw_reflection(canvas, vehicle_scaled, car_x, plat_top_y, wheel_bottom_local)
    _draw_turntable(canvas, cw, ch)
    _draw_generative_shadow(canvas, cw, ch, car_x, car_y, vehicle_scaled)
    canvas.paste(vehicle_scaled, (car_x, car_y), vehicle_scaled)

    # ── Contrast boost for punch ──
    canvas = ImageEnhance.Contrast(canvas).enhance(1.08)
    canvas = ImageEnhance.Sharpness(canvas).enhance(1.20)

    # ── Color harmonization: warm up slightly to match studio lighting ──
    # Shift toward neutral warm by reducing blue cast from outdoor captures
    canvas_arr = np.array(canvas)
    # Subtle warm shift: reduce blue by 3%, increase red by 1%
    canvas_arr[:,:,0] = np.clip(canvas_arr[:,:,0].astype(np.int16) + 2, 0, 255).astype(np.uint8)  # R
    canvas_arr[:,:,2] = np.clip(canvas_arr[:,:,2].astype(np.int16) - 4, 0, 255).astype(np.uint8)  # B
    canvas = Image.fromarray(canvas_arr, 'RGB')

    # ── Debug overlay ──
    if DEBUG_OVERLAY:
        dbg = ImageDraw.Draw(canvas)
        # Bounding box (green)
        dbg.rectangle([car_x, car_y, car_x + target_w, car_y + local_target_h],
                      outline='lime', width=2)
        # Wheel-bottom line (red)
        wbl_y = car_y + wheel_bottom_local
        dbg.line([(0, wbl_y), (cw, wbl_y)], fill='red', width=2)
        # Platform top line (blue)
        dbg.line([(0, plat_top_y), (cw, plat_top_y)], fill='blue', width=2)
        # Label
        dbg.text((10, 10),
                 f"wheel_bottom={wheel_bottom_local} gap={bottom_gap} "
                 f"plat_top={plat_top_y} car_y={car_y} global_h={global_max_h}",
                 fill='white')

    return canvas
