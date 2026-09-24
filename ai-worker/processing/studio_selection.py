"""Photo-only, quality-aware source selection around ten circular targets.

This operates on original capture candidates. The 36-frame viewer selection is
neither changed nor used as a hard limit. Image-based viewpoint measurements
are relative quality heuristics, never physical camera height/pitch estimates.
"""
import io
import json
import math
from collections import defaultdict

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageOps

from processing.frame_selector import analyze_image_quality
from processing.studio_colmap import parse_camera_pose_metadata
from processing.studio_detail import preserve_connected_soft_alpha
from processing.studio_pose import analyze_photo_pose
from processing.target_lock import mask_profile


COUNT = 10
WINDOW_DEGREES = 18.
HERO_WINDOW_DEGREES = 26.
MAX_PROXY_CANDIDATES = 5
PROXY_SIDE = 960
WEIGHTS = {
    'angle': .10,
    'sharpness': .22,
    'exposure': .07,
    'segmentation': .08,
    'viewpoint': .23,
    'perspective': .14,
    'framing': .10,
    'resolution': .06,
}


def _clamp(value):
    return max(0., min(1., float(value)))


def _focus_score(variance):
    # The original 650-cap saturated on this capture (most vehicle regions
    # were above it), making sharp and motion-blurred candidates indistinct.
    low, high = math.log1p(180.), math.log1p(2200.)
    return _clamp((math.log1p(max(variance, 0.))-low)/(high-low))


def circular_distance(first, second):
    return abs((float(first)-float(second)+180.) % 360. - 180.)


def classify_target_view(image):
    """Coarse side/axial/three-quarter class, independent of make/model."""
    if image is None:
        return 'three-quarter'
    bbox = image.getbbox()
    if not bbox:
        return 'three-quarter'
    width, height = bbox[2]-bbox[0], bbox[3]-bbox[1]
    aspect = width/max(1, height)
    if aspect >= 1.90:
        return 'side'
    if aspect <= 1.24:
        return 'front-rear'
    return 'three-quarter'


def _candidate_angles(catalog, camera_poses):
    indexes = [int(item['index']) for item in catalog]
    valid = {index: camera_poses[index] for index in indexes
             if index in camera_poses and 'azimuthDegrees' in camera_poses[index]}
    if len(valid) >= max(10, round(len(indexes)*.8)):
        registered = sorted(valid)
        raw = np.unwrap(np.radians([valid[index]['azimuthDegrees'] for index in registered]))
        direction = 1. if np.median(np.diff(raw)) >= 0 else -1.
        degrees = np.degrees((raw-raw[0])*direction)
        interpolated = np.interp(indexes, registered, degrees)
        return {index: float(angle % 360.) for index, angle in zip(indexes, interpolated)}, 'COLMAP'
    count = len(indexes)
    return {index: 360.*position/count for position, index in enumerate(indexes)}, 'sequence_fallback'


def generate_target_windows(catalog, camera_poses=None, target_types=None,
                            window_degrees=WINDOW_DEGREES,
                            hero_window_degrees=HERO_WINDOW_DEGREES):
    """Several unique original frames per target; seam distance is circular."""
    if len(catalog) < COUNT:
        raise ValueError('Not enough original capture frames for ten studio photos')
    catalog = sorted(catalog, key=lambda item: item['index'])
    angles, method = _candidate_angles(catalog, camera_poses or {})
    target_types = target_types or ['three-quarter']*COUNT
    windows = []
    for slot in range(COUNT):
        target = slot*360./COUNT
        view_type = target_types[slot]
        half_width = float(hero_window_degrees if view_type == 'three-quarter'
                           else window_degrees)
        half_width = max(6., min(36., half_width))
        pool = [{**item, 'selectionAngle': angles[item['index']],
                 'angleError': circular_distance(angles[item['index']], target)}
                for item in catalog
                if circular_distance(angles[item['index']], target) <= half_width]
        if len(pool) < 3:
            pool = sorted(({**item, 'selectionAngle': angles[item['index']],
                            'angleError': circular_distance(angles[item['index']], target)}
                           for item in catalog), key=lambda item: (item['angleError'], item['index']))[:3]
        windows.append({'slot': slot, 'targetAngle': target, 'viewType': view_type,
                        'halfWindow': half_width, 'candidates': pool})
    return windows, method


def _quick_metrics(data):
    raw = analyze_image_quality(data)
    return {'quickSharpness': _focus_score(raw['sharpness']),
            'quickExposure': _clamp(1.-abs(raw['brightness']-128.)/110.),
            'quickClipping': _clamp(1.-(raw['black_clip_ratio']+raw['white_clip_ratio'])/.24)}


def _proxy_shortlist(window, quick, limit=MAX_PROXY_CANDIDATES):
    """Retain angular diversity so the exact target cannot dominate."""
    target, half_width = window['targetAngle'], window['halfWindow']
    ranked = []
    for item in window['candidates']:
        q = quick.get(item['index'])
        if q is None:
            continue
        preliminary = (.52*q['quickSharpness']+.16*q['quickExposure']
                       +.12*q['quickClipping']+.20*(1.-item['angleError']/max(half_width, 1.)))
        ranked.append({**item, 'preliminaryScore': preliminary})
    ranked.sort(key=lambda item: (-item['preliminaryScore'], item['angleError'], item['index']))
    if not ranked:
        return []
    selected = [ranked[0]]
    nearest = min(ranked, key=lambda item: (item['angleError'], item['index']))
    if nearest['index'] != selected[0]['index']:
        selected.append(nearest)
    # Best frames in three angular subwindows, including alternatives on
    # both sides of the target when the camera speed was not uniform.
    for lower, upper in ((-half_width, -half_width/3.),
                         (-half_width/3., half_width/3.),
                         (half_width/3., half_width)):
        sector = [item for item in ranked
                  if lower <= ((item['selectionAngle']-target+180.) % 360.-180.) <= upper]
        if sector and all(item['index'] != sector[0]['index'] for item in selected):
            selected.append(sector[0])
    for item in ranked:
        if len(selected) >= limit:
            break
        if all(other['index'] != item['index'] for other in selected):
            selected.append(item)
    return selected[:limit]


def _upper_width_ratio(binary, bbox):
    x0, y0, x1, y1 = bbox
    height = y1-y0
    def span(start, end):
        lengths = []
        for y in range(y0+round(height*start), min(y1, y0+round(height*end))):
            xs = np.flatnonzero(binary[y])
            if xs.size:
                lengths.append(xs[-1]-xs[0]+1)
        return float(np.median(lengths)) if lengths else 0.
    upper, middle = span(.18, .34), span(.45, .65)
    return upper/max(middle, 1.)


def _mask_proxy(data, predict_mask):
    with Image.open(io.BytesIO(data)) as source:
        image = ImageOps.exif_transpose(source).convert('RGB')
        original_size = image.size
        image.thumbnail((PROXY_SIDE, PROXY_SIDE), Image.Resampling.LANCZOS)
        image = image.copy()
    raw = predict_mask(image).convert('L')
    if raw.size != image.size:
        raw = raw.resize(image.size, Image.Resampling.LANCZOS)
    alpha = preserve_connected_soft_alpha(np.asarray(raw, np.float32)/255.)
    return image, alpha, original_size


def _image_proxy_scores(data, predict_mask, target_type):
    """Relative image geometry scores; no claim of physical pitch/height."""
    image, soft_alpha, original_size = _mask_proxy(data, predict_mask)
    alpha = np.rint(soft_alpha*255.).astype(np.uint8)
    profile = mask_profile(alpha)
    if profile['empty']:
        return None
    bbox = profile['bbox']
    x0, y0, x1, y1 = bbox
    width, height = x1-x0, y1-y0
    if width < image.width*.12 or height < image.height*.12:
        return None
    solid = cv2.erode((alpha >= 180).astype(np.uint8), np.ones((3, 3), np.uint8)) > 0
    if solid.sum() < 250:
        return None
    rgb = np.asarray(image)
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    focus_raw = float(cv2.Laplacian(gray, cv2.CV_32F)[solid].var())
    sharpness = _focus_score(focus_raw)
    pixels = gray[solid]
    luminance = float(np.median(pixels))
    clipped = float(np.mean((pixels <= 7) | (pixels >= 248)))
    exposure = _clamp(1.-abs(luminance-130.)/115.-clipped*1.7)
    blur_risk = _clamp((.46-sharpness)/.36)
    binary = alpha >= 28
    margins = [x0/image.width, (image.width-x1)/image.width,
               y0/image.height, (image.height-y1)/image.height]
    edge_risk = max(_clamp((.045-margins[0])/.045),
                    _clamp((.045-margins[1])/.045),
                    _clamp((.06-margins[2])/.06),
                    _clamp((.03-margins[3])/.03))
    framing = _clamp(1.-.75*edge_risk-.4*profile['centerDistance'])
    segmentation = _clamp(1.-.20*profile['edgeCount']
                           -.9*max(0., profile['coverage']-.60))
    vehicle_width_ratio = width/image.width
    vehicle_size = _clamp(1.-abs(vehicle_width_ratio-.72)/.50)
    source_vehicle_width = width*original_size[0]/image.width
    resolution = _clamp(source_vehicle_width/1700.)
    rgba = image.convert('RGBA')
    rgba.putalpha(Image.fromarray(alpha, 'L'))
    pose = analyze_photo_pose(rgba.crop(bbox))
    contacts = pose['tireContacts']
    contact_spread = (abs(contacts[-1]['y']-contacts[0]['y'])/height
                      if len(contacts) >= 2 else None)
    near_radius = max((item['radius'] for item in contacts), default=None)
    wheel_ratio = (max(item['radius'] for item in contacts)/
                   max(1., min(item['radius'] for item in contacts))
                   if len(contacts) >= 2 else None)
    measured_type = pose['viewType']
    if target_type == 'side':
        depth_limit, depth_range, wheel_limit, wheel_range = .035, .16, 1.25, .70
    elif target_type == 'front-rear':
        depth_limit, depth_range, wheel_limit, wheel_range = .03, .16, 1.40, .70
    else:
        depth_limit, depth_range, wheel_limit, wheel_range = .12, .28, 1.65, .90
    depth_risk = (_clamp((contact_spread-depth_limit)/depth_range)
                  if contact_spread is not None else .28)
    wheel_risk = (_clamp((wheel_ratio-wheel_limit)/wheel_range)
                  if wheel_ratio is not None else .25)
    upper_ratio = _upper_width_ratio(binary, bbox)
    upper_risk = (_clamp((upper_ratio-.72)/.28)
                  if target_type == 'three-quarter' else 0.)
    small_wheel_risk = (_clamp((.085-near_radius/height)/.085)
                        if near_radius is not None else .25)
    viewpoint = _clamp(1.-.46*depth_risk-.27*upper_risk-.17*small_wheel_risk
                       -.10*(measured_type != target_type))
    perspective = _clamp(1.-.68*wheel_risk-.32*depth_risk)
    return {'sharpness': sharpness, 'exposure': exposure,
            'segmentation': segmentation, 'viewpoint': viewpoint,
            'perspective': perspective, 'framing': framing,
            'resolution': resolution, 'vehicleSize': vehicle_size,
            'blurRisk': blur_risk, 'clippingRisk': edge_risk,
            'apparentPitchQuality': _clamp(1.-.7*depth_risk-.3*upper_risk),
            'upperSurfaceRatio': round(upper_ratio, 3),
            'contactSpreadRatio': (round(contact_spread, 3) if contact_spread is not None else None),
            'wheelSizeRatio': (round(wheel_ratio, 3) if wheel_ratio is not None else None),
            'measuredViewType': measured_type,
            'sourceVehicleWidthPx': round(source_vehicle_width),
            'sourceSize': list(original_size), 'proxyBbox': list(bbox),
            'tireContactCount': len(contacts)}


def _pose_quality(pose, orbit_stats):
    if not pose:
        return None
    pieces = []
    if pose.get('relativeElevationDegrees') is not None:
        elevation = float(pose['relativeElevationDegrees'])
        median = orbit_stats.get('medianElevation', 0.)
        deviation = (max(0., elevation-median-2.) if pose.get('gravityAligned')
                     else max(0., abs(elevation-median)-2.))
        pieces.append(_clamp(1.-deviation/14.))
    if pose.get('pitchDegrees') is not None and pose.get('gravityAligned'):
        pieces.append(_clamp(1.-max(0., abs(float(pose['pitchDegrees']))-6.)/14.))
    if pose.get('relativeDistance') is not None:
        distance = float(pose['relativeDistance'])
        median = max(orbit_stats.get('medianDistance', distance), 1e-6)
        pieces.append(_clamp(.75+.25*(distance/median-1.)/.25))
    return float(np.mean(pieces)) if pieces else None


def weighted_candidate_score(components, angle_error, window, weights=WEIGHTS):
    """Explicit 0–1 component mix; target proximity has only 10% weight."""
    angle = _clamp(1.-float(angle_error)/max(float(window), 1.))
    values = {name: _clamp(components.get(name, .5)) for name in weights}
    values['angle'] = angle
    total = sum(weights[name]*values[name] for name in weights)
    total -= .055*_clamp(components.get('blurRisk', 0.))
    total -= .09*_clamp(components.get('clippingRisk', 0.))
    total += .025*(_clamp(components.get('vehicleSize', .5))-.5)
    return round(_clamp(total), 4), values


def _pick_jointly(windows, scored, catalog):
    """Beam search enforces circular source spacing across all ten photos."""
    rank = {item['index']: position for position, item in enumerate(catalog)}
    count = len(catalog)
    minimum = max(2, round(count*.055))
    beams = [(0., [])]
    for window in windows:
        options = sorted(scored[window['slot']], key=lambda item: (-item['totalScore'],
                                                               item['angleError'], item['index']))
        if not options:
            raise ValueError(f"No usable studio candidate for target {window['targetAngle']}")
        advanced = []
        for total, chosen in beams:
            for item in options:
                position = rank[item['index']]
                if any(min(abs(position-rank[prior['index']]),
                           count-abs(position-rank[prior['index']])) < minimum for prior in chosen):
                    continue
                advanced.append((total+item['totalScore'], chosen+[item]))
        if not advanced:
            raise ValueError('Cannot select ten sufficiently separated candidate views')
        advanced.sort(key=lambda state: (-state[0],
                                         tuple(item['index'] for item in state[1])))
        beams = advanced[:96]
    return beams[0][1]


def selection_contact_sheet(windows, scored, chosen, source_bytes):
    """Review sheet: each target's top candidate thumbnails and score."""
    tile_w, tile_h, columns = 280, 205, 5
    sheet = Image.new('RGB', (tile_w*columns, tile_h*len(windows)), (245, 246, 246))
    draw = ImageDraw.Draw(sheet)
    chosen_by_slot = {item['slot']: item['index'] for item in chosen}
    for window in windows:
        row = window['slot']
        choices = sorted(scored[row], key=lambda item: (-item['totalScore'],
                                                        item['angleError'], item['index']))[:columns]
        for column, item in enumerate(choices):
            left, top = column*tile_w, row*tile_h
            try:
                with Image.open(io.BytesIO(source_bytes[item['index']])) as original:
                    thumb = ImageOps.fit(original.convert('RGB'), (tile_w-12, 148),
                                         Image.Resampling.LANCZOS)
                sheet.paste(thumb, (left+6, top+6))
            except Exception:
                pass
            selected = item['index'] == chosen_by_slot[row]
            draw.rectangle((left+2, top+2, left+tile_w-3, top+tile_h-3),
                           outline=(35, 150, 70) if selected else (170, 175, 175), width=4 if selected else 1)
            draw.text((left+8, top+157), f"{window['targetAngle']:.0f}°  frame {item['index']}  "
                      f"err {item['angleError']:.1f}°", fill=(20, 30, 30))
            draw.text((left+8, top+177), f"total {item['totalScore']:.2f}  view "
                      f"{item['components']['viewpoint']:.2f}  sharp "
                      f"{item['components']['sharpness']:.2f}", fill=(20, 30, 30))
    output = io.BytesIO()
    sheet.save(output, 'JPEG', quality=90)
    return output.getvalue()


def select_studio_source_views(catalog, read_candidate, predict_mask,
                               target_types=None, camera_metadata=None,
                               window_degrees=WINDOW_DEGREES,
                               hero_window_degrees=HERO_WINDOW_DEGREES):
    """Rank original frames, then jointly select ten for the photo export.

    `camera_metadata` may be stored COLMAP images.txt or camera-pose JSON.
    Future gyro/lens/still metadata can be added through the same per-frame
    dictionary without changing the capture or viewer pipeline.
    """
    catalog = sorted(catalog, key=lambda item: item['index'])
    try:
        poses = parse_camera_pose_metadata(camera_metadata) if camera_metadata else {}
    except (ValueError, TypeError):
        poses = {}  # Broken optional metadata must not prevent image fallback.
    windows, method = generate_target_windows(catalog, poses, target_types,
                                               window_degrees, hero_window_degrees)
    source_bytes = {}
    quick = {}
    for item in catalog:
        try:
            data = read_candidate(item['key'])
            source_bytes[item['index']] = data
            quick[item['index']] = _quick_metrics(data)
        except Exception:
            continue
    shortlists = {window['slot']: _proxy_shortlist(window, quick) for window in windows}
    detailed = {}
    to_measure = {item['index'] for pool in shortlists.values() for item in pool}
    elevation_values = [item['relativeElevationDegrees'] for item in poses.values()
                        if item.get('relativeElevationDegrees') is not None]
    distance_values = [item['relativeDistance'] for item in poses.values()
                       if item.get('relativeDistance') is not None]
    orbit_stats = {'medianElevation': float(np.median(elevation_values)) if elevation_values else 0.,
                   'medianDistance': float(np.median(distance_values)) if distance_values else 1.}
    # A single model call per unique shortlisted frame, not one per target.
    for index in sorted(to_measure):
        try:
            # Geometry is target-dependent only in its scoring tolerances;
            # cache the model matte and analyse for each requested type below.
            image, alpha, original_size = _mask_proxy(source_bytes[index], predict_mask)
            detailed[index] = (image, alpha, original_size)
        except Exception:
            continue
    scored = defaultdict(list)
    for window in windows:
        for item in shortlists[window['slot']]:
            try:
                # Reuse the one proxy mask; no extra neural inference here.
                image, alpha, original_size = detailed[item['index']]
                metrics = _scores_from_cached_proxy(image, alpha, original_size,
                                                    window['viewType'])
                if metrics is None:
                    continue
                pose_q = _pose_quality(poses.get(item['index']), orbit_stats)
                if pose_q is not None:
                    metrics['viewpoint'] = .65*metrics['viewpoint']+.35*pose_q
                    metrics['poseQuality'] = round(pose_q, 3)
                total, components = weighted_candidate_score(metrics, item['angleError'],
                                                             window['halfWindow'])
                scored[window['slot']].append({**item, 'slot': window['slot'],
                                               'totalScore': total, 'components': components,
                                               'measurements': {key: value for key, value in metrics.items()
                                                                if key not in components},
                                               'selectionMethod': method})
            except (KeyError, ValueError):
                continue
    chosen = _pick_jointly(windows, scored, catalog)
    for item in chosen:
        item['targetAngle'] = windows[item['slot']]['targetAngle']
        item['angleSource'] = method
        item['quality'] = round(item['totalScore']*100., 2)
        score = item['totalScore']
        item['selectionConfidence'] = ('high' if score >= .72 and item['angleError'] <= 12.
                                       else 'medium' if score >= .56 else 'low')
    diagnostics = {'selectionMethod': method, 'weights': WEIGHTS,
                   'proxyFramesMeasured': len(detailed), 'candidateFrames': len(catalog),
                   'targets': [{**{key: window[key] for key in ('slot', 'targetAngle', 'viewType', 'halfWindow')},
                                'selectedFrame': chosen[window['slot']]['index'],
                                'topCandidates': sorted(scored[window['slot']],
                                                        key=lambda item: -item['totalScore'])[:5]}
                               for window in windows]}
    sheet = selection_contact_sheet(windows, scored, chosen, source_bytes)
    return chosen, diagnostics, sheet


def _scores_from_cached_proxy(image, alpha, original_size, target_type):
    """Analyse a cached proxy matte without invoking the model again."""
    # The model prediction is cached. Re-encoding only supplies the existing
    # image-analysis entry point; it does not invoke BiRefNet a second time.
    mask = Image.fromarray(np.rint(alpha*255.).astype(np.uint8), 'L')
    buffer = io.BytesIO()
    image.save(buffer, 'JPEG', quality=95)
    result = _image_proxy_scores(buffer.getvalue(), lambda _: mask, target_type)
    if result is not None:
        result['sourceSize'] = list(original_size)
        result['sourceVehicleWidthPx'] = round(
            result['sourceVehicleWidthPx']*original_size[0]/image.width)
        result['resolution'] = _clamp(result['sourceVehicleWidthPx']/1700.)
    return result
