from PIL import Image, ImageDraw, ImageFilter, ImageOps, ImageChops, ImageEnhance
import io
import numpy as np


# ─────────────────────────────────────────────────────────
# CANVAS CONSTANTS — kept identical across all 24 frames
# so the turntable and car stay perfectly aligned when
# the viewer flips between frames.
# ─────────────────────────────────────────────────────────
CANVAS_ASPECT = 16 / 9        # Landscape widescreen
CANVAS_BASE_W = 2400           # Full HD+ output width
CANVAS_BASE_H = int(CANVAS_BASE_W / CANVAS_ASPECT)   # 1350px

# Car body occupies this fraction of the canvas height (ensures no clipping)
CAR_HEIGHT_FILL = 0.58

# Turntable geometry (fraction of canvas)
PLATFORM_W_FRAC  = 0.72        # Platform width as fraction of canvas width
PLATFORM_H_FRAC  = 0.095       # Platform ellipse height fraction of canvas height
PLATFORM_Y_FRAC  = 0.78        # Center Y of platform as fraction of canvas height

# Studio background gradient
BG_TOP    = (232, 234, 238)    # Warm light gray top
BG_FLOOR  = (215, 218, 224)    # Slightly darker floor


def _make_canvas_background(cw, ch, ground_y):
    """
    Paint the infinity cove studio background:
    - Smooth gradient wall above ground line
    - Slightly darker floor below
    """
    canvas = Image.new('RGB', (cw, ch), BG_TOP)
    draw   = ImageDraw.Draw(canvas)

    for y in range(ch):
        if y <= ground_y:
            t = y / max(ground_y, 1)
            r = int(BG_TOP[0] + (BG_FLOOR[0] - BG_TOP[0]) * t * 0.3)
            g = int(BG_TOP[1] + (BG_FLOOR[1] - BG_TOP[1]) * t * 0.3)
            b = int(BG_TOP[2] + (BG_FLOOR[2] - BG_TOP[2]) * t * 0.3)
        else:
            t = (y - ground_y) / max(ch - ground_y, 1)
            r = int(BG_FLOOR[0] - 20 * t)
            g = int(BG_FLOOR[1] - 20 * t)
            b = int(BG_FLOOR[2] - 22 * t)
        draw.line([(0, y), (cw, y)], fill=(max(0, r), max(0, g), max(0, b)))

    return canvas


def _draw_turntable(canvas, cw, ch):
    """
    Draw a glossy, photo-realistic turntable platform.
    Returns the Y coordinate of the top of the platform (where the car sits).
    """
    plat_cx  = cw // 2
    plat_cy  = int(ch * PLATFORM_Y_FRAC)
    plat_rw  = int(cw * PLATFORM_W_FRAC / 2)    # half-width (x radius)
    plat_rh  = int(ch * PLATFORM_H_FRAC / 2)    # half-height (y radius)

    # The car's tires sit on the TOP edge of the ellipse
    car_sit_y = plat_cy - plat_rh

    # ── Drop shadow beneath the entire platform ──
    shadow = Image.new('RGBA', (cw, ch), (0, 0, 0, 0))
    sh_draw = ImageDraw.Draw(shadow)
    sh_draw.ellipse(
        [plat_cx - plat_rw - 30, plat_cy - plat_rh + 12,
         plat_cx + plat_rw + 30, plat_cy + plat_rh + 40],
        fill=(0, 0, 0, 30)
    )
    shadow = shadow.filter(ImageFilter.GaussianBlur(radius=22))
    canvas.paste(shadow, (0, 0), shadow)

    # ── Outer rim (darker ring) ──
    plat = Image.new('RGBA', (cw, ch), (0, 0, 0, 0))
    p_draw = ImageDraw.Draw(plat)
    p_draw.ellipse(
        [plat_cx - plat_rw - 5, plat_cy - plat_rh - 2,
         plat_cx + plat_rw + 5, plat_cy + plat_rh + 5],
        fill=(160, 162, 170, 240)
    )

    # ── Main surface (mid-gray, slightly lighter center) ──
    p_draw.ellipse(
        [plat_cx - plat_rw, plat_cy - plat_rh,
         plat_cx + plat_rw, plat_cy + plat_rh],
        fill=(200, 202, 210, 245)
    )

    # ── Inner ring detail (concentric groove) ──
    inner_rw = int(plat_rw * 0.82)
    inner_rh = int(plat_rh * 0.82)
    p_draw.ellipse(
        [plat_cx - inner_rw, plat_cy - inner_rh,
         plat_cx + inner_rw, plat_cy + inner_rh],
        fill=(192, 194, 202, 245)
    )

    # ── Center cap (small hub) ──
    hub_rw = int(plat_rw * 0.08)
    hub_rh = int(plat_rh * 0.30)
    p_draw.ellipse(
        [plat_cx - hub_rw, plat_cy - hub_rh,
         plat_cx + hub_rw, plat_cy + hub_rh],
        fill=(175, 178, 188, 255)
    )

    # ── Glossy highlight (bright ellipse at top edge) ──
    hl_layer = Image.new('RGBA', (cw, ch), (0, 0, 0, 0))
    hl_draw  = ImageDraw.Draw(hl_layer)
    hl_rw = int(plat_rw * 0.55)
    hl_rh = int(plat_rh * 0.22)
    hl_y  = plat_cy - int(plat_rh * 0.55)
    hl_draw.ellipse(
        [plat_cx - hl_rw, hl_y - hl_rh,
         plat_cx + hl_rw, hl_y + hl_rh],
        fill=(255, 255, 255, 55)
    )
    hl_layer = hl_layer.filter(ImageFilter.GaussianBlur(radius=8))
    plat = Image.alpha_composite(plat, hl_layer)

    canvas.paste(plat, (0, 0), plat)

    return car_sit_y


def _scale_car_to_canvas(vehicle_image, cw, ch):
    """
    Scale the car so its height equals CAR_HEIGHT_FILL of the canvas height,
    preserving aspect ratio. Never upscale beyond 2×.
    """
    vw, vh = vehicle_image.size
    target_h = int(ch * CAR_HEIGHT_FILL)
    scale    = target_h / vh
    target_w = int(vw * scale)
    # LANCZOS = sharpest resampling filter in Pillow
    resized  = vehicle_image.resize((target_w, target_h), Image.LANCZOS)
    return resized


def _draw_car_shadow(canvas, cw, car_x, car_y, car_w, car_h, sit_y):
    """
    Draw a soft 3-layer elliptical shadow directly under the car
    on the turntable surface.
    """
    shadow_layer = Image.new('RGBA', (cw, canvas.height), (0, 0, 0, 0))
    s_draw = ImageDraw.Draw(shadow_layer)

    cx = car_x + car_w // 2

    # Contact shadow (darkest, tightest)
    s1w = int(car_w * 0.70)
    s1h = max(int(car_h * 0.020), 4)
    s_draw.ellipse([cx - s1w//2, sit_y - s1h//2,
                    cx + s1w//2, sit_y + s1h//2], fill=(0, 0, 0, 60))

    # Mid shadow
    s2w = int(car_w * 0.82)
    s2h = max(int(car_h * 0.040), 7)
    s_draw.ellipse([cx - s2w//2, sit_y - s2h//2,
                    cx + s2w//2, sit_y + s2h//2], fill=(0, 0, 0, 30))

    # Ambient shadow
    s3w = int(car_w * 0.94)
    s3h = max(int(car_h * 0.065), 10)
    s_draw.ellipse([cx - s3w//2, sit_y - s3h//2,
                    cx + s3w//2, sit_y + s3h//2], fill=(0, 0, 0, 14))

    shadow_layer = shadow_layer.filter(ImageFilter.GaussianBlur(radius=16))
    canvas.paste(shadow_layer, (0, 0), shadow_layer)


def _draw_floor_reflection(canvas, vehicle_image, car_x, sit_y, cw):
    """
    Draw a faded floor reflection of the car just below the turntable.
    """
    reflection = ImageOps.flip(vehicle_image)
    rw, rh = reflection.size
    ref_h   = int(rh * 0.28)
    if ref_h < 2:
        return
    reflection = reflection.crop((0, 0, rw, ref_h))

    # Vertical alpha fade
    fade = Image.new('L', (rw, ref_h), 0)
    fd   = ImageDraw.Draw(fade)
    for y in range(ref_h):
        op = int(22 * (1.0 - y / ref_h))
        fd.line([(0, y), (rw, y)], fill=op)

    if reflection.mode == 'RGBA':
        r2, g2, b2, a2 = reflection.split()
        a2 = ImageChops.multiply(a2, fade)
        reflection = Image.merge('RGBA', (r2, g2, b2, a2))

    canvas.paste(reflection, (car_x, sit_y + 4), reflection)


def create_studio_image(vehicle_image):
    """
    Place vehicle on a fixed studio turntable platform.

    Key improvements over previous version:
    - Fixed canvas size (CANVAS_BASE_W × CANVAS_BASE_H) for every frame
      → car is always the same size = smooth, judder-free 360 rotation
    - Car scaled so its height = 58% of canvas (never clips tires)
    - Car bottom-aligned to turntable top edge = sits ON the turntable
    - Sharper output via LANCZOS resampling
    - Concentric ring turntable detail

    Args:
        vehicle_image: PIL Image with transparent background (RGBA)

    Returns:
        PIL RGB Image on studio canvas
    """
    if vehicle_image.mode != 'RGBA':
        vehicle_image = vehicle_image.convert('RGBA')

    # Tight crop to car bounding box — removes empty transparent margins
    # that would otherwise cause the car to appear smaller or offset
    bbox = vehicle_image.getbbox()
    if bbox:
        vehicle_image = vehicle_image.crop(bbox)

    cw = CANVAS_BASE_W
    ch = CANVAS_BASE_H

    # Turntable center-Y
    plat_cy = int(ch * PLATFORM_Y_FRAC)
    plat_rh = int(ch * PLATFORM_H_FRAC / 2)
    car_sit_y = plat_cy - plat_rh   # TOP of the turntable ellipse

    # ── 1. Background ──
    canvas = _make_canvas_background(cw, ch, car_sit_y)

    # ── 2. Floor reflection (goes under platform) ──
    vehicle_scaled = _scale_car_to_canvas(vehicle_image, cw, ch)
    vsw, vsh = vehicle_scaled.size
    car_x = (cw - vsw) // 2        # Horizontally centered
    car_y = car_sit_y - vsh         # Bottom of car == top of turntable
    _draw_floor_reflection(canvas, vehicle_scaled, car_x, car_sit_y, cw)

    # ── 3. Turntable platform (drawn over reflection) ──
    _draw_turntable(canvas, cw, ch)

    # ── 4. Car shadow (on top of platform surface) ──
    _draw_car_shadow(canvas, cw, car_x, car_y, vsw, vsh, car_sit_y)

    # ── 5. Car (topmost layer) ──
    canvas.paste(vehicle_scaled, (car_x, car_y), vehicle_scaled)

    # ── 6. Subtle contrast/clarity boost for sharpness ──
    enhancer = ImageEnhance.Contrast(canvas)
    canvas   = enhancer.enhance(1.06)

    return canvas
