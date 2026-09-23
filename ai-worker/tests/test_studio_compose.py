import os
import sys
import unittest
from unittest.mock import patch

import numpy as np
from PIL import Image, ImageDraw

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from processing.studio_compose import (
    _build_ground_contacts,
    _enhance_vehicle_detail,
    _find_independent_alpha_contacts,
    _find_contact_spans,
    _find_wheel_bottom,
    _fit_contacts_to_platform,
    _make_local_contact_shadow,
    _platform_geometry,
    _platform_vertical_bounds,
    build_grounding_layout,
)
from processing.ground_contacts import silhouette_contacts, tire_contacts


class StudioComposeTests(unittest.TestCase):
    def test_two_foreshortened_wheels_in_same_half_are_not_lost(self):
        image = Image.new('RGBA', (960, 670))
        draw = ImageDraw.Draw(image)
        draw.polygon(((10, 180), (850, 80), (945, 520), (520, 605), (110, 385)), fill=(50, 95, 65))
        for x, y, rx, ry in ((60, 328, 38, 82), (425, 539, 86, 128)):
            draw.ellipse((x-rx, y-ry, x+rx, y+ry), fill=(20, 20, 20))
            draw.ellipse((x-rx*.6, y-ry*.65, x+rx*.6, y+ry*.65), outline=(175, 175, 175), width=5)
            for offset in (-.4, 0, .4):
                draw.line((x-rx*.5, y+offset*ry, x+rx*.5, y+offset*ry), fill=(165, 165, 165), width=4)
        points = silhouette_contacts(np.asarray(image.getchannel('A')))
        self.assertEqual(len(points), 2)
        self.assertLess(points[1]['x'], image.width/2)
        self.assertAlmostEqual(points[0]['y'], 410, delta=3)
        self.assertAlmostEqual(points[1]['y'], 667, delta=3)

    def test_deep_perspective_contacts_fit_surface_without_deforming_vehicle(self):
        platform = _platform_geometry(3200, 1800)
        contacts = [{'x': 100., 'y': 430.}, {'x': 740., 'y': 860.}]
        _, anchors = _fit_contacts_to_platform(contacts, 600, platform, 860)
        self.assertEqual(anchors[1]['canvasY']-anchors[0]['canvasY'], 430)
        for anchor in anchors:
            back, front = _platform_vertical_bounds(platform, anchor['canvasX'])
            self.assertGreaterEqual(anchor['canvasY'], back-1)
            self.assertLessEqual(anchor['canvasY'], front+1)

    def test_grounding_layout_has_one_depth_and_scale_for_entire_orbit(self):
        images = {i: Image.new('RGBA', (700, 400), (30, 30, 30, 255)) for i in range(1, 5)}
        layout = {i: {'targetHeightRatio': 1.} for i in images}
        points = [{'x': 100., 'y': 180., 'radius': 40.}, {'x': 520., 'y': 390., 'radius': 60.}]
        with patch('processing.studio_compose._build_ground_contacts', return_value=points):
            report = build_grounding_layout(images, layout)
        self.assertGreater(report['platformDepthRatio'], .12)
        self.assertEqual(len({item['platformDepthRatio'] for item in layout.values()}), 1)
        self.assertEqual(len({item['groundingScale'] for item in layout.values()}), 1)

    def test_contact_plane_is_inside_platform_top_surface(self):
        geometry = _platform_geometry(2400, 1350)

        self.assertGreater(geometry['contact_y'], geometry['top_y'])
        self.assertLess(
            geometry['contact_y'],
            geometry['center_y'] + geometry['radius_y'],
        )
        self.assertGreaterEqual(
            geometry['contact_y'] - geometry['top_y'],
            geometry['radius_y'],
        )

    def test_contact_spans_follow_two_lowest_wheel_regions(self):
        image = Image.new('RGBA', (600, 360), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)
        draw.rectangle((70, 110, 530, 250), fill=(40, 90, 60, 255))
        draw.ellipse((105, 220, 215, 330), fill=(20, 20, 20, 255))
        draw.ellipse((385, 220, 495, 330), fill=(20, 20, 20, 255))
        alpha = np.array(image)[:, :, 3]
        bottom = _find_wheel_bottom(alpha, image.width)

        spans = _find_contact_spans(alpha, bottom, image.width)

        self.assertEqual(len(spans), 2)
        self.assertLess(spans[0][1], spans[1][0])

    def test_detected_wheel_contacts_keep_distinct_perspective_rows(self):
        image = Image.new('RGBA', (600, 360), (0, 0, 0, 0))
        alpha = np.asarray(image.getchannel('A'))
        detected = [
            {'x': 150.0, 'y': 286.0, 'radius': 54.0, 'confidence': 0.8},
            {'x': 450.0, 'y': 334.0, 'radius': 62.0, 'confidence': 0.8},
        ]

        with patch('processing.studio_compose.estimate_wheel_contacts', return_value=detected):
            contacts = _build_ground_contacts(image, alpha, 340, image.width)

        self.assertEqual(contacts, detected)
        self.assertEqual(contacts[1]['y'] - contacts[0]['y'], 48.0)

    def test_alpha_fallback_keeps_unequal_wheel_rows_and_ignores_tow_hitch(self):
        image = Image.new('RGBA', (700, 420), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)
        draw.rectangle((80, 95, 620, 260), fill=(40, 90, 60, 255))
        draw.ellipse((115, 210, 245, 320), fill=(20, 20, 20, 255))
        draw.ellipse((455, 230, 585, 360), fill=(20, 20, 20, 255))
        draw.line((620, 270, 678, 382), fill=(15, 15, 15, 255), width=5)
        alpha = np.asarray(image.getchannel('A'))

        contacts = _find_independent_alpha_contacts(alpha)

        self.assertEqual(len(contacts), 2)
        self.assertLess(contacts[0]['x'], 280)
        self.assertLess(contacts[1]['x'], 620)
        self.assertAlmostEqual(contacts[0]['y'], 320, delta=5)
        self.assertAlmostEqual(contacts[1]['y'], 360, delta=5)
        self.assertGreater(contacts[1]['y'] - contacts[0]['y'], 30)

    def test_platform_fit_translates_both_contacts_without_flattening_them(self):
        platform = _platform_geometry(2400, 1350)
        contacts = [
            {'x': 100.0, 'y': 286.0, 'radius': 54.0, 'confidence': 0.8},
            {'x': 500.0, 'y': 334.0, 'radius': 62.0, 'confidence': 0.8},
        ]

        car_y, anchors = _fit_contacts_to_platform(
            contacts,
            car_x=900,
            platform=platform,
            fallback_bottom=340,
        )

        self.assertIsInstance(car_y, int)
        self.assertAlmostEqual(
            anchors[1]['canvasY'] - anchors[0]['canvasY'],
            48.0,
            delta=0.01,
        )
        for anchor in anchors:
            back_y, front_y = _platform_vertical_bounds(platform, anchor['canvasX'])
            self.assertGreaterEqual(anchor['canvasY'], back_y - 1.0)
            self.assertLessEqual(anchor['canvasY'], front_y + 1.0)

    def test_local_contact_shadows_follow_each_wheel_row(self):
        anchors = [
            {'canvasX': 160.0, 'canvasY': 260.0, 'radius': 44.0},
            {'canvasX': 520.0, 'canvasY': 320.0, 'radius': 60.0},
        ]
        layer = _make_local_contact_shadow((700, 400), (600, 300), anchors)
        alpha = np.asarray(layer.getchannel('A'))

        left_peak = int(np.argmax(alpha[:, 100:220].sum(axis=1)))
        right_peak = int(np.argmax(alpha[:, 450:590].sum(axis=1)))

        self.assertAlmostEqual(left_peak, 260, delta=3)
        self.assertAlmostEqual(right_peak, 320, delta=3)
        self.assertGreater(right_peak - left_peak, 50)

    def test_detail_enhancement_preserves_alpha(self):
        image = Image.new('RGBA', (80, 60), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)
        draw.rectangle((10, 10, 69, 49), fill=(70, 105, 80, 210))
        original_alpha = image.getchannel('A').tobytes()
        original_rgb = image.convert('RGB').tobytes()

        enhanced = _enhance_vehicle_detail(image)

        self.assertEqual(enhanced.getchannel('A').tobytes(), original_alpha)
        self.assertNotEqual(enhanced.convert('RGB').tobytes(), original_rgb)
        self.assertEqual(enhanced.mode, 'RGBA')


if __name__ == '__main__':
    unittest.main()
