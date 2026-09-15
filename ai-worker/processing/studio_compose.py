from PIL import Image, ImageDraw, ImageFilter, ImageOps, ImageChops, ImageEnhance
import numpy as np
import os
from functools import lru_cache

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


@lru_cache(maxsize=4)
def _make_background_template(cw, ch, ground_y):
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


def _make_background(cw, ch, ground_y):
    """Return an isolated copy of the cached studio background."""
    return _make_background_template(cw, ch, ground_y).copy()


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


def _draw_grounded_shadow(canvas, car_x, vehicle, ground_y):
    """Draw a restrained showroom contact shadow below the vehicle.

    Projecting the full alpha silhouette creates dark side lobes when a source
    photo is clipped. A grounded pair of ellipses is temporally stable across
    all viewpoints and keeps the visual weight underneath the tires.
    """
    vehicle_width, vehicle_height = vehicle.size
    center_x = car_x + vehicle_width // 2

    ambient_width = max(120, int(vehicle_width * 0.88))
    ambient_height = max(24, int(vehicle_height * 0.075))
    ambient = Image.new('RGBA', canvas.size, (0, 0, 0, 0))
    ambient_draw = ImageDraw.Draw(ambient)
    ambient_draw.ellipse(
        [
            center_x - ambient_width // 2,
            ground_y - ambient_height // 2,
            center_x + ambient_width // 2,
            ground_y + ambient_height // 2,
        ],
        fill=(18, 20, 25, 48),
    )
    ambient = ambient.filter(ImageFilter.GaussianBlur(radius=28))
    canvas.paste(ambient, (0, 0), ambient)

    contact_width = max(100, int(vehicle_width * 0.64))
    contact_height = max(12, int(vehicle_height * 0.026))
    contact = Image.new('RGBA', canvas.size, (0, 0, 0, 0))
    contact_draw = ImageDraw.Draw(contact)
    contact_draw.ellipse(
        [
            center_x - contact_width // 2,
            ground_y - contact_height // 2,
            center_x + contact_width // 2,
            ground_y + contact_height // 2,
        ],
        fill=(12, 14, 18, 78),
    )
    contact = contact.filter(ImageFilter.GaussianBlur(radius=11))
    canvas.paste(contact, (0, 0), contact)


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

def create_studio_image(vehicle_image, global_max_h=None, target_height_ratio=None):
    """
    Place vehicle onto a studio turntable.

    Key design decisions:
    - Fixed canvas (2400 × 1350) for all 36 frames → no jitter
    - Car scaled to 62% of canvas height → premium framing without clipping
    - Wheel-bottom row (not bbox bottom) aligned to platform top edge
      → car sits ON the turntable, never floats
    - LANCZOS resampling for sharpest edges

    Args:
        vehicle_image: PIL RGBA Image with transparent background
        global_max_h: Fallback sequence-wide reference height.
        target_height_ratio: Circularly smoothed output height relative to the
                             standard target height. This removes frame jitter
                             without flattening slow perspective changes.

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
    
    target_h = int(ch * CAR_HEIGHT_FILL)
    if target_height_ratio is not None:
        safe_ratio = max(0.84, min(float(target_height_ratio), 1.02))
        scale = (target_h * safe_ratio) / max(vh, 1)
    else:
        reference_vh = global_max_h if global_max_h else vh
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
    _draw_grounded_shadow(canvas, car_x, vehicle_scaled, plat_top_y)
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
