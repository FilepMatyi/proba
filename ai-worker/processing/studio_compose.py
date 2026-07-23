from PIL import Image, ImageDraw, ImageFilter, ImageOps, ImageChops, ImageEnhance
import numpy as np
import os

# ─── Canvas constants ────────────────────────────────────────────────
# Fixed canvas for ALL 24 frames → no jitter when the viewer flips frames.
CANVAS_W = 2400
CANVAS_H = 1350       # 16:9

# The car is scaled so its height fills this fraction of canvas height.
# 0.52 leaves generous room for turntable + reflection below and sky above.
CAR_HEIGHT_FILL = 0.52

# Turntable geometry (fraction of canvas)
PLATFORM_W_FRAC  = 0.68
PLATFORM_H_FRAC  = 0.075
PLATFORM_CY_FRAC = 0.79        # center-Y of platform ellipse

# Debug overlay — set DEBUG_OVERLAY=true to draw alignment guides
DEBUG_OVERLAY = os.getenv('DEBUG_OVERLAY', 'false').lower() == 'true'

# Background gradient
BG_TOP   = (234, 236, 240)
BG_FLOOR = (218, 220, 226)


# ═══════════════════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════════════════

def _find_wheel_bottom(alpha_arr):
    """
    Scan the alpha channel from bottom to top and return the Y coordinate
    of the first row that has ≥ 20 consecutive solid pixels (alpha > 100).
    This is the wheel–ground contact line, not noise or a stray pixel.

    Falls back to the bounding-box bottom if nothing is found.
    """
    h, w = alpha_arr.shape

    for y in range(h - 1, -1, -1):
        row = (alpha_arr[y] > 100).astype(np.int8)
        # Efficient longest-run calculation using diff
        padded = np.concatenate([[0], row, [0]])
        diffs = np.diff(padded)
        starts = np.where(diffs == 1)[0]
        ends   = np.where(diffs == -1)[0]
        if len(starts) > 0:
            max_run = int((ends - starts).max())
            if max_run >= 20:
                return y

    # Fallback
    return h - 1


def _make_background(cw, ch, ground_y):
    """Paint the infinity-cove studio gradient."""
    canvas = Image.new('RGB', (cw, ch), BG_TOP)
    draw   = ImageDraw.Draw(canvas)

    for y in range(ch):
        if y <= ground_y:
            t = y / max(ground_y, 1)
            r = int(BG_TOP[0] + (BG_FLOOR[0] - BG_TOP[0]) * t * 0.35)
            g = int(BG_TOP[1] + (BG_FLOOR[1] - BG_TOP[1]) * t * 0.35)
            b = int(BG_TOP[2] + (BG_FLOOR[2] - BG_TOP[2]) * t * 0.35)
        else:
            t = (y - ground_y) / max(ch - ground_y, 1)
            r = int(BG_FLOOR[0] - 22 * t)
            g = int(BG_FLOOR[1] - 22 * t)
            b = int(BG_FLOOR[2] - 24 * t)
        draw.line([(0, y), (cw, y)], fill=(max(0, r), max(0, g), max(0, b)))

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


def _draw_shadow(canvas, cw, car_cx, sit_y, car_w, car_h):
    """Draw 3-layer elliptical shadow at the wheel line."""
    shadow = Image.new('RGBA', (cw, canvas.height), (0, 0, 0, 0))
    sd = ImageDraw.Draw(shadow)

    for (frac_w, frac_h, alpha) in [
        (0.68, 0.020, 58),   # contact
        (0.80, 0.040, 30),   # mid
        (0.92, 0.065, 14),   # ambient
    ]:
        sw = int(car_w * frac_w)
        sh = max(int(car_h * frac_h), 4)
        sd.ellipse([car_cx - sw//2, sit_y - sh//2,
                    car_cx + sw//2, sit_y + sh//2],
                   fill=(0, 0, 0, alpha))

    shadow = shadow.filter(ImageFilter.GaussianBlur(radius=15))
    canvas.paste(shadow, (0, 0), shadow)


def _draw_reflection(canvas, vehicle, car_x, sit_y):
    """Draw faded floor reflection below the turntable."""
    refl = ImageOps.flip(vehicle)
    rw, rh = refl.size
    crop_h = int(rh * 0.25)
    if crop_h < 2:
        return
    refl = refl.crop((0, 0, rw, crop_h))

    fade = Image.new('L', (rw, crop_h), 0)
    fd   = ImageDraw.Draw(fade)
    for y in range(crop_h):
        fd.line([(0, y), (rw, y)], fill=int(20 * (1 - y / crop_h)))

    if refl.mode == 'RGBA':
        r, g, b, a = refl.split()
        a = ImageChops.multiply(a, fade)
        refl = Image.merge('RGBA', (r, g, b, a))

    canvas.paste(refl, (car_x, sit_y + 5), refl)


# ═══════════════════════════════════════════════════════════════════════
# MAIN ENTRY POINT
# ═══════════════════════════════════════════════════════════════════════

def create_studio_image(vehicle_image):
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
    scale = target_h / vh
    target_w = int(vw * scale)
    vehicle_scaled = vehicle_image.resize((target_w, target_h), Image.LANCZOS)

    # ── Find the actual wheel-bottom row ──
    alpha_arr = np.array(vehicle_scaled)[:, :, 3]
    wheel_bottom_local = _find_wheel_bottom(alpha_arr)
    # How many pixels of "dead space" below the wheels?
    bottom_gap = target_h - 1 - wheel_bottom_local

    # ── Turntable top-edge Y ──
    plat_top_y = int(ch * PLATFORM_CY_FRAC) - int(ch * PLATFORM_H_FRAC / 2)

    # ── Position car so wheel_bottom row == platform top edge ──
    # car_y + wheel_bottom_local == plat_top_y
    car_y = plat_top_y - wheel_bottom_local
    car_x = (cw - target_w) // 2
    car_cx = cw // 2

    # ── Assemble canvas ──
    canvas = _make_background(cw, ch, plat_top_y)
    _draw_reflection(canvas, vehicle_scaled, car_x, plat_top_y)
    _draw_turntable(canvas, cw, ch)
    _draw_shadow(canvas, cw, car_cx, plat_top_y, target_w, target_h)
    canvas.paste(vehicle_scaled, (car_x, car_y), vehicle_scaled)

    # ── Contrast boost for punch ──
    canvas = ImageEnhance.Contrast(canvas).enhance(1.05)
    canvas = ImageEnhance.Sharpness(canvas).enhance(1.08)

    # ── Debug overlay ──
    if DEBUG_OVERLAY:
        dbg = ImageDraw.Draw(canvas)
        # Bounding box (green)
        dbg.rectangle([car_x, car_y, car_x + target_w, car_y + target_h],
                      outline='lime', width=2)
        # Wheel-bottom line (red)
        wbl_y = car_y + wheel_bottom_local
        dbg.line([(0, wbl_y), (cw, wbl_y)], fill='red', width=2)
        # Platform top line (blue)
        dbg.line([(0, plat_top_y), (cw, plat_top_y)], fill='blue', width=2)
        # Label
        dbg.text((10, 10),
                 f"wheel_bottom={wheel_bottom_local} gap={bottom_gap} "
                 f"plat_top={plat_top_y} car_y={car_y}",
                 fill='white')

    return canvas
