"""Read-only source inspection; writes only local diagnostic images/JSON."""
import argparse
import json
from pathlib import Path

from PIL import Image, ImageDraw

from recompose import _download_image
from recompose import minio_client, redis_client
from config import PROCESSED_BUCKET
import io
from processing.stabilization import _estimate_wheel_contact_roll
from processing.studio_compose import _find_independent_alpha_contacts
from processing.ground_contacts import tire_contacts, silhouette_contacts
import numpy as np


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('vehicle')
    parser.add_argument('--frames', nargs='+', type=int, default=[5, 15, 21, 28, 34])
    parser.add_argument('--audit', action='store_true', help='Audit actual scaled contacts and render a processed contact sheet.')
    args = parser.parse_args()
    output = Path('/app/diagnostics/grounding')
    output.mkdir(parents=True, exist_ok=True)
    report = {}
    sheet = Image.new('RGB', (1440, 900), 'white') if args.audit else None
    for index in args.frames:
        image = _download_image(f'{args.vehicle}/transparent-{index}.png')
        image = image.crop(image.getbbox())
        image.thumbnail((960, 960), Image.Resampling.LANCZOS)
        measurement = _estimate_wheel_contact_roll(image)
        fallback = _find_independent_alpha_contacts(np.asarray(image)[:, :, 3])
        report[index] = {'size': image.size, 'measurement': measurement, 'fallback': fallback,
                         'tires': tire_contacts(image), 'lobes': silhouette_contacts(np.asarray(image)[:, :, 3])}
        if args.audit:
            from processing.studio_compose import (_build_ground_contacts, _fit_contacts_to_platform,
                _platform_geometry, _platform_vertical_bounds, _enhance_vehicle_detail,
                CANVAS_W, CANVAS_H, CAR_HEIGHT_FILL)
            source = _download_image(f'{args.vehicle}/transparent-{index}.png')
            source = source.crop(source.getbbox())
            layout = json.loads(redis_client.hget(f'vehicle:{args.vehicle}:layout', str(index)))
            scale = min(CANVAS_H*CAR_HEIGHT_FILL*layout['targetHeightRatio']/source.height,
                        CANVAS_W*.90/source.width)*layout.get('groundingScale', 1.)
            scaled = _enhance_vehicle_detail(source.resize((int(source.width*scale), int(source.height*scale)), Image.Resampling.LANCZOS))
            contacts = _build_ground_contacts(scaled, np.asarray(scaled.getchannel('A')), scaled.height-1, scaled.width)
            platform = _platform_geometry(CANVAS_W, CANVAS_H, layout.get('platformDepthRatio'))
            _, anchors = _fit_contacts_to_platform(contacts, (CANVAS_W-scaled.width)//2, platform, scaled.height-1)
            violations = []
            for anchor in anchors:
                lo, hi = _platform_vertical_bounds(platform, anchor['canvasX'])
                if not lo-1 <= anchor['canvasY'] <= hi+1:
                    violations.append(anchor)
            report[index]['audit'] = {'contacts': anchors, 'outsidePlatform': violations,
                                      'platformRadius': platform['radius_y']}
            response = minio_client.get_object(PROCESSED_BUCKET, f'{args.vehicle}/processed-{index}.jpg')
            try:
                processed = Image.open(io.BytesIO(response.read())).convert('RGB')
            finally:
                response.close(); response.release_conn()
            processed.thumbnail((240, 135))
            tile = Image.new('RGB', (240, 150), 'white')
            tile.paste(processed, (0, 15))
            ImageDraw.Draw(tile).text((5, 1), f'{index:02} | contacts {len(anchors)}', fill='black')
            sheet.paste(tile, (((index-1)%6)*240, ((index-1)//6)*150))
        background = Image.new('RGB', image.size, 'white')
        background.paste(image, mask=image.getchannel('A'))
        draw = ImageDraw.Draw(background)
        for x, y in measurement.get('wheelContacts', []):
            draw.ellipse((x-5, y-5, x+5, y+5), fill='red')
        for item in fallback:
            x, y = item['x'], item['y']
            draw.ellipse((x-4, y-4, x+4, y+4), fill='blue')
        background.save(output / f'{args.vehicle}-{index}.jpg', quality=93)
    (output / f'{args.vehicle}.json').write_text(json.dumps(report, indent=2))
    if sheet:
        sheet.save(output / f'{args.vehicle}-all-36.jpg', quality=94)
        print(json.dumps({i: row['audit'] for i, row in report.items()}, indent=2))
    else:
        print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
