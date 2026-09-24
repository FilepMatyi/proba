from PIL import Image, ImageDraw, ImageFilter, ImageOps, ImageChops, ImageEnhance
import cv2
import math
import numpy as np
import os
from functools import lru_cache

from processing.stabilization import estimate_wheel_contacts
from processing.ground_contacts import silhouette_contacts, tire_contacts
from processing.source_detail import decontaminate_mask_edges
from processing.studio_photo_look import cyclorama_template, floor_reflection, photo_shadow_layers

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
PLATFORM_H_FRAC  = 0.36        # Include the farther tire in the visible floor surface
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


def robust_ground_anchor(alpha_arr):
    """Supported low silhouette level; isolated hooks and alpha dust are ignored."""
    height, width = alpha_arr.shape
    if not np.any(alpha_arr >= 160):
        return None
    mask = cv2.morphologyEx((alpha_arr >= 160).astype(np.uint8), cv2.MORPH_OPEN,
                            cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3)))
    present = mask.any(axis=0)
    if not present.any():
        return None
    bottom = height-1-np.argmax(mask[::-1], axis=0)
    # Select a low run with meaningful width. A narrow tow hitch cannot
    # anchor the vehicle, while the lower arc of a tire spans many columns.
    low = present & (bottom >= np.percentile(bottom[present], 98)-height*.018)
    changes = np.diff(np.r_[0, low.astype(np.int8), 0])
    runs = [(a, b) for a, b in zip(np.where(changes == 1)[0], np.where(changes == -1)[0])
            if b-a >= max(5, round(width*.018))]
    if runs:
        values = np.concatenate([bottom[a:b] for a, b in runs])
        return int(round(np.percentile(values, 94)))
    return int(round(np.percentile(bottom[present], 98)))


def studio_placement(image_size, anchor_y, canvas_size, target_height_ratio=1., fill_ratio=CAR_HEIGHT_FILL):
    """Return proportional scale and translation; no angle or image warp."""
    width, height = image_size
    canvas_w, canvas_h = canvas_size
    ratio = max(.84, min(1.02, float(target_height_ratio)))
    scale = min(canvas_h*fill_ratio*ratio/max(height, 1), canvas_w*.90/max(width, 1))
    scaled_w, scaled_h = max(1, round(width*scale)), max(1, round(height*scale))
    floor = _platform_geometry(canvas_w, canvas_h)
    # Place the near tire deeper on the visible floor so the farther tire in
    # a three-quarter view does not sit above the platform's back edge.
    ground_y = round(floor['center_y']+floor['radius_y']*.32)
    x = (canvas_w-scaled_w)//2
    y = ground_y-round(float(anchor_y)*scaled_h/max(height, 1))
    return (scaled_w, scaled_h), (x, y), ground_y


def _platform_geometry(cw, ch, depth_ratio=None):
    """Return shared turntable geometry and its optical contact plane."""
    pcx = cw // 2
    pcy = int(ch * PLATFORM_CY_FRAC)
    prw = int(cw * PLATFORM_W_FRAC / 2)
    prh = int(ch * (depth_ratio or PLATFORM_H_FRAC) / 2)
    pcy = min(pcy, ch - prh - 12)
    top_y = pcy - prh
    contact_y = top_y + int(round(prh * PLATFORM_CONTACT_DEPTH_FRAC))
    return {
        'canvas_height': ch,
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
    """Find separate tire lobes without assuming one wheel per image half."""
    return silhouette_contacts(alpha_arr)


def _build_ground_contacts(vehicle, alpha_arr, wheel_bottom, car_w):
    """Return one or two independent wheel contacts in vehicle coordinates."""
    detected = estimate_wheel_contacts(vehicle, minimum_aspect_ratio=1.0)
    if detected:
        return sorted(detected, key=lambda item: item['x'])

    # A single clearly visible tire is safer than labelling a rear hitch as
    # the second wheel. Preserve uncertainty instead of inventing a pair.
    partial = tire_contacts(vehicle)
    if partial:
        if len(partial) == 2 and vehicle.width/vehicle.height < 1.65:
            partial = [max(partial, key=lambda item: item['radius'])]
        return partial

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
    # Match the studio floor to the measured perspective, rather than bending
    # the photographed car to a thin ellipse. Normally the sequence planner
    # has already chosen this depth for ALL frames, avoiding platform pumping.
    required = _required_platform_radius(usable, car_x, platform)
    if required > platform['radius_y']:
        platform['radius_y'] = math.ceil(required)
        platform['center_y'] = min(platform['center_y'], platform['canvas_height']-math.ceil(required)-12)
        platform['top_y'] = platform['center_y']-platform['radius_y']
        platform['contact_y'] = platform['top_y']+platform['radius_y']*PLATFORM_CONTACT_DEPTH_FRAC
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

    car_y = int(round(car_y))
    anchors = [
        {
            **item,
            'canvasX': car_x + float(item['x']),
            'canvasY': car_y + float(item['y']),
        }
        for item in usable
    ]
    return int(round(car_y)), anchors


def _required_platform_radius(contacts, car_x, platform):
    """Minimum ellipse depth permitting one translation for all contacts."""
    required = float(platform['radius_y'])
    for first in contacts:
        for second in contacts:
            factors = []
            for item in (first, second):
                nx = (car_x+item['x']-platform['center_x']) / platform['radius_x']
                factors.append(math.sqrt(max(.01, 1-min(.995, abs(nx))**2)))
            required = max(required, (abs(first['y']-second['y'])+14) / sum(factors))
    return required


def build_grounding_layout(images, layout):
    """Use one floor depth and car scale throughout the complete revolution."""
    platform = _platform_geometry(CANVAS_W, CANVAS_H)
    required = float(platform['radius_y'])
    measured = 0
    for index, source in images.items():
        image = source.crop(source.getbbox()) if source.getbbox() else source
        scale = min(CANVAS_H*CAR_HEIGHT_FILL*layout[index]['targetHeightRatio']/max(image.height, 1),
                    CANVAS_W*.90/max(image.width, 1))
        # Use the same measurement path as composition, at a bounded size.
        proxy = image.copy()
        proxy.thumbnail((960, 960), Image.Resampling.LANCZOS)
        contacts = _build_ground_contacts(proxy, np.asarray(proxy.getchannel('A')),
                                          proxy.height-1, proxy.width)
        factor = image.height*scale/max(proxy.height, 1)
        scaled = [{**item, 'x': item['x']*factor, 'y': item['y']*factor} for item in contacts]
        required = max(required, _required_platform_radius(scaled, (CANVAS_W-image.width*scale)/2, platform))
        measured += len(contacts) >= 2
    # Leave room below the platform. A uniform shrink, if necessary, preserves
    # body proportions and detail; no view-specific stretching or zoom jumps.
    max_radius = CANVAS_H*.16
    grounding_scale = min(1., max_radius / max(required, 1.))
    depth_ratio = 2*min(max_radius, math.ceil(required+4))/CANVAS_H
    for item in layout.values():
        item.update({'platformDepthRatio': depth_ratio, 'groundingScale': grounding_scale})
    return {'platformDepthRatio': round(depth_ratio, 4),
            'groundingScale': round(grounding_scale, 4), 'groundContactPairFrames': measured}


def _enhance_vehicle_detail(vehicle):
    """Apply conservative, vehicle-only micro-contrast and sharpening."""
    if vehicle.mode != 'RGBA':
        vehicle = vehicle.convert('RGBA')
    red, green, blue, alpha = vehicle.split()
    rgb = Image.merge('RGB', (red, green, blue))
    rgb = ImageEnhance.Contrast(rgb).enhance(1.025)
    rgb = rgb.filter(ImageFilter.UnsharpMask(radius=1.15, percent=125, threshold=3))
    return Image.merge('RGBA', (*rgb.split(), alpha))


def _harmonize_vehicle_color(vehicle, strength=1.):
    """Conservatively tame blue outdoor glass reflections and hard hotspots.

    This is a tonal adjustment, not synthetic relighting; opaque body colour
    and all alpha values remain intact.
    """
    rgba = np.array(vehicle.convert('RGBA'), dtype=np.uint8)
    rgb = rgba[:, :, :3]
    h = rgba.shape[0]
    red = rgb[:, :, 0].astype(np.float32)
    green = rgb[:, :, 1].astype(np.float32)
    blue = rgb[:, :, 2].astype(np.float32)
    upper = np.arange(h)[:, None] < h*.60
    glass_blue = (upper & (rgba[:, :, 3] >= 180) & (blue > red+14)
                  & (blue > green+8) & (blue < 220) & (blue > 35))
    rgb[:, :, 2][glass_blue] = np.clip(
        blue[glass_blue] - np.minimum(18., (blue[glass_blue]-green[glass_blue])*.30)*strength,
        0, 255).astype(np.uint8)
    # Reduce only extreme channel highlights, avoiding global contrast loss.
    highlight = (rgba[:, :, 3] >= 180) & (rgb.max(axis=2) > 235)
    for channel in range(3):
        values = rgb[:, :, channel][highlight].astype(np.float32)
        rgb[:, :, channel][highlight] = np.clip(
            np.where(values > 235, 235+(values-235)*(1.-.18*strength), values), 0, 255
        ).astype(np.uint8)
    return Image.fromarray(rgba, 'RGBA')


@lru_cache(maxsize=2)
def _cyclorama_template(cw, ch):
    """Seamless neutral backdrop and floor, with no drawn platform or hub."""
    return cyclorama_template(cw, ch)


def _draw_body_shadow(canvas, vehicle_size, car_x, ground_y, contacts):
    """Wide soft body occlusion follows the same final translation as the car."""
    width, height = vehicle_size
    center_y = (sum(item['canvasY'] for item in contacts)/len(contacts)) if contacts else ground_y
    center_y = min(center_y+height*.025, ground_y+height*.04)
    layer = Image.new('RGBA', canvas.size, (0, 0, 0, 0))
    half_w, half_h = width*.41, max(10., height*.065)
    center_x = car_x+width/2
    ImageDraw.Draw(layer).ellipse((center_x-half_w, center_y-half_h,
                                   center_x+half_w, center_y+half_h),
                                  fill=(17, 19, 20, 50))
    layer = layer.filter(ImageFilter.GaussianBlur(radius=max(6, round(canvas.height*.016))))
    canvas.paste(layer, (0, 0), layer)


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


def _draw_turntable(canvas, cw, ch, geometry=None):
    """
    Draw a glossy turntable with rim, inner ring, hub, and highlight.
    Returns the shared turntable geometry.
    """
    geometry = geometry or _platform_geometry(cw, ch)
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

def create_studio_image(vehicle_image, global_max_h=None, target_height_ratio=None,
                        canvas_size=None, style='viewer'):
    """
    Place vehicle onto the selected studio background.

    The mask bounding box controls horizontal framing. A robust lower mask
    anchor is translated to the fixed floor level; the vehicle is never
    rotated, sheared or warped from wheel positions. The 10-photo export has
    its own floor treatment; the viewer retains its turntable appearance.

    Args:
        vehicle_image: PIL RGBA Image with transparent background
        global_max_h: Fallback sequence-wide reference height.
        target_height_ratio: Circularly smoothed output height relative to the
                             standard target height. This removes frame jitter
                             without flattening slow perspective changes.

    Returns:
        PIL RGB Image on studio canvas
    """
    if style not in ('viewer', 'photo'):
        raise ValueError('Unknown studio composition style')
    if vehicle_image.mode != 'RGBA':
        vehicle_image = vehicle_image.convert('RGBA')

    # Tight crop to non-transparent content
    bbox = vehicle_image.getbbox()
    if bbox:
        vehicle_image = vehicle_image.crop(bbox)
        vehicle_image = decontaminate_mask_edges(vehicle_image)

    cw, ch = canvas_size or (CANVAS_W, CANVAS_H)

    # The final composition uses only a supported lower mask level and a fixed
    # studio floor. It never rotates or shears the vehicle from wheel points.
    source_alpha = np.asarray(vehicle_image.getchannel('A'))
    anchor = robust_ground_anchor(source_alpha)
    if anchor is None:
        canvas = (_cyclorama_template(cw, ch).copy() if style == 'photo'
                  else _make_background(cw, ch, _platform_geometry(cw, ch)['top_y']))
        if style == 'viewer':
            _draw_turntable(canvas, cw, ch)
        return canvas
    source_contacts = tire_contacts(vehicle_image)
    # Tire detections control shadow placement only: switching between a
    # confident and an occluded wheel must not move the car between frames.
    dimensions, (car_x, car_y), ground_y = studio_placement(
        vehicle_image.size, anchor, (cw, ch),
        1. if target_height_ratio is None else target_height_ratio,
        fill_ratio=.70 if style == 'photo' else CAR_HEIGHT_FILL,
    )
    vehicle_scaled = _enhance_vehicle_detail(vehicle_image.resize(dimensions, Image.Resampling.LANCZOS))
    vehicle_scaled = _harmonize_vehicle_color(vehicle_scaled, 1. if style == 'photo' else .55)
    platform = _platform_geometry(cw, ch)
    if style == 'photo':
        canvas = _cyclorama_template(cw, ch).copy()
    else:
        canvas = _make_background(cw, ch, platform['top_y'])
        _draw_turntable(canvas, cw, ch, platform)
    # Contact shadows may follow independently visible tires, but their
    # positions never change the vehicle placement or its orientation.
    scale_x, scale_y = dimensions[0]/vehicle_image.width, dimensions[1]/vehicle_image.height
    anchors = [{'canvasX': car_x+item['x']*scale_x, 'canvasY': car_y+item['y']*scale_y,
                'radius': item['radius']*scale_x} for item in source_contacts]
    if style == 'photo':
        reflection = floor_reflection(vehicle_scaled, ground_y-car_y, ch-ground_y)
        canvas.paste(reflection, (car_x, ground_y), reflection)
        for shadow_layer, location in photo_shadow_layers((cw, ch), dimensions,
                                                           car_x, ground_y, anchors):
            canvas.paste(shadow_layer, location, shadow_layer)
    else:
        _draw_body_shadow(canvas, dimensions, car_x, ground_y, anchors)
    if style == 'viewer' and anchors:
        _draw_grounded_shadow(canvas, vehicle_scaled, anchors)
    elif style == 'viewer':
        shadow = Image.new('RGBA', (cw, ch), (0, 0, 0, 0))
        sd = ImageDraw.Draw(shadow)
        half_w = dimensions[0]*.38
        half_h = max(9, dimensions[1]*.035)
        center_x = cw/2
        sd.ellipse((center_x-half_w, ground_y-half_h, center_x+half_w, ground_y+half_h),
                   fill=(16, 20, 20, 38))
        shadow = shadow.filter(ImageFilter.GaussianBlur(radius=max(6, round(ch*.012))))
        canvas.paste(shadow, (0, 0), shadow)
    canvas.paste(vehicle_scaled, (car_x, car_y), vehicle_scaled)
    return canvas
