"""Independent 10-view, 4K export from the normalized 36-view cutouts."""
import io
import json
import zipfile

import numpy as np
from PIL import Image

from processing.studio_compose import create_studio_image, robust_ground_anchor

EXPORT_COUNT = 10
EXPORT_SIZE = (3840, 2160)


def select_studio_indices(frame_count, count=EXPORT_COUNT):
    """One stable sample per equally spaced circular sector, 1-based."""
    if frame_count < count or count < 1:
        raise ValueError('Not enough frames for the requested circular export')
    return [1 + (slot*frame_count)//count for slot in range(count)]


def export_studio_photos(vehicle_id, read_mask, read_layout, save_object, progress=None,
                         frame_count=36):
    """Generate separate JPEGs, a manifest and a downloadable ZIP.

    Storage callbacks make this testable without Redis, MinIO or the AI model.
    Each frame is decoded, rendered and released before the next one.
    """
    indexes = select_studio_indices(frame_count)
    reserved = set(indexes)
    used = set()
    unusable = set()
    entries = []
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, 'w', compression=zipfile.ZIP_STORED) as bundle:
        for number, planned_index in enumerate(indexes, 1):
            source = None
            source_index = None
            candidates = [planned_index]
            for distance in range(1, frame_count):
                candidates.extend((1 + (planned_index-1-distance) % frame_count,
                                   1 + (planned_index-1+distance) % frame_count))
            for candidate in candidates:
                if candidate in used or candidate in unusable or (candidate in reserved and candidate != planned_index):
                    continue
                try:
                    image = read_mask(candidate).convert('RGBA')
                except (OSError, ValueError):
                    unusable.add(candidate)
                    continue
                if robust_ground_anchor(np.asarray(image.getchannel('A'))) is None:
                    unusable.add(candidate)
                    continue
                source, source_index = image, candidate
                break
            if source is None:
                raise ValueError(f'Frame {planned_index} has no usable vehicle mask or fallback')
            used.add(source_index)
            layout = read_layout(source_index) or {}
            studio = create_studio_image(source, target_height_ratio=layout.get('targetHeightRatio'),
                                         canvas_size=EXPORT_SIZE)
            output = io.BytesIO()
            studio.save(output, 'JPEG', quality=96, subsampling=0, optimize=True)
            data = output.getvalue()
            filename = f'{number:02d}.jpg'
            key = f'{vehicle_id}/studio-photos/{filename}'
            save_object(key, data, 'image/jpeg')
            bundle.writestr(filename, data)
            entries.append({'number': number, 'sourceFrame': source_index,
                            'degrees': round((number-1)*360/EXPORT_COUNT, 1),
                            'file': filename, 'width': EXPORT_SIZE[0], 'height': EXPORT_SIZE[1],
                            'fallbackUsed': source_index != planned_index})
            if progress:
                progress(number)
    manifest = {'vehicleId': vehicle_id, 'kind': 'studio-photos', 'count': len(entries),
                'size': list(EXPORT_SIZE), 'photos': entries}
    save_object(f'{vehicle_id}/studio-photos/album.zip', archive.getvalue(), 'application/zip')
    save_object(f'{vehicle_id}/studio-photos/manifest.json',
                json.dumps(manifest, ensure_ascii=False).encode('utf-8'), 'application/json')
    return manifest
