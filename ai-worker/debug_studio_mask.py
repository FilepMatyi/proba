"""Save one reproducible Studio Photos mask trace from MinIO for visual QA.

Example: python debug_studio_mask.py --vehicle car-test-5-studio-photos-v3
  --source-vehicle car-test-5-premium-v2 --frame 12
"""
import argparse
import io
import json
from pathlib import Path

import cv2
import numpy as np
from PIL import Image
from rembg.bg import post_process

from processing.background_removal import _cleanup_mask, _session, _target_locked_retry
from processing.source_detail import attach_mask_to_source
from processing.stabilization import level_source_image
from processing.studio_compose import create_studio_image
from processing.studio_detail import segment_studio_source
from worker import PROCESSED_BUCKET, RAW_BUCKET, _download_bytes, minio_client


def _features(image, mask=None):
    image.thumbnail((1024, 1024), Image.Resampling.LANCZOS)
    grey = cv2.cvtColor(np.asarray(image.convert('RGB')), cv2.COLOR_RGB2GRAY)
    if mask is not None:
        mask = mask.resize(image.size, Image.Resampling.NEAREST)
        mask = np.where(np.asarray(mask) >= 128, 255, 0).astype(np.uint8)
    points, descriptors = cv2.ORB_create(nfeatures=1800, fastThreshold=8).detectAndCompute(grey, mask)
    return points, descriptors


def find_source_frame(source_vehicle, foreground, candidate_numbers=None):
    reference = foreground.copy()
    points, descriptors = _features(reference, foreground.getchannel('A'))
    if descriptors is None:
        raise ValueError('Stored foreground has no matchable features')
    matcher = cv2.BFMatcher(cv2.NORM_HAMMING)
    ranked = []
    for obj in minio_client.list_objects(RAW_BUCKET, prefix=f'{source_vehicle}/candidates/', recursive=True):
        if not obj.object_name.endswith('.jpg'):
            continue
        if candidate_numbers is not None and int(obj.object_name.rsplit('-', 1)[1].split('.')[0]) not in candidate_numbers:
            continue
        original = Image.open(io.BytesIO(_download_bytes(RAW_BUCKET, obj.object_name)))
        other_points, other_descriptors = _features(original)
        if other_descriptors is None:
            continue
        pairs = matcher.knnMatch(descriptors, other_descriptors, k=2)
        good = [a for a, b in pairs if a.distance < .77 * b.distance]
        inliers = 0
        if len(good) >= 6:
            p1 = np.float32([points[item.queryIdx].pt for item in good])
            p2 = np.float32([other_points[item.trainIdx].pt for item in good])
            _, accepted = cv2.estimateAffinePartial2D(p1, p2, method=cv2.RANSAC,
                                                       ransacReprojThreshold=5.)
            inliers = int(accepted.sum()) if accepted is not None else 0
        ranked.append((inliers, len(good), obj.object_name))
    return sorted(ranked, reverse=True)[:8]


def save_trace(vehicle, source_vehicle, frame, output_dir, candidate_key=None):
    output_dir.mkdir(parents=True, exist_ok=True)
    old_bytes = _download_bytes(RAW_BUCKET, f'{vehicle}/transparent-{frame}.png')
    old_foreground = Image.open(io.BytesIO(old_bytes)).convert('RGBA')
    matches = []
    if candidate_key is None:
        matches = find_source_frame(source_vehicle, old_foreground)
        if not matches or matches[0][0] < 8:
            raise ValueError(f'No reliable source match: {matches}')
        candidate_key = matches[0][2]
    source_bytes = _download_bytes(RAW_BUCKET, candidate_key)
    source = Image.open(io.BytesIO(source_bytes)).convert('RGB')
    source.save(output_dir / '01_original_source.jpg', quality=96)
    segmentation_bytes = level_source_image(source_bytes, 0.)
    inference_input = Image.open(io.BytesIO(segmentation_bytes)).convert('RGB')
    inference_input.save(output_dir / '02_segmentation_input.jpg', quality=96)

    raw_alpha = _session.predict(inference_input)[0]
    raw_alpha.save(output_dir / '03_raw_birefnet_alpha.png')
    resized_alpha = raw_alpha.resize(source.size, Image.Resampling.LANCZOS)
    resized_alpha.save(output_dir / '04_alpha_after_resize.png')
    postprocessed = Image.fromarray(post_process(np.asarray(raw_alpha)))
    postprocessed.save(output_dir / '03b_rembg_postprocess_alpha.png')
    rgba = inference_input.copy().convert('RGBA')
    rgba.putalpha(postprocessed)
    cleaned, _ = _cleanup_mask(rgba, frame, log_quality=False)
    cleaned, retry_used, _ = _target_locked_retry(inference_input, cleaned, frame, (.5, .58))
    cleaned.getchannel('A').save(output_dir / '05_alpha_after_cleanup.png')
    current_foreground = attach_mask_to_source(source_bytes, cleaned)
    current_foreground.save(output_dir / '06_current_pipeline_foreground_rgba.png')
    old_foreground.save(output_dir / '06_final_foreground_rgba.png')
    old_foreground.getchannel('A').save(output_dir / '06b_stored_foreground_alpha.png')
    detailed_foreground, detail_report = segment_studio_source(
        source_bytes, lambda image: _session.predict(image)[0])
    detailed_foreground.getchannel('A').save(output_dir / '08_studio_soft_alpha.png')
    detailed_foreground.save(output_dir / '08_studio_foreground_rgba.png')
    create_studio_image(detailed_foreground, canvas_size=(3840, 2160),
                        style='photo').save(output_dir / '09_studio_detail_composite.jpg', quality=96)

    # Readable detail strips use each mask's own low-threshold top foreground;
    # the old stored mask may have a different geometry from today's source.
    for label, picture, alpha in (
        ('01_roof_original', source, raw_alpha),
        ('03_roof_raw', raw_alpha, raw_alpha),
        ('03b_roof_postprocess', postprocessed, postprocessed),
        ('05_roof_cleaned', cleaned.getchannel('A'), cleaned.getchannel('A')),
        ('06_roof_stored', old_foreground, old_foreground.getchannel('A')),
    ):
        bounds = alpha.point(lambda value: 255 if value >= 24 else 0).getbbox()
        if bounds:
            x0, y0, x1, _ = bounds
            detail = picture.crop((max(0, x0-45), max(0, y0-40),
                                   min(picture.width, x1+45), min(picture.height, y0+90)))
            detail.resize((detail.width*2, detail.height*2),
                          Image.Resampling.NEAREST).save(output_dir / f'{label}.png')
    try:
        manifest = json.loads(_download_bytes(
            PROCESSED_BUCKET, f'{vehicle}/studio-photos/manifest.json'))
        photo = next(item for item in manifest['photos'] if item['sourceFrame'] == frame)
        composite = Image.open(io.BytesIO(_download_bytes(
            PROCESSED_BUCKET, f"{vehicle}/studio-photos/{photo['file']}"))).convert('RGB')
    except Exception:
        composite = create_studio_image(old_foreground, canvas_size=(3840, 2160), style='photo')
    composite.save(output_dir / '07_final_studio_composite.jpg', quality=96)
    report = {'vehicle': vehicle, 'sourceVehicle': source_vehicle, 'viewerFrame': frame,
              'candidateKey': candidate_key, 'sourceMatches': matches,
              'sourceSize': source.size, 'inferenceSize': inference_input.size,
              'rawMaskSize': raw_alpha.size, 'retryUsed': retry_used,
              'rawNonzero': int(np.count_nonzero(np.asarray(raw_alpha) > 10)),
              'postprocessedNonzero': int(np.count_nonzero(np.asarray(postprocessed) > 10)),
              'cleanedNonzero': int(np.count_nonzero(np.asarray(cleaned.getchannel('A')) > 10)),
              'studioDetail': detail_report}
    (output_dir / 'debug.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--vehicle', required=True)
    parser.add_argument('--source-vehicle', required=True)
    parser.add_argument('--frame', type=int, required=True)
    parser.add_argument('--candidate-key')
    parser.add_argument('--output-dir', type=Path, required=True)
    arguments = parser.parse_args()
    print(json.dumps(save_trace(arguments.vehicle, arguments.source_vehicle, arguments.frame,
                                arguments.output_dir, arguments.candidate_key), indent=2))
