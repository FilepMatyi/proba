from PIL import Image, ImageDraw, ImageFilter, ImageOps, ImageChops
import io


def create_studio_image(vehicle_image):
    """
    Place vehicle on a professional studio turntable with glossy floor
    reflection, multi-layer shadow, and studio infinity cove background.
    Auto-crops to the vehicle bounding box so nothing is clipped.

    Args:
        vehicle_image: PIL Image with transparent background (RGBA)

    Returns:
        PIL Image on studio canvas with turntable and reflection
    """
    # Ensure RGBA mode for proper transparency handling
    if vehicle_image.mode != 'RGBA':
        vehicle_image = vehicle_image.convert('RGBA')

    # Auto-crop to actual vehicle content (non-transparent bounding box)
    bbox = vehicle_image.getbbox()
    if bbox:
        vehicle_image = vehicle_image.crop(bbox)

    vw, vh = vehicle_image.size

    # Canvas sizing — generous padding for turntable + reflection
    padding_x = int(vw * 0.20)
    padding_top = int(vh * 0.12)
    padding_bottom = int(vh * 0.50)

    cw = vw + padding_x * 2
    ch = vh + padding_top + padding_bottom

    # Vehicle position on canvas
    vx = padding_x
    vy = padding_top

    # Ground line — where the car's wheels touch
    ground_y = vy + vh

    # ─────────────────────────────────────────────────
    # 1. STUDIO INFINITY COVE BACKGROUND
    # ─────────────────────────────────────────────────
    canvas = Image.new('RGB', (cw, ch), (240, 240, 242))
    draw = ImageDraw.Draw(canvas)

    for y in range(ch):
        if y < ground_y:
            # Upper wall: warm light gray
            t = y / max(ground_y, 1)
            r = int(238 + 7 * t)
            g = int(239 + 6 * t)
            b = int(242 + 5 * t)
        else:
            # Floor: subtle gradient down to slightly darker
            t = (y - ground_y) / max(ch - ground_y, 1)
            r = int(238 - 24 * t)
            g = int(239 - 24 * t)
            b = int(242 - 26 * t)
        draw.line([(0, y), (cw, y)], fill=(r, g, b))

    # ─────────────────────────────────────────────────
    # 2. TURNTABLE PLATFORM
    # ─────────────────────────────────────────────────
    platform_w = int(vw * 0.95)
    platform_h = int(vh * 0.09)
    platform_h = max(platform_h, 12)
    platform_x = vx + (vw - platform_w) // 2
    platform_y = ground_y - int(platform_h * 0.35)

    # Platform drop shadow
    plat_shadow = Image.new('RGBA', (cw, ch), (0, 0, 0, 0))
    ps_draw = ImageDraw.Draw(plat_shadow)
    ps_draw.ellipse(
        [platform_x - 15, platform_y + 8,
         platform_x + platform_w + 15, platform_y + platform_h + 18],
        fill=(0, 0, 0, 22),
    )
    plat_shadow = plat_shadow.filter(ImageFilter.GaussianBlur(radius=14))
    canvas.paste(plat_shadow, (0, 0), plat_shadow)

    # Platform rim (darker edge)
    plat_layer = Image.new('RGBA', (cw, ch), (0, 0, 0, 0))
    pl_draw = ImageDraw.Draw(plat_layer)
    pl_draw.ellipse(
        [platform_x - 3, platform_y + 3,
         platform_x + platform_w + 3, platform_y + platform_h + 3],
        fill=(185, 186, 192, 200),
    )

    # Platform surface with gradient sheen
    pl_draw.ellipse(
        [platform_x, platform_y,
         platform_x + platform_w, platform_y + platform_h],
        fill=(215, 216, 222, 220),
    )

    # Highlight stripe across the top of the platform (glossy sheen)
    highlight = Image.new('RGBA', (cw, ch), (0, 0, 0, 0))
    hl_draw = ImageDraw.Draw(highlight)
    hl_w = int(platform_w * 0.6)
    hl_h = max(int(platform_h * 0.35), 3)
    hl_x = platform_x + (platform_w - hl_w) // 2
    hl_y = platform_y + int(platform_h * 0.2)
    hl_draw.ellipse(
        [hl_x, hl_y, hl_x + hl_w, hl_y + hl_h],
        fill=(255, 255, 255, 50),
    )
    highlight = highlight.filter(ImageFilter.GaussianBlur(radius=6))
    plat_layer = Image.alpha_composite(plat_layer, highlight)

    canvas.paste(plat_layer, (0, 0), plat_layer)

    # ─────────────────────────────────────────────────
    # 3. FLOOR REFLECTION
    # ─────────────────────────────────────────────────
    reflection = vehicle_image.copy()
    reflection = ImageOps.flip(reflection)

    r_w, r_h = reflection.size
    ref_height = int(r_h * 0.30)
    if ref_height > 0:
        reflection = reflection.crop((0, 0, r_w, ref_height))

        # Create vertical fade mask
        fade_mask = Image.new('L', (r_w, ref_height), 0)
        fade_draw = ImageDraw.Draw(fade_mask)
        for y in range(ref_height):
            opacity = int(28 * (1 - y / ref_height))
            fade_draw.line([(0, y), (r_w, y)], fill=opacity)

        # Apply fade to reflection alpha channel
        if reflection.mode == 'RGBA':
            r, g, b, a = reflection.split()
            a = ImageChops.multiply(a, fade_mask)
            reflection = Image.merge('RGBA', (r, g, b, a))

        canvas.paste(reflection, (vx, ground_y + 3), reflection)

    # ─────────────────────────────────────────────────
    # 4. MULTI-LAYER GROUND SHADOW
    # ─────────────────────────────────────────────────
    shadow_layer = Image.new('RGBA', (cw, ch), (0, 0, 0, 0))
    s_draw = ImageDraw.Draw(shadow_layer)

    # Contact shadow (darkest, tightest)
    sw1 = int(vw * 0.68)
    sh1 = max(int(vh * 0.022), 3)
    s_draw.ellipse(
        [vx + (vw - sw1) // 2, ground_y - int(vh * 0.008),
         vx + (vw + sw1) // 2, ground_y - int(vh * 0.008) + sh1],
        fill=(0, 0, 0, 55),
    )

    # Mid shadow
    sw2 = int(vw * 0.80)
    sh2 = max(int(vh * 0.045), 6)
    s_draw.ellipse(
        [vx + (vw - sw2) // 2, ground_y - int(vh * 0.02),
         vx + (vw + sw2) // 2, ground_y - int(vh * 0.02) + sh2],
        fill=(0, 0, 0, 28),
    )

    # Ambient shadow (widest, lightest)
    sw3 = int(vw * 0.92)
    sh3 = max(int(vh * 0.075), 10)
    s_draw.ellipse(
        [vx + (vw - sw3) // 2, ground_y - int(vh * 0.035),
         vx + (vw + sw3) // 2, ground_y - int(vh * 0.035) + sh3],
        fill=(0, 0, 0, 14),
    )

    shadow_layer = shadow_layer.filter(ImageFilter.GaussianBlur(radius=14))
    canvas.paste(shadow_layer, (0, 0), shadow_layer)

    # ─────────────────────────────────────────────────
    # 5. PASTE VEHICLE (on top of everything)
    # ─────────────────────────────────────────────────
    canvas.paste(vehicle_image, (vx, vy), vehicle_image)

    return canvas
