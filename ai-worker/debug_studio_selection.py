"""Download and compare a Studio Photos selection without changing storage.

Run inside the AI worker container:
    python debug_studio_selection.py car-test-5-studio-photos-v3
"""
import io
import json
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageOps

from worker import PROCESSED_BUCKET, RAW_BUCKET, _download_bytes


def _thumbnail(data, size):
    with Image.open(io.BytesIO(data)) as source:
        return ImageOps.fit(source.convert('RGB'), size, Image.Resampling.LANCZOS)


def main(vehicle_id):
    prefix = f'{vehicle_id}/studio-photos/'
    output = Path('debug') / f'{vehicle_id}-selection'
    output.mkdir(parents=True, exist_ok=True)
    manifest = json.loads(_download_bytes(PROCESSED_BUCKET, prefix+'manifest.json'))
    diagnostics = json.loads(_download_bytes(PROCESSED_BUCKET,
                                             prefix+'selection-debug.json'))
    (output / 'manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    (output / 'selection-debug.json').write_text(json.dumps(diagnostics, indent=2), encoding='utf-8')
    (output / 'selection-contact-sheet.jpg').write_bytes(
        _download_bytes(PROCESSED_BUCKET, prefix+'selection-contact-sheet.jpg'))

    old_directory = Path('debug') / f'{vehicle_id}-pose-before'
    tile_width, tile_height = 390, 220
    sheet = Image.new('RGB', (tile_width*5, (tile_height*2+34)*2), 'white')
    draw = ImageDraw.Draw(sheet)
    for photo in manifest['photos']:
        number = photo['number']
        row, column = divmod(number-1, 5)
        left, top = column*tile_width, row*(tile_height*2+34)
        key = prefix+photo['file']
        data = _download_bytes(PROCESSED_BUCKET, key)
        (output / photo['file']).write_bytes(data)
        if photo.get('sourceCandidateKey'):
            (output / f'{number:02d}-source.jpg').write_bytes(
                _download_bytes(RAW_BUCKET, photo['sourceCandidateKey']))
        old_path = old_directory / f'{number:02d}-after.jpg'
        if old_path.exists():
            sheet.paste(_thumbnail(old_path.read_bytes(), (tile_width, tile_height)), (left, top+24))
        sheet.paste(_thumbnail(data, (tile_width, tile_height)), (left, top+24+tile_height))
        for caption, caption_top in (('OLD', top+28), ('NEW', top+28+tile_height)):
            draw.rectangle((left+5, caption_top-2, left+51, caption_top+15),
                           fill=(245, 245, 245))
            draw.text((left+9, caption_top), caption, fill='black')
        draw.text((left+8, top+5),
                  f"{number:02d}: source {photo['sourceFrame']}  "
                  f"{photo['selectionConfidence']}  {photo['qualityScore']:.1f}", fill='black')
    sheet.save(output / 'before-after-contact-sheet.jpg', quality=90)
    print(json.dumps({'folder': str(output), 'count': manifest['count'],
                      'method': manifest['selectionMethod'],
                      'frames': [photo['sourceFrame'] for photo in manifest['photos']]},
                     ensure_ascii=False))


if __name__ == '__main__':
    main(sys.argv[1])
