import io
import json
import math
import os
import sys
import unittest
from unittest.mock import patch

import numpy as np
from PIL import Image, ImageDraw

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from processing.studio_colmap import parse_camera_pose_metadata, parse_colmap_images_text
from processing.studio_selection import (_pick_jointly, circular_distance,
                                         _pose_quality, _scores_from_cached_proxy,
                                         generate_target_windows,
                                         weighted_candidate_score)
from processing.studio_export import export_studio_photos


class StudioSelectionTests(unittest.TestCase):
    def test_target_windows_cover_circle_with_multiple_candidates(self):
        catalog = [{'index': i, 'key': f'frame-{i:03d}.jpg'} for i in range(1, 109)]
        windows, method = generate_target_windows(catalog, target_types=['three-quarter']*10)
        self.assertEqual(method, 'sequence_fallback')
        self.assertEqual([window['targetAngle'] for window in windows],
                         [i*36. for i in range(10)])
        self.assertTrue(all(len(window['candidates']) >= 3 for window in windows))
        self.assertTrue(all(item['angleError'] <= window['halfWindow']
                            for window in windows for item in window['candidates']))
        self.assertLess(circular_distance(358, 2), 5.)

    def test_partial_pose_falls_back_to_reproducible_sequence_windows(self):
        catalog = [{'index': i, 'key': f'frame-{i:03d}.jpg'} for i in range(1, 109)]
        incomplete = {1: {'azimuthDegrees': 0.}, 2: {'azimuthDegrees': 3.}}
        first, method = generate_target_windows(catalog, incomplete)
        second, _ = generate_target_windows(catalog, incomplete)
        self.assertEqual(method, 'sequence_fallback')
        self.assertEqual([[item['index'] for item in target['candidates']] for target in first],
                         [[item['index'] for item in target['candidates']] for target in second])
        self.assertEqual(first[0]['candidates'][0]['index'], 1)

    def test_viewpoint_and_sharpness_can_outweigh_exact_angle(self):
        strong = dict.fromkeys(('sharpness', 'exposure', 'segmentation', 'viewpoint',
                                'perspective', 'framing', 'resolution'), .9)
        weak = {**strong, 'sharpness': .35, 'viewpoint': .3, 'perspective': .3}
        better, _ = weighted_candidate_score(strong, 4., 18.)
        exact, _ = weighted_candidate_score(weak, 0., 18.)
        self.assertGreater(better, exact)
        poor_view = {**strong, 'viewpoint': .2}
        self.assertLess(weighted_candidate_score(poor_view, 0., 18.)[0],
                        weighted_candidate_score(strong, 0., 18.)[0])
        clipped = {**strong, 'clippingRisk': 1.}
        self.assertLess(weighted_candidate_score(clipped, 0., 18.)[0],
                        weighted_candidate_score(strong, 0., 18.)[0])

    def test_joint_selection_avoids_same_or_nearly_same_frame(self):
        catalog = [{'index': i} for i in range(1, 41)]
        windows = [{'slot': 0, 'targetAngle': 0.}, {'slot': 1, 'targetAngle': 36.}]
        scored = {0: [{'index': 10, 'totalScore': .95, 'angleError': 0.},
                      {'index': 5, 'totalScore': .80, 'angleError': 4.}],
                  1: [{'index': 10, 'totalScore': .98, 'angleError': 0.},
                      {'index': 16, 'totalScore': .86, 'angleError': 3.}]}
        selected = _pick_jointly(windows, scored, catalog)
        self.assertEqual(len({item['index'] for item in selected}), 2)
        self.assertGreaterEqual(abs(selected[0]['index']-selected[1]['index']), 2)

    def test_colmap_text_camera_centres_and_json_adapter(self):
        headers = []
        for frame in range(1, 13):
            angle = (frame-1)*2*math.pi/12
            x, y = 10*math.cos(angle), 10*math.sin(angle)
            headers.append(f'{frame} 1 0 0 0 {-x:.6f} {-y:.6f} -1 1 frame-{frame:03d}.jpg')
            headers.append('')
        poses = parse_colmap_images_text('\n'.join(headers))
        self.assertEqual(len(poses), 12)
        self.assertAlmostEqual(poses[1]['azimuthDegrees'], 0., delta=1.)
        self.assertAlmostEqual(poses[7]['azimuthDegrees'], 180., delta=1.)
        self.assertNotIn('pitchDegrees', poses[1])  # No gravity calibration.
        payload = {'frames': [{'sourceFrame': i, 'azimuthDegrees': (i-1)*30,
                               'relativeDistance': 10+i*.01} for i in range(1, 13)]}
        from_json = parse_camera_pose_metadata(json.dumps(payload))
        catalog = [{'index': i, 'key': str(i)} for i in range(1, 13)]
        windows, method = generate_target_windows(catalog, from_json)
        self.assertEqual(method, 'COLMAP')
        self.assertEqual(len(windows), 10)
        self.assertTrue(all(window['candidates'] for window in windows))

    def test_relative_pose_and_upper_surface_geometry_affect_viewpoint(self):
        stats = {'medianElevation': 4., 'medianDistance': 10.}
        ordinary = {'relativeElevationDegrees': 4., 'relativeDistance': 10.}
        extreme = {'relativeElevationDegrees': 25., 'relativeDistance': 7.}
        self.assertGreater(_pose_quality(ordinary, stats), _pose_quality(extreme, stats))

        def proxy(roof_width):
            image = Image.new('RGB', (800, 450), (237, 238, 239))
            matte = Image.new('L', image.size, 0)
            for canvas, color in ((image, (50, 105, 65)), (matte, 255)):
                draw = ImageDraw.Draw(canvas)
                draw.rectangle((100, 210, 700, 340), fill=color)
                draw.rectangle((400-roof_width//2, 100,
                                400+roof_width//2, 215), fill=color)
                draw.ellipse((175, 305, 270, 400), fill=color)
                draw.ellipse((530, 305, 625, 400), fill=color)
            return image, matte

        narrow_image, narrow_mask = proxy(340)
        broad_image, broad_mask = proxy(590)
        narrow = _scores_from_cached_proxy(narrow_image,
                                           np.asarray(narrow_mask)/255.,
                                           narrow_image.size, 'three-quarter')
        broad = _scores_from_cached_proxy(broad_image,
                                          np.asarray(broad_mask)/255.,
                                          broad_image.size, 'three-quarter')
        self.assertGreater(narrow['viewpoint'], broad['viewpoint'])

    def test_studio_export_manifest_contains_source_selection_diagnostics(self):
        stored = {}
        mask = Image.new('RGBA', (400, 225))
        draw = ImageDraw.Draw(mask)
        draw.rectangle((35, 55, 360, 180), fill=(40, 100, 60, 255))
        draw.ellipse((70, 150, 125, 210), fill=(20, 20, 20, 255))
        draw.ellipse((275, 150, 330, 210), fill=(20, 20, 20, 255))
        source = Image.new('RGB', (400, 225), (235, 236, 237))
        source.paste(mask, mask=mask.getchannel('A'))
        buffer = io.BytesIO()
        source.save(buffer, 'JPEG', quality=93)
        data = buffer.getvalue()
        catalog = [{'index': i, 'key': f'frames/frame-{i:03d}.jpg'} for i in range(1, 37)]
        predict = lambda image: mask.getchannel('A').resize(image.size)
        with patch('processing.studio_export.EXPORT_SIZE', (400, 225)):
            manifest = export_studio_photos(
                'car', lambda _: mask, lambda _: {},
                lambda key, payload, _: stored.__setitem__(key, payload),
                candidate_catalog=catalog, read_candidate=lambda _: data,
                predict_mask=predict,
            )
        self.assertEqual(manifest['count'], 10)
        self.assertEqual(manifest['selectionMethod'], 'sequence_fallback')
        self.assertIn('car/studio-photos/selection-debug.json', stored)
        self.assertIn('car/studio-photos/selection-contact-sheet.jpg', stored)
        self.assertEqual(len({photo['sourceFrame'] for photo in manifest['photos']}), 10)
        self.assertTrue(all(photo['selectionConfidence'] in ('high', 'medium', 'low')
                            and photo['viewpointScore'] >= 0.
                            and photo['sourceCandidateKey'] for photo in manifest['photos']))


if __name__ == '__main__':
    unittest.main()
