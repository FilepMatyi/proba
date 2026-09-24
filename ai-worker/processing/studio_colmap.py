"""Optional camera-pose adapter for the independent Studio Photos selector.

COLMAP's world frame has arbitrary rotation and scale.  Values derived from
images.txt are therefore *relative orbit proxies*, not physical camera height
or gravity-referenced pitch.  The photo export works without this file.
"""
import json
import math
import re

import numpy as np


FRAME_NAME = re.compile(r'(?:frame[-_])?(\d+)\.(?:jpe?g|png)$', re.IGNORECASE)


def _unit(vector):
    length = float(np.linalg.norm(vector))
    return vector / length if length > 1e-8 else vector


def _rotation_from_quaternion(qw, qx, qy, qz):
    q = _unit(np.array((qw, qx, qy, qz), dtype=np.float64))
    w, x, y, z = q
    return np.array([
        [1-2*(y*y+z*z), 2*(x*y-z*w), 2*(x*z+y*w)],
        [2*(x*y+z*w), 1-2*(x*x+z*z), 2*(y*z-x*w)],
        [2*(x*z-y*w), 2*(y*z+x*w), 1-2*(x*x+y*y)],
    ], dtype=np.float64)


def parse_colmap_images_text(data):
    """Map COLMAP images.txt camera centres to relative azimuth and elevation.

    At least six registered orbit views are needed for a useful plane fit.
    No absolute camera pitch/height is reported without gravity calibration.
    """
    text = data.decode('utf-8') if isinstance(data, bytes) else str(data)
    lines = [line.strip() for line in text.splitlines() if line.strip() and not line.lstrip().startswith('#')]
    centers = {}
    for header in lines:
        parts = header.split()
        if len(parts) < 10:
            continue
        match = FRAME_NAME.search(parts[9])
        if not match:
            continue
        try:
            rotation = _rotation_from_quaternion(*map(float, parts[1:5]))
            translation = np.array(list(map(float, parts[5:8])), dtype=np.float64)
            centers[int(match.group(1))] = -rotation.T @ translation
        except (ValueError, OverflowError):
            continue
    if len(centers) < 6:
        return {}
    indexes = sorted(centers)
    positions = np.stack([centers[index] for index in indexes])
    centre = np.median(positions, axis=0)
    centered = positions-centre
    _, _, basis = np.linalg.svd(centered, full_matrices=False)
    normal = _unit(basis[2])
    first_radial = centered[0] - np.dot(centered[0], normal)*normal
    first_radial = _unit(first_radial)
    if np.linalg.norm(first_radial) < 1e-8:
        return {}
    tangent = _unit(np.cross(normal, first_radial))
    raw = np.array([math.atan2(float(np.dot(point, tangent)),
                               float(np.dot(point, first_radial))) for point in centered])
    unwrapped = np.unwrap(raw)
    direction = 1. if np.median(np.diff(unwrapped)) >= 0 else -1.
    angles = np.degrees((unwrapped-unwrapped[0])*direction)
    if angles[-1] < 240. or angles[-1] > 480.:
        return {}  # Not a sufficiently complete orbit.
    result = {}
    for index, point, angle in zip(indexes, centered, angles):
        planar = point-np.dot(point, normal)*normal
        result[index] = {
            'azimuthDegrees': float(angle % 360.),
            'relativeElevationDegrees': math.degrees(math.atan2(
                float(np.dot(point, normal)), max(float(np.linalg.norm(planar)), 1e-8))),
            'relativeDistance': float(np.linalg.norm(point)),
            'poseSource': 'COLMAP',
        }
    return result


def parse_camera_pose_metadata(data):
    """Accept stored COLMAP text or a future explicit camera-pose JSON file."""
    text = data.decode('utf-8') if isinstance(data, bytes) else str(data)
    if not text.lstrip().startswith(('{', '[')):
        return parse_colmap_images_text(text)
    payload = json.loads(text)
    frames = payload.get('frames', []) if isinstance(payload, dict) else payload
    result = {}
    for frame in frames:
        try:
            index = int(frame.get('sourceFrame', frame.get('frame')))
            angle = float(frame['azimuthDegrees'])
            if index < 1 or not math.isfinite(angle):
                continue
            item = {'azimuthDegrees': angle % 360., 'poseSource': 'COLMAP'}
            for source, target in (('relativeElevationDegrees', 'relativeElevationDegrees'),
                                   ('elevationDegrees', 'relativeElevationDegrees'),
                                   ('relativeDistance', 'relativeDistance'),
                                   ('distance', 'relativeDistance'),
                                   ('pitchDegrees', 'pitchDegrees')):
                if frame.get(source) is not None and math.isfinite(float(frame[source])):
                    item[target] = float(frame[source])
            item['gravityAligned'] = bool(frame.get('gravityAligned', False))
            result[index] = item
        except (TypeError, ValueError, KeyError):
            continue
    return result
