import io
import json
import os
import sys
import unittest
import zipfile
from unittest.mock import patch

import numpy as np
from PIL import Image, ImageDraw

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from processing.studio_export import export_studio_photos, select_studio_indices
from processing.studio_compose import create_studio_image, robust_ground_anchor, studio_placement


class StudioExportTests(unittest.TestCase):
    def test_ten_unique_even_circular_views(self):
        for count in (36, 108):
            indexes = select_studio_indices(count)
            self.assertEqual(len(indexes), 10)
            self.assertEqual(len(set(indexes)), 10)
            self.assertEqual(indexes, select_studio_indices(count))
            gaps = [b-a for a, b in zip(indexes, indexes[1:])]
            gaps.append(count+indexes[0]-indexes[-1])
            self.assertLessEqual(max(gaps)-min(gaps), 1)
            self.assertEqual(sum(gaps), count)
        self.assertEqual(select_studio_indices(36), [1, 4, 8, 11, 15, 19, 22, 26, 29, 33])

    def test_ground_anchor_rejects_thin_hitch_and_placement_is_translation(self):
        image = Image.new('RGBA', (600, 360))
        draw = ImageDraw.Draw(image)
        draw.rectangle((60, 80, 530, 250), fill=(30, 80, 50, 255))
        draw.ellipse((110, 205, 205, 327), fill=(20, 20, 20, 255))
        draw.ellipse((390, 205, 490, 327), fill=(20, 20, 20, 255))
        draw.rectangle((545, 255, 551, 351), fill=(10, 10, 10, 255))
        anchor = robust_ground_anchor(np.asarray(image.getchannel('A')))
        self.assertAlmostEqual(anchor, 327, delta=4)
        dimensions, (x, y), ground = studio_placement(image.size, anchor, (3840, 2160))
        self.assertEqual(x, (3840-dimensions[0])//2)
        self.assertAlmostEqual(y+anchor*dimensions[1]/image.height, ground, delta=1)
        with patch('processing.studio_compose.estimate_wheel_contacts', side_effect=AssertionError('wheel logic used')):
            composed = create_studio_image(image, canvas_size=(400, 225))
        self.assertEqual(composed.size, (400, 225))

    def test_empty_mask_has_safe_studio_fallback(self):
        image = create_studio_image(Image.new('RGBA', (200, 100)), canvas_size=(400, 225))
        self.assertEqual(image.size, (400, 225))

    def test_export_writes_ten_images_archive_and_manifest_without_viewer_keys(self):
        stored = {}
        opened = []
        source = Image.new('RGBA', (400, 225))
        ImageDraw.Draw(source).rectangle((20, 20, 380, 220), fill=(20, 80, 50, 255))
        with patch('processing.studio_export.EXPORT_SIZE', (400, 225)):
            manifest = export_studio_photos('car', lambda index: (opened.append(index), source)[1],
                                            lambda _: {}, lambda key, data, _: stored.__setitem__(key, data))
        self.assertEqual(opened, select_studio_indices(36))
        self.assertEqual(len([key for key in stored if key.endswith('.jpg')]), 10)
        self.assertTrue(all(key.startswith('car/studio-photos/') for key in stored))
        self.assertEqual(manifest['count'], 10)
        with zipfile.ZipFile(io.BytesIO(stored['car/studio-photos/album.zip'])) as album:
            self.assertEqual(len(album.namelist()), 10)
        self.assertEqual(json.loads(stored['car/studio-photos/manifest.json'])['photos'][0]['sourceFrame'], 1)

    def test_bad_source_mask_reports_failure_without_false_success(self):
        with self.assertRaisesRegex(ValueError, 'no usable vehicle mask'):
            export_studio_photos('car', lambda _: Image.new('RGBA', (400, 225)),
                                 lambda _: {}, lambda *_: None)

    def test_one_bad_mask_uses_nearest_valid_unreserved_frame(self):
        stored = {}
        source = Image.new('RGBA', (400, 225))
        ImageDraw.Draw(source).rectangle((20, 20, 380, 220), fill=(20, 80, 50, 255))
        def read(index):
            return Image.new('RGBA', (400, 225)) if index == 8 else source
        with patch('processing.studio_export.EXPORT_SIZE', (400, 225)):
            manifest = export_studio_photos('car', read, lambda _: {},
                                            lambda key, data, _: stored.__setitem__(key, data))
        self.assertEqual(manifest['count'], 10)
        self.assertEqual(manifest['photos'][2]['sourceFrame'], 7)
        self.assertTrue(manifest['photos'][2]['fallbackUsed'])
        self.assertEqual(len({item['sourceFrame'] for item in manifest['photos']}), 10)


if __name__ == '__main__':
    unittest.main()
