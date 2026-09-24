"""Photo-only studio floor, lighting and grounding for the 10-image export.

All effects are derived from the final translated vehicle position.  Nothing
in this module rotates, warps or otherwise changes the photographed car.
"""
from functools import lru_cache

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageOps


@lru_cache(maxsize=2)
def cyclorama_template(width, height):
    """A continuous wall-to-floor sweep with restrained centre illumination."""
    rows = np.arange(height, dtype=np.float32) / max(height, 1)
    columns = np.arange(width, dtype=np.float32) / max(width, 1)
    sweep = np.clip((rows - .54) / .34, 0., 1.)
    sweep = sweep * sweep * (3. - 2. * sweep)
    depth = np.clip((rows - .82) / .18, 0., 1.)
    spotlight = np.exp(-(((columns[None, :] - .50) / .48) ** 2
                         + ((rows[:, None] - .46) / .58) ** 2) * 1.4)
    edge_falloff = ((columns - .50) / .50) ** 2
    image = np.empty((height, width, 3), dtype=np.uint8)
    for channel, (wall, floor) in enumerate(zip((247., 248., 248.), (227., 229., 228.))):
        tone = wall * (1. - sweep) + floor * sweep - depth * 6.
        image[:, :, channel] = np.clip(
            tone[:, None] + 5. * spotlight - 3. * edge_falloff[None, :], 0, 255
        ).astype(np.uint8)
    return Image.fromarray(image, 'RGB')


def floor_reflection(vehicle, ground_local_y, available_height, max_alpha=14):
    """Return a shallow, blurred reflection of only the lower vehicle band.

    The low alpha and quick fade prevent a recognisable second car from
    appearing below the floor.  The returned image begins at the ground line.
    """
    width, height = vehicle.size
    ground_local_y = min(height, max(0, round(ground_local_y)))
    if ground_local_y < 2 or available_height < 2:
        return Image.new('RGBA', (max(1, width), 1))
    band_height = min(ground_local_y, max(2, round(height * .32)))
    band = vehicle.crop((0, ground_local_y - band_height, width, ground_local_y))
    reflected_height = min(available_height, max(2, round(band_height * .38)))
    reflected = ImageOps.flip(band).resize((width, reflected_height), Image.Resampling.LANCZOS)
    reflected = reflected.filter(ImageFilter.GaussianBlur(radius=max(1., height * .012)))
    rgba = np.array(reflected, dtype=np.uint8)
    fade = (1. - np.arange(reflected_height, dtype=np.float32) / reflected_height) ** 2
    rgba[:, :, 3] = np.clip(rgba[:, :, 3].astype(np.float32)
                            * fade[:, None] * (max_alpha / 255.), 0, max_alpha).astype(np.uint8)
    return Image.fromarray(rgba, 'RGBA')


def photo_shadow_layers(canvas_size, vehicle_size, car_x, ground_y, contacts):
    """Return ambient, underbody and tire-contact layers in final canvas space.

    Layers use a local region instead of three 4K canvases.  Tire shadows can
    follow perspective contact positions, but never alter the car placement.
    """
    canvas_w, canvas_h = canvas_size
    width, height = vehicle_size
    contact_rows = [item['canvasY'] for item in contacts]
    first_y = min([ground_y] + contact_rows)
    last_y = max([ground_y] + contact_rows)
    left = max(0, int(car_x - width * .10))
    top = max(0, int(first_y - height * .14))
    right = min(canvas_w, int(car_x + width * 1.10) + 1)
    bottom = min(canvas_h, int(last_y + height * .14) + 1)
    if right <= left or bottom <= top:
        return []
    size = (right - left, bottom - top)
    centre_x = car_x + width * .5 - left
    centre_y = (float(np.median(contact_rows)) if contact_rows else ground_y) - top

    ambient = Image.new('RGBA', size)
    ImageDraw.Draw(ambient).ellipse(
        (centre_x - width * .48, centre_y - height * .060,
         centre_x + width * .48, centre_y + height * .060),
        fill=(26, 28, 29, 24),
    )
    ambient = ambient.filter(ImageFilter.GaussianBlur(radius=max(2., height * .035)))

    underbody = Image.new('RGBA', size)
    ImageDraw.Draw(underbody).ellipse(
        (centre_x - width * .39, centre_y - height * .028,
         centre_x + width * .39, centre_y + height * .028),
        fill=(17, 19, 20, 49),
    )
    underbody = underbody.filter(ImageFilter.GaussianBlur(radius=max(2., height * .016)))

    contact = Image.new('RGBA', size)
    draw = ImageDraw.Draw(contact)
    if contacts:
        for item in contacts:
            x, y = item['canvasX'] - left, item['canvasY'] - top
            radius = max(8., float(item.get('radius', height * .05)))
            draw.ellipse((x - radius * .78, y - height * .010,
                          x + radius * .78, y + height * .010),
                         fill=(9, 11, 12, 110))
    else:
        # A conservative fallback keeps a valid mask grounded when individual
        # tires are too occluded for reliable detection.
        draw.ellipse((centre_x - width * .19, centre_y - height * .010,
                      centre_x + width * .19, centre_y + height * .010),
                     fill=(9, 11, 12, 72))
    contact = contact.filter(ImageFilter.GaussianBlur(radius=max(1., height * .005)))
    return [(layer, (left, top)) for layer in (ambient, underbody, contact)]
