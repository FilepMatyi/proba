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

from processing.studio_export import export_studio_photos, select_quality_views, select_studio_indices
from processing.studio_compose import create_studio_image, robust_ground_anchor, studio_placement
from processing.studio_photo_look import cyclorama_template, floor_reflection, photo_shadow_layers


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

    def test_quality_and_sensor_angle_choose_best_candidate_in_each_sector(self):
        candidates = [{'index': i, 'angle': ((i-1)/35)**1.5*350,
                       'quality': 72.} for i in range(1, 37)]
        candidates[1]['quality'] = 100.  # Better frame near the circular seam.
        first = select_quality_views(candidates, orbit_frames=36)
        self.assertEqual(first, select_quality_views(candidates, orbit_frames=36))
        self.assertEqual(len({item['index'] for item in first}), 10)
        self.assertEqual(first[0]['index'], 2)
        self.assertEqual(first[0]['angleSource'], 'sensor')
        self.assertNotEqual(first[5]['index'], select_studio_indices(36)[5])
        self.assertTrue(all(abs((item['selectionAngle']-item['targetAngle']+180)%360-180) <= 18
                            for item in first))

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
        hero_dimensions, _, hero_ground = studio_placement(image.size, anchor, (3840, 2160),
                                                            fill_ratio=.70)
        self.assertGreater(hero_dimensions[1], dimensions[1])
        self.assertEqual(hero_ground, ground)

    def test_empty_mask_has_safe_studio_fallback(self):
        image = create_studio_image(Image.new('RGBA', (200, 100)), canvas_size=(400, 225))
        self.assertEqual(image.size, (400, 225))
        photo = create_studio_image(Image.new('RGBA', (200, 100)), canvas_size=(400, 225), style='photo')
        self.assertLess(max(abs(a-b) for a, b in zip(photo.getpixel((200, 170)),
                                                     photo.getpixel((30, 170)))), 8,
                        'cyclorama has no central turntable hub')

    def test_contact_shadows_follow_final_translation_without_rotation(self):
        source = Image.new('RGBA', (600, 360))
        ImageDraw.Draw(source).rectangle((40, 50, 560, 320), fill=(50, 90, 60, 255))
        contacts = [{'x': 140., 'y': 230., 'radius': 50.},
                    {'x': 470., 'y': 258., 'radius': 62.}]
        with patch('processing.studio_compose.tire_contacts', return_value=contacts), \
             patch('processing.studio_compose.photo_shadow_layers', wraps=photo_shadow_layers) as draw_shadow, \
             patch('processing.studio_compose.estimate_wheel_contacts',
                   side_effect=AssertionError('wheel roll used')):
            image = create_studio_image(source, canvas_size=(400, 225), style='photo')
        self.assertEqual(image.size, (400, 225))
        anchors = draw_shadow.call_args.args[4]
        self.assertEqual(len(anchors), 2)
        self.assertGreater(anchors[1]['canvasY'], anchors[0]['canvasY'])
        self.assertAlmostEqual(anchors[1]['canvasY']-anchors[0]['canvasY'],
                               (contacts[1]['y']-contacts[0]['y'])*draw_shadow.call_args.args[1][1]/271,
                               delta=1)

    def test_photo_shadow_has_three_grounded_components(self):
        contacts = [{'canvasX': 100., 'canvasY': 142., 'radius': 25.},
                    {'canvasX': 300., 'canvasY': 150., 'radius': 30.}]
        layers = photo_shadow_layers((400, 225), (300, 110), 50, 150, contacts)
        self.assertEqual(len(layers), 3)
        alpha_peaks = [np.asarray(layer.getchannel('A')).max() for layer, _ in layers]
        self.assertLess(alpha_peaks[0], alpha_peaks[1])
        self.assertLess(alpha_peaks[1], alpha_peaks[2])
        contact, (left, top) = layers[-1]
        alpha = np.asarray(contact.getchannel('A'))
        self.assertGreater(alpha[142-top, 100-left], 0)
        self.assertGreater(alpha[150-top, 300-left], 0)

    def test_floor_reflection_is_compressed_faint_and_fades(self):
        source = Image.new('RGBA', (200, 100), (20, 100, 60, 255))
        reflected = floor_reflection(source, 90, 45)
        alpha = np.asarray(reflected.getchannel('A'))
        self.assertLessEqual(reflected.height, 45)
        self.assertLessEqual(alpha.max(), 14)
        self.assertGreater(alpha[2, 100], alpha[-2, 100])
        self.assertGreater(alpha[2, 100], 0)

    def test_cyclorama_has_soft_sweep_without_a_platform(self):
        background = np.asarray(cyclorama_template(400, 225))
        self.assertGreater(int(background[110, 200, 0]), int(background[220, 200, 0]))
        self.assertLess(int(np.abs(np.diff(background[:, 200, 0].astype(np.int16))).max()), 3)
        self.assertLess(abs(int(background[170, 200, 0]) - int(background[170, 30, 0])), 8)

    def test_intermittent_tire_detection_does_not_move_vehicle(self):
        source = Image.new('RGBA', (600, 360))
        ImageDraw.Draw(source).rectangle((40, 50, 560, 320), fill=(50, 120, 60, 255))
        positions = []
        for contacts in ([], [{'x': 140., 'y': 250., 'radius': 50.}]):
            with patch('processing.studio_compose.tire_contacts', return_value=contacts):
                image = create_studio_image(source, canvas_size=(400, 225), style='photo')
            rgb = np.asarray(image).astype(np.int16)
            ys = np.where((rgb[:, :, 1] > rgb[:, :, 0]+30) & (rgb[:, :, 1] > rgb[:, :, 2]+30))[0]
            positions.append((int(ys.min()), int(ys.max())))
        self.assertEqual(positions[0], positions[1])

    def test_export_writes_ten_images_archive_and_manifest_without_viewer_keys(self):
        stored = {}
        opened = []
        source = Image.new('RGBA', (400, 225))
        ImageDraw.Draw(source).rectangle((20, 20, 380, 220), fill=(20, 80, 50, 255))
        with patch('processing.studio_export.EXPORT_SIZE', (400, 225)):
            manifest = export_studio_photos('car', lambda index: (opened.append(index), source)[1],
                                            lambda _: {}, lambda key, data, _: stored.__setitem__(key, data))
        self.assertEqual(opened[:36], list(range(1, 37)))
        self.assertEqual(len([key for key in stored if key.endswith('.jpg')]), 10)
        self.assertTrue(all(key.startswith('car/studio-photos/') for key in stored))
        self.assertEqual(manifest['count'], 10)
        self.assertIn('generatedAt', manifest)
        self.assertEqual(len({item['sourceFrame'] for item in manifest['photos']}), 10)
        self.assertTrue(all(item['angleSource'] == 'ordered-frames' for item in manifest['photos']))
        with zipfile.ZipFile(io.BytesIO(stored['car/studio-photos/album.zip'])) as album:
            self.assertEqual(len(album.namelist()), 10)
        self.assertEqual(json.loads(stored['car/studio-photos/manifest.json'])['photos'][0]['sourceFrame'], 1)

    def test_bad_source_mask_reports_failure_without_false_success(self):
        with self.assertRaisesRegex(ValueError, 'Not enough usable masks'):
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
        self.assertNotEqual(manifest['photos'][2]['sourceFrame'], 8)
        self.assertTrue(manifest['photos'][2]['fallbackUsed'])
        self.assertEqual(len({item['sourceFrame'] for item in manifest['photos']}), 10)


if __name__ == '__main__':
    unittest.main()
