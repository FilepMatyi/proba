"""Conservative, photo-only canonical stance measurements.

Image-space wheel slope is normally perspective, not roll.  Rotation is
permitted only for almost orthographic side or front/rear views when an
independent long body line agrees with the tire line.  Everything else uses
translation to a tire-derived contact level; no perspective warp is applied.
"""
import math

import cv2
import numpy as np
from PIL import Image

from processing.ground_contacts import silhouette_contacts, tire_contacts
from processing.studio_compose import robust_ground_anchor


def reliable_tire_contacts(image):
    """Reject narrow bumper/trim lobes occasionally classified as tires."""
    height = image.height
    return [item for item in tire_contacts(image)
            if item['prominence'] >= max(7., height*.012)
            and item['radius'] >= height*.04
            and item['y'] >= height*.62]


def _body_line_angles(image):
    """Long interior near-horizontal lines, excluding silhouette and tires."""
    rgba = np.asarray(image.convert('RGBA'))
    height, width = rgba.shape[:2]
    factor = min(1., 960./max(height, width))
    if factor < 1.:
        rgba = cv2.resize(rgba, None, fx=factor, fy=factor, interpolation=cv2.INTER_AREA)
    height, width = rgba.shape[:2]
    gray = cv2.cvtColor(rgba[:, :, :3], cv2.COLOR_RGB2GRAY)
    alpha = rgba[:, :, 3]
    valid = cv2.erode((alpha >= 180).astype(np.uint8),
                      cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7)))
    valid[:round(height*.18)] = 0
    valid[round(height*.82):] = 0
    edges = cv2.Canny(gray, 55, 145) * valid
    lines = cv2.HoughLinesP(edges, 1, np.pi/360, threshold=max(25, round(width*.065)),
                            minLineLength=max(25, round(width*.14)),
                            maxLineGap=max(5, round(width*.02)))
    if lines is None:
        return []
    measured = []
    for x1, y1, x2, y2 in lines[:, 0]:
        dx, dy = int(x2)-int(x1), int(y2)-int(y1)
        if dx == 0:
            continue
        angle = math.degrees(math.atan2(dy, dx))
        if abs(angle) <= 6.:
            measured.append((angle, math.hypot(dx, dy)))
    return measured


def _weighted_median(values):
    ordered = sorted(values)
    total = sum(weight for _, weight in ordered)
    through = 0.
    for value, weight in ordered:
        through += weight
        if through >= total/2.:
            return float(value)
    return None


def conservative_roll_correction(view_type, wheel_angle, body_angle):
    """A small rotation only when independent cues agree in an axial view."""
    if view_type not in ('side', 'front-rear') or wheel_angle is None or body_angle is None:
        return 0.
    if abs(wheel_angle) > 5. or abs(body_angle) > 3. or abs(wheel_angle-body_angle) > 2.5:
        return 0.
    # PIL's positive rotation moves points on the right upward in image
    # coordinates, so it subtracts this positive measured line slope.
    correction = float(np.clip(.55*body_angle+.45*wheel_angle, -2., 2.))
    return correction if abs(correction) >= .35 else 0.


def photo_placement(image_size, anchor_y, canvas_size):
    """Fixed photo-only studio template, independent of viewer layout hints."""
    width, height = image_size
    canvas_w, canvas_h = canvas_size
    scale = min(canvas_h*.686/max(height, 1), canvas_w*.90/max(width, 1))
    scaled_w, scaled_h = max(1, round(width*scale)), max(1, round(height*scale))
    ground_y = round(canvas_h*.8722)
    x = (canvas_w-scaled_w)//2
    y = ground_y-round(float(anchor_y)*scaled_h/max(height, 1))
    return (scaled_w, scaled_h), (x, y), ground_y


def analyze_photo_pose(image):
    """Return explicit tire/stance diagnostics and a small justified roll.

    A nearest visible tire is the image-space contact anchor.  Far tires can
    appear higher on the same floor in a 3/4 perspective and are not leveled
    to the near tire.  Isolated low hardware is not a contact candidate.
    """
    if image.mode != 'RGBA':
        image = image.convert('RGBA')
    alpha = np.asarray(image.getchannel('A'))
    tires = reliable_tire_contacts(image)
    fallback = silhouette_contacts(alpha)
    supported = robust_ground_anchor(alpha)
    aspect = image.width/max(1, image.height)
    kind = 'three-quarter'
    wheel_slope = None
    if len(tires) >= 2:
        left, right = sorted(tires, key=lambda item: item['x'])[:2]
        wheel_slope = math.degrees(math.atan2(right['y']-left['y'], right['x']-left['x']))
        separation = (right['x']-left['x'])/image.width
        radius_ratio = max(left['radius'], right['radius'])/max(1., min(left['radius'], right['radius']))
        if aspect >= 1.8 and separation >= .45 and radius_ratio <= 1.35 and abs(wheel_slope) <= 5.:
            kind = 'side'
        elif aspect <= 1.4 and separation >= .20 and abs(right['y']-left['y']) <= image.height*.07:
            kind = 'front-rear'
    line_angles = _body_line_angles(image)
    body_angle = _weighted_median(line_angles) if len(line_angles) >= 2 else None
    correction = conservative_roll_correction(kind, wheel_slope, body_angle)
    reason = ('corroborated-body-and-tire-lines' if correction
              else 'perspective-or-insufficient-evidence')
    if tires:
        if kind == 'front-rear' and len(tires) >= 2:
            anchor = float(np.median([item['y'] for item in tires]))
        else:
            anchor = max(item['y'] for item in tires)
        anchor_source = 'tires'
    elif fallback:
        # Silhouette-only contact is less certain, but keeps a valid cutout
        # usable when tire material is occluded or underexposed.
        anchor = max(item['y'] for item in fallback)
        anchor_source = 'silhouette-fallback'
    else:
        anchor = supported
        anchor_source = 'supported-mask-fallback' if supported is not None else 'empty'
    return {'viewType': kind, 'tireContacts': tires, 'silhouetteContacts': fallback,
            'groundAnchorY': anchor, 'groundAnchorSource': anchor_source,
            'supportedMaskAnchorY': supported, 'wheelLineDegrees': wheel_slope,
            'bodyLineDegrees': body_angle, 'bodyLineCount': len(line_angles),
            'rollCorrectionDegrees': correction, 'rollReason': reason,
            'pitchCorrectionDegrees': 0., 'pitchReason': 'not-observable-from-single-2d-view'}


def normalize_photo_pose(image):
    """Rotate only when independently justified, then recompute tire anchor."""
    plan = analyze_photo_pose(image)
    correction = plan['rollCorrectionDegrees']
    if correction:
        # PIL uses positive degrees counter-clockwise in image coordinates.
        image = image.rotate(correction, resample=Image.Resampling.BICUBIC, expand=True)
        updated = analyze_photo_pose(image)
        updated['appliedRollDegrees'] = correction
        updated['rollBeforeDegrees'] = plan['wheelLineDegrees']
        return image, updated
    plan['appliedRollDegrees'] = 0.
    plan['rollBeforeDegrees'] = plan['wheelLineDegrees']
    return image, plan
