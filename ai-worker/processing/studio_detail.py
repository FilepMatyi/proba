"""Original-source, soft-matte segmentation for the 10-photo export only.

The 360 viewer keeps its existing stored cutouts.  A photo export may re-run
BiRefNet from the selected original frame, without rembg's binary morphological
post-processing, to retain thin roof rails and other accessories.
"""
import io
import math

import cv2
import numpy as np
from PIL import Image, ImageOps

from processing.source_detail import MAX_DETAIL_SIDE
from processing.target_lock import DEFAULT_TARGET_CENTER, select_primary_component


# Frame 35 of the test capture has a meaningful upper-edge distribution down
# to ~0.10, while rembg's 0.50 binary post-process deletes it.  These are
# topology thresholds, never replacement alpha values.
STRONG_ALPHA = .55
WEAK_ALPHA = .10


def padded_vehicle_crop(bbox, image_size, expansion=1.):
    """Generous all-sided ROI; a clipped top falls back to the full frame."""
    width, height = image_size
    x0, y0, x1, y1 = bbox
    box_w, box_h = x1-x0, y1-y0
    side = max(32, math.ceil(box_w*.10*expansion))
    top = max(32, math.ceil(box_h*.16*expansion))
    bottom = max(32, math.ceil(box_h*.10*expansion))
    box = (max(0, x0-side), max(0, y0-top),
           min(width, x1+side), min(height, y1+bottom))
    # If the coarse foreground itself reaches an image edge, no crop can be
    # trusted to include an unseen roof box, antenna, mirror or tow hook.
    if x0 <= 2 or y0 <= 2 or x1 >= width-2 or y1 >= height-2:
        return (0, 0, width, height)
    return box


def _soft_bbox(alpha, threshold=WEAK_ALPHA):
    ys, xs = np.where(alpha >= threshold)
    if not len(xs):
        return None
    return (int(xs.min()), int(ys.min()), int(xs.max())+1, int(ys.max())+1)


def preserve_connected_soft_alpha(raw_alpha, target_center=DEFAULT_TARGET_CENTER):
    """Use hysteresis for topology while retaining original floating alpha.

    A strong primary vehicle seeds a weak connected component.  The weak
    foreground can include a one-pixel rack support; disconnected sky noise
    cannot enter.  No dilation, erosion or binary output is applied.
    """
    alpha = np.clip(np.asarray(raw_alpha, dtype=np.float32), 0., 1.)
    if alpha.ndim != 2:
        raise ValueError('Expected a 2D alpha matte')
    high = np.where(alpha >= STRONG_ALPHA, 255, 0).astype(np.uint8)
    main_seed, _ = select_primary_component(high, target_center=target_center)
    seed = main_seed > 0
    if not np.any(seed):
        return np.zeros_like(alpha)
    weak = (alpha >= WEAK_ALPHA).astype(np.uint8)
    count, labels = cv2.connectedComponents(weak, connectivity=8)
    votes = np.bincount(labels[seed], minlength=count)
    votes[0] = 0
    chosen = int(votes.argmax())
    if not votes[chosen]:
        return np.zeros_like(alpha)
    return np.where(labels == chosen, alpha, 0.).astype(np.float32)


def crop_edge_risk(alpha):
    """Flag foreground too close to any inference-crop boundary."""
    bbox = _soft_bbox(alpha)
    if bbox is None:
        return True
    height, width = alpha.shape
    x0, y0, x1, y1 = bbox
    return (x0 < max(8, width*.025) or y0 < max(8, height*.04)
            or width-x1 < max(8, width*.025) or height-y1 < max(8, height*.025))


def _predict_float(predict_mask, image):
    mask = predict_mask(image).convert('L')
    if mask.size != image.size:
        mask = mask.resize(image.size, Image.Resampling.LANCZOS)
    return np.asarray(mask, dtype=np.float32) / 255.


def segment_studio_source(source_bytes, predict_mask, detail_pass=True):
    """Re-segment one chosen original frame; return RGBA and QA metadata.

    ``predict_mask`` is the existing BiRefNet session's predict method wrapped
    as a one-image callable.  A crop increases *effective* model resolution;
    it is always cut from the original frame, never enlarged from a thumbnail.
    """
    with Image.open(io.BytesIO(source_bytes)) as decoded:
        source = ImageOps.exif_transpose(decoded).convert('RGB')
        if max(source.size) > MAX_DETAIL_SIDE:
            source.thumbnail((MAX_DETAIL_SIDE, MAX_DETAIL_SIDE), Image.Resampling.LANCZOS)
        source = source.copy()
    raw = _predict_float(predict_mask, source)
    alpha = preserve_connected_soft_alpha(raw)
    bbox = _soft_bbox(alpha)
    metadata = {'sourceSize': list(source.size), 'detailPassUsed': False,
                'cropRetried': False, 'softAlpha': True, 'bbox': bbox}
    if bbox is None:
        rgba = source.convert('RGBA')
        rgba.putalpha(Image.new('L', source.size))
        return rgba, metadata

    if detail_pass:
        initial_box = padded_vehicle_crop(bbox, source.size)
        box = initial_box
        full_box = (0, 0, *source.size)
        if box != full_box:
            detail = None
            for expansion in (1., 2.):
                box = padded_vehicle_crop(bbox, source.size, expansion)
                crop = source.crop(box)
                local_center = ((.5*source.width-box[0])/crop.width,
                                (.58*source.height-box[1])/crop.height)
                detail_raw = _predict_float(predict_mask, crop)
                detail = preserve_connected_soft_alpha(detail_raw, local_center)
                if not crop_edge_risk(detail):
                    break
                metadata['cropRetried'] = True
            if detail is not None and not crop_edge_risk(detail):
                candidate = np.zeros_like(alpha)
                candidate[box[1]:box[3], box[0]:box[2]] = detail
                x0, y0, x1, y1 = bbox
                upper_limit = min(source.height, y0 + round((y1-y0)*.42))
                xpad = max(8, round((x1-x0)*.04))
                supported_region = np.zeros_like(alpha, dtype=bool)
                supported_region[max(0, y0-round((y1-y0)*.05)):upper_limit,
                                 max(0, x0-xpad):min(source.width, x1+xpad)] = True
                additions = supported_region & (candidate >= WEAK_ALPHA) & (candidate > alpha)
                added_pixels = int(np.count_nonzero(additions & (alpha < WEAK_ALPHA)))
                # A true accessory is thin.  A large new region is more likely
                # scenery attached to the crop mask, so reject that pass.
                if added_pixels <= max(100, int(np.count_nonzero(alpha >= WEAK_ALPHA)*.025)):
                    alpha[additions] = candidate[additions]
                    metadata['detailPassUsed'] = True
                    metadata['detailCrop'] = box
                    metadata['detailAddedPixels'] = added_pixels

    rgba = source.convert('RGBA')
    rgba.putalpha(Image.fromarray(np.rint(alpha*255.).astype(np.uint8), 'L'))
    metadata['bbox'] = _soft_bbox(alpha)
    return rgba, metadata
