import io
import os

import numpy as np
from PIL import Image, ImageOps


MAX_DETAIL_SIDE = max(1920, int(os.getenv('MAX_DETAIL_SIDE', '3840')))


def attach_mask_to_source(source_bytes, masked_inference, max_side=None):
    """Restore source-resolution RGB while reusing the AI-generated alpha mask.

    Segmentation is intentionally allowed to run on a smaller image to keep the
    CPU worker stable. The customer-facing pixels, however, come from the
    original decoded frame so a 4K upload remains 4K after background removal.
    """
    limit = MAX_DETAIL_SIDE if max_side is None else max(1920, int(max_side))
    with Image.open(io.BytesIO(source_bytes)) as source:
        source = ImageOps.exif_transpose(source).convert('RGB')
        if max(source.size) > limit:
            source.thumbnail((limit, limit), Image.Resampling.LANCZOS)
        source = source.copy()

    alpha = masked_inference.convert('RGBA').getchannel('A')
    if alpha.size != source.size:
        alpha = alpha.resize(source.size, Image.Resampling.LANCZOS)

    rgb = np.asarray(source, dtype=np.uint8)
    alpha_array = np.asarray(alpha, dtype=np.uint8)
    rgba = np.empty((source.height, source.width, 4), dtype=np.uint8)
    rgba[:, :, :3] = rgb
    rgba[:, :, 3] = alpha_array
    # RGB hidden behind fully transparent pixels otherwise makes every PNG
    # unnecessarily large. Soft edge pixels retain their original colour.
    rgba[alpha_array == 0, :3] = 0
    return Image.fromarray(rgba, 'RGBA')
