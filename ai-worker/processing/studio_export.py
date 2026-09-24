"""Quality-aware 10-view, 4K export from the normalized viewer cutouts."""
import io
import json
import math
import zipfile
from datetime import datetime, timezone

import cv2
import numpy as np
from PIL import Image

from processing.studio_compose import create_studio_image, robust_ground_anchor
from processing.target_lock import mask_profile

EXPORT_COUNT = 10
EXPORT_SIZE = (3840, 2160)


def select_studio_indices(frame_count, count=EXPORT_COUNT):
    """One stable sample per equally spaced circular sector, 1-based."""
    if frame_count < count or count < 1:
        raise ValueError('Not enough frames for the requested circular export')
    return [1 + (slot*frame_count)//count for slot in range(count)]


def cutout_quality(image):
    """Foreground focus and mask QA, without crisp background bias."""
    proxy = image.copy()
    proxy.thumbnail((768, 768), Image.Resampling.LANCZOS)
    alpha = np.asarray(proxy.getchannel('A'))
    profile = mask_profile(alpha)
    if profile['empty'] or robust_ground_anchor(alpha) is None:
        return None
    rgb = np.asarray(proxy.convert('RGB'))
    grey = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    solid = cv2.erode((alpha >= 220).astype(np.uint8), np.ones((5, 5), np.uint8)) > 0
    if solid.sum() < 100:
        return None
    edge_response = cv2.Laplacian(grey, cv2.CV_32F)
    focus = min(1., math.log1p(float(edge_response[solid].var())) / math.log1p(500.))
    foreground = grey[solid]
    brightness = 1. - min(1., abs(float(np.median(foreground))-128.) / 128.)
    clipping = 1. - min(1., float(np.mean((foreground <= 5) | (foreground >= 250))) / .24)
    framing = max(0., 1. - profile['edgeCount'] * .18 - max(0., profile['coverage']-.62) * 2.)
    return round(100. * (.58*focus + .13*brightness + .15*clipping + .14*framing), 2)


def _circular_distance(a, b):
    difference = abs((a-b) % 360.)
    return min(difference, 360.-difference)


def select_quality_views(candidates, count=EXPORT_COUNT, orbit_frames=None):
    """Pick one strong, unique image near each target angle around the seam.

    True capture azimuth is used when present on every candidate. Otherwise
    ordered viewer-frame position is the explicit, approximate fallback.
    """
    if len(candidates) < count:
        raise ValueError('Not enough usable masks for a circular studio export')
    ordered = sorted(candidates, key=lambda item: item['index'])
    indexes = {item['index'] for item in ordered}
    if len(indexes) != len(ordered):
        raise ValueError('Duplicate source-frame index')
    frame_count = orbit_frames or max(indexes)
    try:
        sensor_angles = all(item.get('angle') is not None and math.isfinite(float(item['angle']))
                            for item in ordered)
        sensor_angles = sensor_angles and max(float(item['angle']) for item in ordered) - min(
            float(item['angle']) for item in ordered) >= 270.
    except (TypeError, ValueError):
        sensor_angles = False
    angle_source = 'sensor' if sensor_angles else 'ordered-frames'
    views = []
    for item in ordered:
        angle = float(item['angle']) % 360. if sensor_angles else 360.*(item['index']-1)/frame_count
        views.append({**item, 'selectionAngle': angle})
    selected = []
    used = set()
    for slot in range(count):
        target = 360.*slot/count
        available = [item for item in views if item['index'] not in used]
        sector = [item for item in available if _circular_distance(item['selectionAngle'], target) <= 180./count]
        pool = sector or available
        chosen = max(pool, key=lambda item: (
            float(item['quality']) - .35*_circular_distance(item['selectionAngle'], target),
            -_circular_distance(item['selectionAngle'], target), -item['index']))
        selected.append({**chosen, 'targetAngle': target, 'angleSource': angle_source})
        used.add(chosen['index'])
    return selected


def export_studio_photos(vehicle_id, read_mask, read_layout, save_object, progress=None,
                         frame_count=36, read_selection=None):
    """Generate separate JPEGs, a manifest and a downloadable ZIP.

    Storage callbacks make this testable without Redis, MinIO or the AI model.
    Each frame is decoded, rendered and released before the next one.
    """
    selection = read_selection() if read_selection else {}
    selected_metadata = {item['viewerFrame']: item for item in selection.get('views', [])}
    candidates = []
    for index in range(1, frame_count+1):
        try:
            with_image = read_mask(index).convert('RGBA')
            mask_score = cutout_quality(with_image)
        except (OSError, ValueError):
            continue
        if mask_score is None:
            continue
        metadata = selected_metadata.get(index, {})
        source_score = metadata.get('qualityScore')
        quality = mask_score if source_score is None else .50*mask_score + .50*float(source_score)
        quality -= min(12., float(metadata.get('poseDeviation', 0.))* .35)
        candidates.append({'index': index, 'quality': round(quality, 2),
                           'angle': metadata.get('azimuthDegrees')})
    chosen_views = select_quality_views(candidates, orbit_frames=frame_count)
    usable_indexes = {item['index'] for item in candidates}
    uniform_indexes = select_studio_indices(frame_count)
    entries = []
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, 'w', compression=zipfile.ZIP_STORED) as bundle:
        for number, view in enumerate(chosen_views, 1):
            source_index = view['index']
            source = read_mask(source_index).convert('RGBA')
            layout = read_layout(source_index) or {}
            studio = create_studio_image(source, target_height_ratio=layout.get('targetHeightRatio'),
                                         canvas_size=EXPORT_SIZE, style='photo')
            output = io.BytesIO()
            studio.save(output, 'JPEG', quality=96, subsampling=0, optimize=True)
            data = output.getvalue()
            filename = f'{number:02d}.jpg'
            key = f'{vehicle_id}/studio-photos/{filename}'
            save_object(key, data, 'image/jpeg')
            bundle.writestr(filename, data)
            entries.append({'number': number, 'sourceFrame': source_index,
                            'degrees': round(view['targetAngle'], 1),
                            'selectionAngle': round(view['selectionAngle'], 2),
                            'angleSource': view['angleSource'],
                            'qualityScore': view['quality'],
                            'file': filename, 'width': EXPORT_SIZE[0], 'height': EXPORT_SIZE[1],
                            'selectionAdjusted': source_index != uniform_indexes[number-1],
                            'fallbackUsed': uniform_indexes[number-1] not in usable_indexes})
            if progress:
                progress(number)
    manifest = {'vehicleId': vehicle_id, 'kind': 'studio-photos',
                'generatedAt': datetime.now(timezone.utc).isoformat(), 'count': len(entries),
                'size': list(EXPORT_SIZE), 'photos': entries}
    save_object(f'{vehicle_id}/studio-photos/album.zip', archive.getvalue(), 'application/zip')
    save_object(f'{vehicle_id}/studio-photos/manifest.json',
                json.dumps(manifest, ensure_ascii=False).encode('utf-8'), 'application/json')
    return manifest
