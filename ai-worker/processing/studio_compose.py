from PIL import Image, ImageDraw, ImageFilter, ImageOps, ImageChops, ImageEnhance
import cv2
import math
import numpy as np
import os
from functools import lru_cache

from processing.stabilization import estimate_wheel_contacts

# ─── Canvas constants ────────────────────────────────────────────────
# Fixed canvas for ALL 36 frames → no jitter when the viewer flips frames.
# 3200 × 1800 preserves substantially more inspection detail from 4K uploads,
# while the separate 1280 × 720 previews keep normal rotation lightweight.
CANVAS_W = max(2400, int(os.getenv('STUDIO_CANVAS_WIDTH', '3200')))
CANVAS_H = max(1350, int(os.getenv('STUDIO_CANVAS_HEIGHT', '1800')))

# The car is scaled so its height fills this fraction of canvas height.
# 0.62 makes the car look significantly larger and more premium.
CAR_HEIGHT_FILL = 0.62

# Turntable geometry (fraction of canvas)
PLATFORM_W_FRAC  = 0.85        # Wider turntable base
PLATFORM_H_FRAC  = 0.12        # Enough top-surface depth for 3/4 wheel contacts
PLATFORM_CY_FRAC = 0.82        # Lowered to make room for larger car
# The vehicle contact row belongs slightly inside the visible top surface.
# Aligning it to the ellipse's topmost tangent makes even a perfect mask float.
PLATFORM_CONTACT_DEPTH_FRAC = 1.15

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


def _platform_geometry(cw, ch):
    """Return shared turntable geometry and its optical contact plane."""
    pcx = cw // 2
    pcy = int(ch * PLATFORM_CY_FRAC)
    prw = int(cw * PLATFORM_W_FRAC / 2)
    prh = int(ch * PLATFORM_H_FRAC / 2)
    top_y = pcy - prh
    contact_y = top_y + int(round(prh * PLATFORM_CONTACT_DEPTH_FRAC))
    return {
        'center_x': pcx,
        'center_y': pcy,
        'radius_x': prw,
        'radius_y': prh,
        'top_y': top_y,
        'contact_y': contact_y,
    }


def _find_contact_spans(alpha_arr, wheel_bottom, car_w):
    """Locate solid near-ground alpha spans for view-aware tire shadows."""
    h, w = alpha_arr.shape
    band_height = max(10, int(h * 0.035))
    band_top = max(0, wheel_bottom - band_height)
    band_bottom = min(h, wheel_bottom + 1)
    near_ground = np.any(alpha_arr[band_top:band_bottom] > 200, axis=0)

    padded = np.concatenate([[False], near_ground, [False]])
    diffs = np.diff(padded.astype(np.int8))
    starts = np.where(diffs == 1)[0]
    ends = np.where(diffs == -1)[0]
    min_width = max(6, int(car_w * 0.008))
    spans = [
        (int(start), int(end))
        for start, end in zip(starts, ends)
        if end - start >= min_width
    ]

    # Segmentation noise can create many tiny islands. Keep the widest contact
    # regions while preserving their left-to-right order.
    if len(spans) > 4:
        spans = sorted(spans, key=lambda span: span[1] - span[0], reverse=True)[:4]
        spans.sort()
    return spans


def _find_independent_alpha_contacts(alpha_arr):
    """Estimate separate wheel bottoms when circle detection has no pair.

    The fallback follows the lower alpha envelope independently on the left and
    right of the vehicle. Broad, well-supported lobes are preferred over narrow
    tow bars or segmentation whiskers, and each returned contact keeps its own
    row instead of inheriting the deepest global pixel.
    """
    height, width = alpha_arr.shape
    if width < 80 or height < 60 or width / max(height, 1) < 1.0:
        return []

    mask = (alpha_arr >= 160).astype(np.uint8)
    mask = cv2.morphologyEx(
        mask,
        cv2.MORPH_OPEN,
        cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3)),
    )
    bottom = np.full(width, np.nan, dtype=np.float64)
    support = np.zeros(width, dtype=np.float64)
    support_depth = max(6, int(round(height * 0.10)))
    for x in range(width):
        rows = np.flatnonzero(mask[:, x])
        if rows.size:
            contact = int(rows[-1])
            band_top = max(0, contact - support_depth + 1)
            vertical_support = int(np.count_nonzero(mask[band_top:contact + 1, x]))
            if vertical_support >= max(3, int(round(height * 0.025))):
                bottom[x] = float(contact)
                support[x] = float(vertical_support)

    smooth_radius = max(2, int(round(width * 0.0125)))
    smoothed = np.full(width, np.nan, dtype=np.float64)
    for x in range(width):
        start = max(0, x - smooth_radius)
        end = min(width, x + smooth_radius + 1)
        values = bottom[start:end]
        values = values[np.isfinite(values)]
        if values.size >= max(3, smooth_radius // 2):
            smoothed[x] = float(np.median(values))

    contacts = []
    for start_ratio, end_ratio, expected_ratio in (
        (0.03, 0.50, 0.25),
        (0.50, 0.97, 0.75),
    ):
        start = int(round(width * start_ratio))
        end = int(round(width * end_ratio))
        columns = np.arange(start, end)
        valid = np.isfinite(smoothed[columns]) & (smoothed[columns] >= height * 0.52)
        if np.count_nonzero(valid) < max(8, int(round(width * 0.025))):
            continue
        valid_values = smoothed[columns][valid]
        threshold = float(np.percentile(valid_values, 82)) - height * 0.012
        deep = np.zeros(width, dtype=np.uint8)
        deep_columns = columns[valid & (smoothed[columns] >= threshold)]
        deep[deep_columns] = 1
        gap_width = max(3, int(round(width * 0.012)))
        deep = cv2.morphologyEx(
            deep.reshape(1, -1),
            cv2.MORPH_CLOSE,
            np.ones((1, gap_width), np.uint8),
        ).reshape(-1)
        deep[:start] = 0
        deep[end:] = 0
        padded = np.concatenate(([0], deep, [0]))
        changes = np.diff(padded)
        runs = list(zip(np.where(changes == 1)[0], np.where(changes == -1)[0]))
        minimum_width = max(6, int(round(width * 0.025)))
        runs = [run for run in runs if run[1] - run[0] >= minimum_width]
        if not runs:
            continue

        def run_score(run):
            run_columns = np.arange(run[0], run[1])
            run_values = bottom[run_columns]
            finite = np.isfinite(run_values)
            if not np.any(finite):
                return -1e9
            depth = float(np.percentile(run_values[finite], 88)) / max(height, 1)
            run_width = (run[1] - run[0]) / max(width, 1)
            support_score = float(np.mean(support[run_columns][finite])) / max(support_depth, 1)
            center = (run[0] + run[1]) / 2.0 / max(width, 1)
            position_prior = 1.0 - min(1.0, abs(center - expected_ratio) / 0.34)
            return depth * 0.55 + min(1.0, run_width / 0.10) * 0.20 + support_score * 0.18 + position_prior * 0.07

        best = max(runs, key=run_score)
        run_columns = np.arange(best[0], best[1])
        run_values = bottom[run_columns]
        finite = np.isfinite(run_values)
        run_columns, run_values = run_columns[finite], run_values[finite]
        if run_values.size < minimum_width:
            continue
        contact_y = float(np.percentile(run_values, 90))
        near = run_values >= contact_y - max(2.0, height * 0.008)
        near_columns = run_columns[near]
        if near_columns.size == 0:
            continue
        weights = np.maximum(support[near_columns], 1.0)
        contact_x = float(np.average(near_columns, weights=weights))
        radius = float(np.clip((best[1] - best[0]) * 0.55, height * 0.055, height * 0.22))
        contacts.append({
            'x': contact_x,
            'y': contact_y,
            'radius': radius,
            'confidence': 0.18,
        })

    contacts.sort(key=lambda item: item['x'])
    if len(contacts) == 2 and contacts[1]['x'] - contacts[0]['x'] < width * 0.25:
        return [max(contacts, key=lambda item: item['y'])]
    return contacts


def _build_ground_contacts(vehicle, alpha_arr, wheel_bottom, car_w):
    """Return one or two independent wheel contacts in vehicle coordinates."""
    detected = estimate_wheel_contacts(vehicle, minimum_aspect_ratio=1.0)
    if detected:
        return sorted(detected, key=lambda item: item['x'])

    alpha_contacts = _find_independent_alpha_contacts(alpha_arr)
    if alpha_contacts:
        return alpha_contacts

    # Front/rear views and difficult masks may not expose two reliable wheel
    # circles. Fall back to independently measured span bottoms; never flatten
    # several spans onto one global row.
    spans = _find_contact_spans(alpha_arr, wheel_bottom, car_w)
    contacts = []
    for start, end in spans:
        local_bottoms = []
        for x in range(start, end):
            rows = np.flatnonzero(alpha_arr[:, x] >= 160)
            if rows.size:
                local_bottoms.append(float(rows[-1]))
        if local_bottoms:
            contacts.append({
                'x': (start + end) / 2.0,
                'y': float(np.percentile(local_bottoms, 90)),
                'radius': max(12.0, (end - start) * 0.55),
                'confidence': 0.0,
            })
    return contacts


def _platform_vertical_bounds(platform, canvas_x, margin=5.0):
    """Return the visible ellipse's back/front Y bounds at ``canvas_x``."""
    normalized_x = (
        (float(canvas_x) - platform['center_x'])
        / max(float(platform['radius_x']), 1.0)
    )
    normalized_x = max(-0.995, min(0.995, normalized_x))
    half_depth = platform['radius_y'] * math.sqrt(max(0.0, 1.0 - normalized_x ** 2))
    return (
        platform['center_y'] - half_depth + margin,
        platform['center_y'] + half_depth - margin,
    )


def _fit_contacts_to_platform(contacts, car_x, platform, fallback_bottom):
    """Place the projected wheel plane inside the turntable without flattening it.

    Both wheels keep their distinct image-space Y coordinate. We solve only one
    shared vertical translation, preferring the standard near-wheel contact row
    while keeping every detected contact inside the visible platform ellipse.
    """
    usable = contacts or [{
        'x': float(platform['center_x'] - car_x),
        'y': float(fallback_bottom),
        'radius': 16.0,
        'confidence': 0.0,
    }]
    deepest = max(float(item['y']) for item in usable)
    preferred_y = float(platform['contact_y']) - deepest

    lower_limits = []
    upper_limits = []
    for item in usable:
        canvas_x = car_x + float(item['x'])
        back_y, front_y = _platform_vertical_bounds(platform, canvas_x)
        lower_limits.append(back_y - float(item['y']))
        upper_limits.append(front_y - float(item['y']))

    lower = max(lower_limits)
    upper = min(upper_limits)
    if lower <= upper:
        car_y = min(max(preferred_y, lower), upper)
    else:
        # An extreme high-angle source cannot be made eye-level without a 3D
        # reconstruction. Split the unavoidable mismatch instead of anchoring
        # one tire perfectly and making the other visibly float.
        car_y = (lower + upper) / 2.0

    anchors = [
        {
            **item,
            'canvasX': car_x + float(item['x']),
            'canvasY': car_y + float(item['y']),
        }
        for item in usable
    ]
    return int(round(car_y)), anchors


def _enhance_vehicle_detail(vehicle):
    """Apply conservative, vehicle-only micro-contrast and sharpening."""
    if vehicle.mode != 'RGBA':
        vehicle = vehicle.convert('RGBA')
    red, green, blue, alpha = vehicle.split()
    rgb = Image.merge('RGB', (red, green, blue))
    rgb = ImageEnhance.Contrast(rgb).enhance(1.025)
    rgb = rgb.filter(ImageFilter.UnsharpMask(radius=1.15, percent=125, threshold=3))
    return Image.merge('RGBA', (*rgb.split(), alpha))


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
    Returns the shared turntable geometry.
    """
    geometry = _platform_geometry(cw, ch)
    pcx = geometry['center_x']
    pcy = geometry['center_y']
    prw = geometry['radius_x']
    prh = geometry['radius_y']

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
    return geometry


def _make_local_contact_shadow(canvas_size, vehicle_size, contact_anchors):
    """Build independently positioned tire-contact patches for testing/reuse."""
    vehicle_width, vehicle_height = vehicle_size
    ordered = sorted(contact_anchors, key=lambda item: item['canvasX'])
    local = Image.new('RGBA', canvas_size, (0, 0, 0, 0))
    if not ordered:
        return local
    local_draw = ImageDraw.Draw(local)
    max_radius = max(float(item.get('radius', 1.0)) for item in ordered)
    for item in ordered:
        center_x = int(round(item['canvasX']))
        center_y = int(round(item['canvasY']))
        radius = max(1.0, float(item.get('radius', 1.0)))
        depth_scale = 0.72 + 0.28 * radius / max(max_radius, 1.0)
        shadow_width = max(42, min(int(vehicle_width * 0.18), int(radius * 1.65)))
        shadow_height = max(8, int(vehicle_height * 0.014 * depth_scale))
        opacity = int(round(78 + 30 * depth_scale))
        local_draw.ellipse(
            (
                center_x - shadow_width // 2,
                center_y - shadow_height // 2,
                center_x + shadow_width // 2,
                center_y + shadow_height // 2,
            ),
            fill=(6, 8, 10, opacity),
        )
    return local.filter(ImageFilter.GaussianBlur(radius=6))


def _draw_grounded_shadow(canvas, vehicle, contact_anchors):
    """Draw a perspective-aware shadow through the actual wheel contacts."""
    vehicle_width, vehicle_height = vehicle.size
    if not contact_anchors:
        return

    ordered = sorted(contact_anchors, key=lambda item: item['canvasX'])
    points = [
        (int(round(item['canvasX'])), int(round(item['canvasY'])))
        for item in ordered
    ]

    # A soft, rotated capsule follows the projected axle/ground direction. It
    # replaces the old horizontal shadow that made a raised far wheel obvious.
    ambient = Image.new('RGBA', canvas.size, (0, 0, 0, 0))
    ambient_draw = ImageDraw.Draw(ambient)
    ambient_width = max(30, int(vehicle_height * 0.055))
    if len(points) >= 2:
        ambient_draw.line(points, fill=(18, 20, 25, 48), width=ambient_width)
        radius = ambient_width // 2
        for x, y in (points[0], points[-1]):
            ambient_draw.ellipse(
                (x - radius, y - radius, x + radius, y + radius),
                fill=(18, 20, 25, 48),
            )
    else:
        x, y = points[0]
        half_width = max(70, int(vehicle_width * 0.30))
        ambient_draw.ellipse(
            (x - half_width, y - ambient_width, x + half_width, y + ambient_width),
            fill=(18, 20, 25, 45),
        )
    ambient = ambient.filter(ImageFilter.GaussianBlur(radius=26))
    canvas.paste(ambient, (0, 0), ambient)

    # Each wheel receives its own compact contact patch. Perspective-scaled
    # wheel radii naturally make the near patch larger and slightly darker.
    local = _make_local_contact_shadow(canvas.size, vehicle.size, ordered)
    canvas.paste(local, (0, 0), local)


def _draw_reflection(
    canvas,
    vehicle,
    car_x,
    sit_y,
    wheel_bottom_local,
    perspective_delta=0.0,
):
    """Draw faded floor reflection below the turntable."""
    rw, rh = vehicle.size
    # A single horizontal flip plane is physically wrong when the two wheel
    # contacts have visibly different depths. Suppressing that faint artifact
    # is cleaner than drawing a second, floating vehicle below the platform.
    if abs(float(perspective_delta)) > rh * 0.035:
        return
    
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
    - Fixed high-resolution 16:9 canvas for all 36 frames → no jitter
    - Car scaled to 62% of canvas height → premium framing without clipping
    - Wheel-bottom row (not bbox bottom) aligned to an optical contact plane
      inside the turntable surface, avoiding a tangent/hovering appearance
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
    vehicle_scaled = _enhance_vehicle_detail(vehicle_scaled)

    # ── Find the actual wheel-bottom row ──
    alpha_arr = np.array(vehicle_scaled)[:, :, 3]
    silhouette_bottom_local = _find_wheel_bottom(alpha_arr, target_w)
    ground_contacts = _build_ground_contacts(
        vehicle_scaled,
        alpha_arr,
        silhouette_bottom_local,
        target_w,
    )
    wheel_bottom_local = int(round(max(
        (item['y'] for item in ground_contacts),
        default=silhouette_bottom_local,
    )))
    # How many pixels of "dead space" below the wheels?
    bottom_gap = local_target_h - 1 - wheel_bottom_local

    # ── Turntable and optical contact plane ──
    platform = _platform_geometry(cw, ch)
    plat_top_y = platform['top_y']
    contact_y = platform['contact_y']

    car_x = (cw - target_w) // 2
    # ── Fit the two projected wheel contacts to the platform surface ──
    # The contacts keep their perspective Y difference; only a shared vertical
    # translation is solved, so the body is never tilted to fake grounding.
    car_y, contact_anchors = _fit_contacts_to_platform(
        ground_contacts,
        car_x,
        platform,
        wheel_bottom_local,
    )
    contact_rows = [item['canvasY'] for item in contact_anchors]
    reflection_y = int(round(max(contact_rows, default=contact_y)))
    perspective_delta = (
        max(contact_rows) - min(contact_rows)
        if len(contact_rows) >= 2 else 0.0
    )

    # ── Assemble canvas ──
    canvas = _make_background(cw, ch, plat_top_y)
    _draw_reflection(
        canvas,
        vehicle_scaled,
        car_x,
        reflection_y,
        wheel_bottom_local,
        perspective_delta=perspective_delta,
    )
    _draw_turntable(canvas, cw, ch)
    _draw_grounded_shadow(canvas, vehicle_scaled, contact_anchors)
    canvas.paste(vehicle_scaled, (car_x, car_y), vehicle_scaled)

    # ── Contrast boost for punch ──
    canvas = ImageEnhance.Contrast(canvas).enhance(1.08)

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
        # Independent wheel contacts (red)
        for item in contact_anchors:
            x = int(round(item['canvasX']))
            y = int(round(item['canvasY']))
            dbg.ellipse((x - 8, y - 8, x + 8, y + 8), outline='red', width=3)
        # Platform top line (blue)
        dbg.line([(0, plat_top_y), (cw, plat_top_y)], fill='blue', width=2)
        # Optical contact plane (yellow)
        dbg.line([(0, contact_y), (cw, contact_y)], fill='yellow', width=2)
        # Label
        dbg.text((10, 10),
                 f"wheel_bottom={wheel_bottom_local} gap={bottom_gap} "
                 f"plat_top={plat_top_y} contact={contact_y} "
                 f"car_y={car_y} perspective_delta={perspective_delta:.1f} "
                 f"global_h={global_max_h}",
                 fill='white')

    return canvas
