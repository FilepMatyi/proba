"""Save non-destructive diagnostics for an existing 10 Studio Photos album.

Run inside the AI worker container: python debug_studio_pose.py VEHICLE_ID
The script reads the original selected frames and existing export, but writes
only local debug artifacts; it never changes MinIO or the 360 viewer.
"""
import io
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from processing.ground_contacts import silhouette_contacts, tire_contacts
from processing.studio_compose import robust_ground_anchor, studio_placement
from processing.studio_detail import segment_studio_source
from processing.studio_export import _match_stored_exposure
from processing.studio_compose import create_studio_image
from worker import RAW_BUCKET, PROCESSED_BUCKET, _download_bytes, redis_client


def _png(image, path):
    image.save(path, optimize=True)


def _preview(image, max_width=1400):
    image = image.copy()
    image.thumbnail((max_width, 1000), Image.Resampling.LANCZOS)
    return image


def main(vehicle_id):
    output = Path('debug') / f'{vehicle_id}-pose-before'
    output.mkdir(parents=True, exist_ok=True)
    manifest = json.loads(_download_bytes(PROCESSED_BUCKET, f'{vehicle_id}/studio-photos/manifest.json'))
    selection = json.loads(_download_bytes(RAW_BUCKET, f'{vehicle_id}/selection.json'))
    source_by_frame = {item['viewerFrame']: item for item in selection['views']}
    rows = []

    def predict_mask(image):
        from processing.background_removal import _session
        return _session.predict(image)[0]

    for photo in manifest['photos']:
        number, index = photo['number'], photo['sourceFrame']
        prefix = f'{number:02d}'
        selected = source_by_frame[index]
        original = _download_bytes(RAW_BUCKET, selected['candidateKey'])
        (output / f'{prefix}-source.jpg').write_bytes(original)
        before = _download_bytes(PROCESSED_BUCKET, f'{vehicle_id}/studio-photos/{prefix}.jpg')
        (output / f'{prefix}-before.jpg').write_bytes(before)
        reference = Image.open(io.BytesIO(_download_bytes(RAW_BUCKET, f'{vehicle_id}/transparent-{index}.png'))).convert('RGBA')
        try:
            foreground, detail = segment_studio_source(original, predict_mask)
            foreground = _match_stored_exposure(foreground, reference)
            source_kind = 'resegmented-original'
        except Exception as error:
            foreground = reference
            detail = {'error': str(error)}
            source_kind = 'stored-mask-fallback'
        _png(foreground, output / f'{prefix}-foreground.png')
        bbox = foreground.getbbox()
        if bbox is None:
            rows.append({'photo': number, 'sourceFrame': index, 'empty': True})
            continue
        crop = foreground.crop(bbox)
        alpha = np.asarray(crop.getchannel('A'))
        tires = tire_contacts(crop)
        silhouette = silhouette_contacts(alpha)
        bottom = robust_ground_anchor(alpha)
        try:
            layout = json.loads(redis_client.hget(f'vehicle:{vehicle_id}:layout', str(index)) or '{}')
        except (TypeError, ValueError):
            layout = {}
        dimensions, (x, y), ground_y = studio_placement(crop.size, bottom, (3840, 2160),
                                                         layout.get('targetHeightRatio', 1.), fill_ratio=.70)
        scale_y = dimensions[1] / crop.height
        nearest = max(tires, key=lambda item: item['y']) if tires else None
        near_gap = None if nearest is None else round((bottom-nearest['y'])*scale_y, 1)
        # The contact slope is deliberately reported as perspective evidence,
        # never interpreted directly as camera roll.
        slope = None
        if len(tires) == 2:
            slope = round(float(np.degrees(np.arctan2(tires[1]['y']-tires[0]['y'],
                                                       tires[1]['x']-tires[0]['x']))), 2)
        overlay = _preview(crop)
        factor = overlay.width / crop.width
        draw = ImageDraw.Draw(overlay)
        draw.rectangle((0, 0, overlay.width-1, overlay.height-1), outline='orange', width=3)
        if bottom is not None:
            by = bottom * factor
            draw.line((0, by, overlay.width, by), fill='orange', width=3)
        for item in silhouette:
            px, py = item['x']*factor, item['y']*factor
            draw.ellipse((px-6, py-6, px+6, py+6), fill='yellow')
        for item in tires:
            px, py = item['x']*factor, item['y']*factor
            draw.ellipse((px-10, py-10, px+10, py+10), outline='red', width=3)
        _png(overlay, output / f'{prefix}-geometry.png')
        row = {'photo': number, 'sourceFrame': index, 'targetAngle': photo['degrees'],
               'sourceKind': source_kind, 'sourceBbox': bbox, 'cropSize': crop.size,
               'layoutTargetHeightRatio': layout.get('targetHeightRatio'),
               'silhouetteAnchor': bottom, 'tireContacts': tires,
               'silhouetteContacts': silhouette, 'wheelImageSlopeDegrees': slope,
               'canvasGroundY': ground_y, 'canvasCarY': y,
               'canvasNearestTireY': None if nearest is None else round(y+nearest['y']*scale_y, 1),
               'nearTireToGroundGapPx': near_gap, 'scale': scale_y, 'detail': detail}
        rows.append(row)
        print(json.dumps({key: row[key] for key in ('photo', 'sourceFrame', 'cropSize',
            'silhouetteAnchor', 'tireContacts', 'wheelImageSlopeDegrees',
            'nearTireToGroundGapPx', 'layoutTargetHeightRatio')}, default=str), flush=True)
    (output / 'diagnostics.json').write_text(json.dumps(rows, indent=2, default=str), encoding='utf-8')
    print(f'Diagnostics: {output}', flush=True)


def render_cached(vehicle_id):
    output = Path('debug') / f'{vehicle_id}-pose-before'
    rows = []
    comparisons = []
    for foreground_path in sorted(output.glob('*-foreground.png')):
        prefix = foreground_path.name[:2]
        foreground = Image.open(foreground_path).convert('RGBA')
        result, pose = create_studio_image(foreground, canvas_size=(3840, 2160),
                                           style='photo', return_pose=True)
        result.save(output / f'{prefix}-after.jpg', quality=93, subsampling=0)
        preview = _preview(result.convert('RGB'), 1280)
        factor = preview.width / result.width
        draw = ImageDraw.Draw(preview)
        canvas = pose['canvas'] if pose else None
        if canvas:
            gy = canvas['groundY']*factor
            draw.line((0, gy, preview.width, gy), fill=(210, 70, 40), width=2)
            draw.rectangle((canvas['x']*factor, canvas['y']*factor,
                            (canvas['x']+canvas['width'])*factor,
                            (canvas['y']+canvas['height'])*factor), outline=(225, 125, 30), width=2)
            for contact in pose['tireContacts']:
                x = (canvas['x']+contact['x']*canvas['width']/pose['sourceSize'][0])*factor
                y = (canvas['y']+contact['y']*canvas['height']/pose['sourceSize'][1])*factor
                draw.ellipse((x-7, y-7, x+7, y+7), outline=(220, 30, 35), width=3)
            draw.rectangle((12, 12, 535, 72), fill=(255, 255, 255))
            draw.text((22, 22), f"{pose['viewType']} | roll {pose['appliedRollDegrees']:+.2f} deg | "
                      f"pitch {pose['pitchCorrectionDegrees']:+.2f} deg", fill=(35, 35, 35))
            draw.text((22, 43), f"ground {canvas['groundY']} px | anchor "
                      f"{pose['groundAnchorSource']}", fill=(35, 35, 35))
        _png(preview, output / f'{prefix}-pose-overlay.png')
        row = {'photo': int(prefix), **pose}
        rows.append(row)
        before = Image.open(output / f'{prefix}-before.jpg')
        pair = Image.new('RGB', (1280, 360), 'white')
        pair.paste(before.resize((640, 360)), (0, 0))
        pair.paste(result.resize((640, 360)), (640, 0))
        pair.save(output / f'{prefix}-before-after.jpg', quality=92)
        comparisons.append(pair)
        print(prefix, pose['viewType'], pose['appliedRollDegrees'], pose['groundAnchorSource'],
              pose['canvas'], flush=True)
    (output / 'pose-after.json').write_text(json.dumps(rows, indent=2, default=str), encoding='utf-8')
    sheet = Image.new('RGB', (1280, 360*len(comparisons)), 'white')
    for index, pair in enumerate(comparisons):
        sheet.paste(pair, (0, 360*index))
    sheet.save(output / 'before-after-contact-sheet.jpg', quality=91)


if __name__ == '__main__':
    if len(sys.argv) > 2 and sys.argv[2] == '--render-cached':
        render_cached(sys.argv[1])
    else:
        main(sys.argv[1])
