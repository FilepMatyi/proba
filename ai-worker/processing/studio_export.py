"""Quality-aware 10-view, 4K export with optional original-frame detail masks."""
import io
import json
import math
import zipfile
from datetime import datetime, timezone

import cv2
import numpy as np
from PIL import Image

from processing.exposure_normalize import apply_exposure_plan, measure_exposure
from processing.studio_compose import create_studio_image, robust_ground_anchor
from processing.studio_detail import segment_studio_source
from processing.studio_selection import (HERO_WINDOW_DEGREES, WINDOW_DEGREES,
                                         classify_target_view, select_studio_source_views)
from processing.target_lock import mask_profile

EXPORT_COUNT = 10
EXPORT_SIZE = (3840, 2160)


def _match_stored_exposure(detailed, normalized_reference):
    """Carry the session's gentle exposure target onto a resegmented source.

    The old cutout and new matte represent the same view.  Luminance-only,
    tightly bounded correction avoids shifting the vehicle's paint hue.
    """
    source_stats = measure_exposure(detailed)
    target_stats = measure_exposure(normalized_reference)
    if not source_stats or not target_stats:
        return detailed
    mean, deviation = source_stats
    target_mean, target_deviation = target_stats
    return apply_exposure_plan(detailed, {
        'sourceMean': mean,
        'meanShift': float(np.clip(target_mean-mean, -8., 8.)),
        'contrastGain': float(np.clip(target_deviation/max(deviation, 1.), .95, 1.05)),
    })


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
                         frame_count=36, read_selection=None, read_source=None,
                         predict_mask=None, candidate_catalog=None,
                         read_candidate=None, camera_metadata=None,
                         window_degrees=WINDOW_DEGREES,
                         hero_window_degrees=HERO_WINDOW_DEGREES):
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
    selection_method = chosen_views[0]['angleSource']
    selection_diagnostics = None
    if candidate_catalog and read_candidate and predict_mask:
        try:
            target_types = [classify_target_view(read_mask(index).convert('RGBA'))
                            for index in select_studio_indices(frame_count)]
            chosen_views, selection_diagnostics, contact_sheet = select_studio_source_views(
                candidate_catalog, read_candidate, predict_mask,
                target_types=target_types, camera_metadata=camera_metadata,
                window_degrees=window_degrees,
                hero_window_degrees=hero_window_degrees)
            selection_method = selection_diagnostics['selectionMethod']
            save_object(f'{vehicle_id}/studio-photos/selection-debug.json',
                        json.dumps(selection_diagnostics, ensure_ascii=False).encode('utf-8'),
                        'application/json')
            save_object(f'{vehicle_id}/studio-photos/selection-contact-sheet.jpg',
                        contact_sheet, 'image/jpeg')
        except (OSError, ValueError, RuntimeError) as error:
            # Older or incomplete captures retain the proven 36-mask export.
            selection_diagnostics = {'selectionFailure': str(error)[:200]}
    original_candidates = selection_method in ('COLMAP', 'sequence_fallback')
    source_mappings = [item for item in selection.get('views', [])
                       if isinstance(item.get('candidateFrame'), int)]
    usable_indexes = {item['index'] for item in candidates}
    uniform_indexes = select_studio_indices(frame_count)
    entries = []
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, 'w', compression=zipfile.ZIP_STORED) as bundle:
        for number, view in enumerate(chosen_views, 1):
            source_index = view['index']
            source_viewer_index = (min(source_mappings,
                                       key=lambda item: abs(item['candidateFrame']-source_index))['viewerFrame']
                                   if original_candidates and source_mappings else
                                   min(frame_count, max(1, round((source_index-.5)*frame_count/
                                                                  max(len(candidate_catalog or []), 1)+.5)))
                                   if original_candidates else source_index)
            source = read_mask(source_viewer_index).convert('RGBA')
            detail_metadata = {'sourceDetail': 'stored-mask'}
            if (original_candidates and read_candidate and predict_mask) or (read_source and predict_mask):
                try:
                    original_bytes = (read_candidate(view['key']) if original_candidates
                                      else read_source(source_index))
                    if original_bytes:
                        detailed, detail_metadata = segment_studio_source(
                            original_bytes, predict_mask)
                        if cutout_quality(detailed) is not None:
                            source = _match_stored_exposure(detailed, source)
                            detail_metadata['sourceDetail'] = 'original-frame-soft-matte'
                        else:
                            detail_metadata = {'sourceDetail': 'stored-mask',
                                               'sourceDetailFallback': 'empty detail matte'}
                except Exception as error:
                    detail_metadata = {'sourceDetail': 'stored-mask',
                                       'sourceDetailFallback': str(error)[:160]}
            # read_layout remains in the callback API for old jobs, but the
            # standalone photo template must not inherit viewer height jitter.
            studio, pose = create_studio_image(source, canvas_size=EXPORT_SIZE,
                                               style='photo', return_pose=True)
            output = io.BytesIO()
            studio.save(output, 'JPEG', quality=96, subsampling=0, optimize=True)
            data = output.getvalue()
            filename = f'{number:02d}.jpg'
            key = f'{vehicle_id}/studio-photos/{filename}'
            save_object(key, data, 'image/jpeg')
            bundle.writestr(filename, data)
            components = view.get('components', {})
            entries.append({'number': number, 'sourceFrame': source_index,
                            'sourceViewerFrame': source_viewer_index,
                            'sourceCandidateKey': view.get('key'),
                            'degrees': round(view['targetAngle'], 1),
                            'selectionAngle': round(view['selectionAngle'], 2),
                            'angleSource': view['angleSource'],
                            'qualityScore': view['quality'],
                            'selectionMethod': selection_method,
                            'angleError': round(view.get('angleError',
                                                       _circular_distance(view['selectionAngle'],
                                                                          view['targetAngle'])), 2),
                            'selectionConfidence': view.get('selectionConfidence', 'medium'),
                            'viewpointScore': round(components.get('viewpoint', .5), 3),
                            'sharpnessScore': round(components.get('sharpness', .5), 3),
                            'perspectiveScore': round(components.get('perspective', .5), 3),
                            'framingScore': round(components.get('framing', .5), 3),
                            'segmentationScore': round(components.get('segmentation', .5), 3),
                            'exposureScore': round(components.get('exposure', .5), 3),
                            'file': filename, 'width': EXPORT_SIZE[0], 'height': EXPORT_SIZE[1],
                            'selectionAdjusted': (source_index != uniform_indexes[number-1]
                                                  if not original_candidates else
                                                  source_index != 1+((number-1)*len(candidate_catalog))//EXPORT_COUNT),
                            'fallbackUsed': (uniform_indexes[number-1] not in usable_indexes
                                             if not original_candidates else
                                             detail_metadata['sourceDetail'] == 'stored-mask'),
                            'sourceDetail': detail_metadata['sourceDetail'],
                            'detailPassUsed': detail_metadata.get('detailPassUsed', False),
                            'sourceDetailFallback': detail_metadata.get('sourceDetailFallback'),
                            'stance': {
                                'viewType': pose['viewType'] if pose else 'empty',
                                'groundAnchorSource': pose['groundAnchorSource'] if pose else 'empty',
                                'appliedRollDegrees': round(pose['appliedRollDegrees'], 3) if pose else 0.,
                                'wheelLineDegrees': (round(pose['wheelLineDegrees'], 3)
                                                     if pose and pose['wheelLineDegrees'] is not None else None),
                                'bodyLineDegrees': (round(pose['bodyLineDegrees'], 3)
                                                    if pose and pose['bodyLineDegrees'] is not None else None),
                                'pitchCorrectionDegrees': 0.,
                                'canvas': pose.get('canvas') if pose else None,
                            }})
            if progress:
                progress(number)
    manifest = {'vehicleId': vehicle_id, 'kind': 'studio-photos',
                'selectionMethod': selection_method,
                'selectionDiagnostics': ('selection-debug.json' if original_candidates else
                                         selection_diagnostics),
                'generatedAt': datetime.now(timezone.utc).isoformat(), 'count': len(entries),
                'size': list(EXPORT_SIZE), 'photos': entries}
    save_object(f'{vehicle_id}/studio-photos/album.zip', archive.getvalue(), 'application/zip')
    save_object(f'{vehicle_id}/studio-photos/manifest.json',
                json.dumps(manifest, ensure_ascii=False).encode('utf-8'), 'application/json')
    return manifest
