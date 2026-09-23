import io
import os
import sys
import unittest
from unittest.mock import patch

import numpy as np
from PIL import Image, ImageDraw

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from processing.stabilization import (
    _estimate_wheel_contact_roll,
    _fit_orbit_wheel_roll,
    _smooth_perspective_warps,
    apply_roll_correction,
    apply_sequence_roll_plan,
    apply_vehicle_transform,
    build_vehicle_alignment_plan,
    build_vehicle_roll_plan,
    build_sequence_layout,
    combine_scene_and_vehicle_roll,
    estimate_vehicle_roll,
    estimate_visual_roll,
    level_source_image,
    smooth_roll_measurements,
)


class StabilizationTests(unittest.TestCase):
    @staticmethod
    def _reference_image(rotation=0):
        image = Image.new('RGB', (900, 600), 'white')
        draw = ImageDraw.Draw(image)
        for y in (90, 180, 270):
            draw.line((0, y, 900, y), fill='black', width=6)
        for x in (80, 820):
            draw.line((x, 0, x, 600), fill='black', width=6)
        return image.rotate(rotation, resample=Image.Resampling.BICUBIC, expand=False, fillcolor='white')

    def test_visual_roll_estimate_has_the_correct_sign(self):
        clockwise = self._reference_image(rotation=-4)
        estimate = estimate_visual_roll(clockwise)

        self.assertGreater(estimate['confidence'], 0.2)
        self.assertAlmostEqual(estimate['angle'], 4.0, delta=0.8)

    def test_roll_plan_rejects_outlier_and_wraps_last_to_first(self):
        measurements = [
            {'angle': 2.0, 'confidence': 0.9},
            {'angle': 2.2, 'confidence': 0.9},
            {'angle': 11.0, 'confidence': 0.15},
            {'angle': 1.8, 'confidence': 0.9},
        ]

        plan = smooth_roll_measurements(measurements, radius=1, max_correction=6)

        self.assertLess(abs(plan[2]['correction'] - 2.0), 0.5)
        self.assertLess(abs(plan[0]['correction'] - plan[-1]['correction']), 0.4)

    def test_roll_plan_limits_aggressive_scene_lines(self):
        measurements = [
            {'angle': 9.0, 'confidence': 0.9}
            for _ in range(12)
        ]

        plan = smooth_roll_measurements(measurements, max_correction=3.5)

        self.assertTrue(all(abs(item['correction']) <= 3.5 for item in plan))
        self.assertTrue(all(item['limited'] for item in plan))

    def test_level_source_expands_canvas_instead_of_cropping(self):
        source = self._reference_image()
        source_buffer = io.BytesIO()
        source.save(source_buffer, format='JPEG')

        levelled = Image.open(io.BytesIO(level_source_image(source_buffer.getvalue(), 5)))

        self.assertGreater(levelled.width, source.width)
        self.assertGreater(levelled.height, source.height)

    def test_large_source_is_bounded_for_memory_safe_inference(self):
        source = Image.new('RGB', (2400, 1350), 'gray')
        source_buffer = io.BytesIO()
        source.save(source_buffer, format='JPEG')

        prepared = Image.open(io.BytesIO(level_source_image(source_buffer.getvalue(), 0)))

        self.assertEqual(max(prepared.size), 1920)

    def test_scene_roll_is_applied_after_masking_without_clipping(self):
        image = Image.new('RGBA', (300, 200), (0, 0, 0, 0))
        ImageDraw.Draw(image).rectangle((20, 40, 280, 170), fill=(30, 60, 40, 255))

        result = apply_sequence_roll_plan({1: image}, {1: 4.0})[1]

        content_bbox = image.getbbox()
        self.assertGreater(result.width, content_bbox[2] - content_bbox[0])
        self.assertGreater(result.height, content_bbox[3] - content_bbox[1])
        self.assertIsNotNone(result.getbbox())

    def test_anchored_warp_levels_contacts_without_tilting_vertical_edges(self):
        image = Image.new('RGBA', (300, 220), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)
        draw.rectangle((45, 50, 55, 100), fill=(80, 120, 90, 255))
        draw.rectangle((245, 88, 255, 138), fill=(80, 120, 90, 255))

        result = apply_vehicle_transform(image, perspective_warp=-0.9)
        alpha = np.asarray(result.getchannel('A'))
        opaque_columns = np.flatnonzero(np.any(alpha >= 128, axis=0))
        left_x = int(opaque_columns.min() + 5)
        right_x = int(opaque_columns.max() - 5)
        left_rows = np.flatnonzero(alpha[:, left_x] >= 128)
        right_rows = np.flatnonzero(alpha[:, right_x] >= 128)
        left_bottom = int(left_rows[-1])
        right_bottom = int(right_rows[-1])

        self.assertLessEqual(abs(right_bottom - left_bottom), 2)
        self.assertTrue(np.all(np.diff(left_rows) == 1))
        self.assertTrue(np.all(np.diff(right_rows) == 1))

    def test_sequence_layout_reduces_height_jitter(self):
        images = {}
        heights = [300, 302, 365, 301, 299, 300]
        for index, height in enumerate(heights, start=1):
            image = Image.new('RGBA', (500, 500), (0, 0, 0, 0))
            ImageDraw.Draw(image).rectangle((100, 50, 400, 50 + height - 1), fill=(30, 50, 70, 255))
            images[index] = image

        layout, report = build_sequence_layout(images)

        self.assertEqual(len(layout), len(images))
        self.assertLess(report['heightJitterAfter'], report['heightJitterBefore'])
        self.assertTrue(report['circularSmoothing'])

    @staticmethod
    def _vehicle_mask(left_bottom, right_bottom):
        image = Image.new('RGBA', (600, 360), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)
        draw.polygon(
            ((90, 120), (480, 120), (540, 230), (500, 260), (110, 260), (60, 225)),
            fill=(40, 90, 60, 255),
        )
        draw.ellipse((105, left_bottom - 90, 225, left_bottom + 30), fill=(20, 20, 20, 255))
        draw.ellipse((385, right_bottom - 90, 505, right_bottom + 30), fill=(20, 20, 20, 255))
        for center_x, center_y in ((165, left_bottom - 30), (445, right_bottom - 30)):
            draw.ellipse(
                (center_x - 36, center_y - 36, center_x + 36, center_y + 36),
                fill=(155, 155, 155, 255),
                outline=(25, 25, 25, 255),
                width=5,
            )
            draw.ellipse(
                (center_x - 10, center_y - 10, center_x + 10, center_y + 10),
                fill=(25, 25, 25, 255),
            )
            draw.line((center_x - 33, center_y, center_x + 33, center_y), fill=(25, 25, 25, 255), width=5)
            draw.line((center_x, center_y - 33, center_x, center_y + 33), fill=(25, 25, 25, 255), width=5)
        return image

    def test_vehicle_roll_uses_left_and_right_contact_zones(self):
        vehicle = self._vehicle_mask(280, 315)

        estimate = estimate_vehicle_roll(vehicle)

        self.assertGreater(estimate['angle'], 3.0)
        self.assertGreater(estimate['confidence'], 0.3)

    def test_vehicle_roll_prefers_wheel_contacts_over_tow_hitch(self):
        vehicle = self._vehicle_mask(300, 330)
        draw = ImageDraw.Draw(vehicle)
        draw.line((45, 305, 90, 325), fill=(15, 15, 15, 255), width=10)
        draw.ellipse((38, 315, 58, 335), fill=(15, 15, 15, 255))

        estimate = estimate_vehicle_roll(vehicle)

        self.assertEqual(estimate['method'], 'wheels')
        self.assertGreater(estimate['angle'], 3.0)
        self.assertLess(estimate['angle'], 8.0)

    def test_edge_wheel_candidate_survives_hough_padding(self):
        image = Image.new('RGBA', (600, 360), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)
        # Faint alpha corners must NOT change opaque measurement coordinates.
        draw.point((0, 0), fill=(0, 0, 0, 1))
        draw.point((599, 359), fill=(0, 0, 0, 1))
        draw.rectangle((25, 105, 525, 245), fill=(45, 90, 60, 255))
        draw.ellipse((0, 215, 110, 325), fill=(24, 24, 24, 255))
        draw.ellipse((265, 215, 375, 325), fill=(24, 24, 24, 255))
        for center_x in (55, 320):
            draw.ellipse((center_x - 30, 270 - 30, center_x + 30, 270 + 30), fill=(160, 160, 160, 255))
            draw.line((center_x - 28, 270, center_x + 28, 270), fill=(20, 20, 20, 255), width=5)
            draw.line((center_x, 242, center_x, 298), fill=(20, 20, 20, 255), width=5)

        # Opaque crop is y=105..325 (221 px): padding 45, lower_top 93.
        circles = np.asarray([[[100.0, 72.0, 45.0], [365.0, 72.0, 45.0]]], dtype=np.float32)
        with patch('processing.stabilization.tire_contacts', return_value=[]), \
             patch('processing.stabilization.cv2.HoughCircles', return_value=circles):
            estimate = _estimate_wheel_contact_roll(image)

        self.assertEqual(estimate['method'], 'wheels')
        self.assertGreaterEqual(estimate['confidence'], 0.2)
        self.assertLess(estimate['wheelCenters'][0][0], 90)
        self.assertGreater(estimate['wheelCenters'][1][0], 280)

    def test_wheel_contact_slope_is_measurement_not_direct_rotation(self):
        vehicle = self._vehicle_mask(270, 330)
        estimate = estimate_vehicle_roll(vehicle)

        self.assertIn(estimate['method'], ('wheels', 'silhouette'))
        self.assertGreater(abs(estimate['contactDelta']), 35.0)
        self.assertGreater(abs(estimate['angle']), 3.0)

    def test_narrow_rear_hitch_pair_is_not_used_as_a_ground_plane(self):
        image = Image.new('RGBA', (960, 720), (30, 70, 40, 255))
        footprints = [
            {'x': 190., 'y': 715., 'radius': 90., 'confidence': .6},
            {'x': 650., 'y': 710., 'radius': 40., 'confidence': .6},
        ]
        with patch('processing.stabilization.tire_contacts', return_value=footprints), \
             patch('processing.stabilization.cv2.HoughCircles', return_value=None):
            result = _estimate_wheel_contact_roll(image)
        self.assertEqual(result['confidence'], 0.)

    def test_orbit_fit_interpolates_ambiguous_front_and_rear_views(self):
        measurements = []
        for index in range(36):
            angle = 8.0 * np.sin(4.0 * np.pi * index / 36.0)
            reliable = index % 3 != 0
            measurements.append({
                'angle': angle if reliable else 0.0,
                'confidence': 0.8 if reliable else 0.0,
                'method': 'wheels' if reliable else 'silhouette',
            })

        plan, amplitude = _fit_orbit_wheel_roll(measurements)

        self.assertAlmostEqual(amplitude, 8.0, delta=0.3)
        self.assertAlmostEqual(plan[5], 8.0, delta=0.4)
        self.assertAlmostEqual(plan[14], -8.0, delta=0.4)

    def test_perspective_warp_smoothing_rejects_one_bad_wheel_pair(self):
        clean = 0.28 * np.sin(4.0 * np.pi * np.arange(36) / 36.0)
        expected = _smooth_perspective_warps(clean)
        corrupted = clean.copy()
        corrupted[8] = 0.9

        actual = _smooth_perspective_warps(corrupted)

        self.assertLess(abs(actual[8] - expected[8]), 0.12)
        self.assertLess(abs(actual[7] - expected[7]), 0.08)
        self.assertLess(abs(actual[9] - expected[9]), 0.08)
        self.assertLess(abs(actual[0] - actual[-1]), 0.14)

    @staticmethod
    def _orbit_measurements(common_roll=0.0):
        measurements = []
        for index in range(36):
            angle = common_roll + 8.0 * np.sin(4.0 * np.pi * index / 36.0)
            delta = np.tan(np.radians(angle)) * 400.0
            measurements.append({
                'angle': angle,
                'confidence': 0.85,
                'contactDelta': delta,
                'method': 'wheels',
                'aspectRatio': 2.0,
                'wheelContacts': [
                    (100.0, 240.0 - delta / 2.0),
                    (500.0, 240.0 + delta / 2.0),
                ],
                'wheelRadii': [55.0, 55.0],
            })
        return measurements

    def test_natural_orbit_perspective_does_not_rotate_level_body(self):
        images = {
            index: Image.new('RGBA', (600, 360), (30, 60, 40, 255))
            for index in range(1, 37)
        }
        measurements = self._orbit_measurements()

        with patch('processing.stabilization.estimate_vehicle_roll', side_effect=measurements):
            plan, warp_plan, report = build_vehicle_alignment_plan(images)

        self.assertTrue(report['perspectiveBaselineUsed'])
        self.assertGreater(report['orbitPerspectiveAmplitudeDegrees'], 7.5)
        self.assertLess(max(abs(value) for value in plan.values()), 0.15)
        self.assertGreater(max(abs(value) for value in warp_plan.values()), 0.1)
        self.assertLessEqual(report['maximumPerspectiveWarp'], 0.9)
        self.assertLess(report['contactDeltaAfter'], report['contactDeltaBefore'] * 0.35)

    def test_common_roll_is_recovered_after_perspective_is_removed(self):
        images = {
            index: Image.new('RGBA', (600, 360), (30, 60, 40, 255))
            for index in range(1, 37)
        }
        measurements = self._orbit_measurements(common_roll=2.0)

        with patch('processing.stabilization.estimate_vehicle_roll', side_effect=measurements):
            plan, report = build_vehicle_roll_plan(images)

        values = np.asarray(list(plan.values()))
        self.assertAlmostEqual(float(np.median(values)), 2.0, delta=0.15)
        self.assertLess(float(np.ptp(values)), 0.2)
        self.assertLess(report['maximumResidualAngleDegrees'], 0.2)

    def test_short_sequence_without_perspective_model_is_not_rotated(self):
        images = {
            index: self._vehicle_mask(280, 315)
            for index in range(1, 9)
        }
        images[4] = Image.new('RGBA', (600, 360), (0, 0, 0, 0))

        plan, report = build_vehicle_roll_plan(images)

        self.assertFalse(report['perspectiveBaselineUsed'])
        self.assertTrue(all(value == 0.0 for value in plan.values()))

    def test_scene_roll_and_vehicle_residual_are_added(self):
        combined = combine_scene_and_vehicle_roll(
            {1: 3.0, 2: -2.0},
            {1: 1.2, 2: 0.8},
            {1},
        )

        self.assertAlmostEqual(combined[1], 4.2)
        self.assertAlmostEqual(combined[2], -1.2)


if __name__ == '__main__':
    unittest.main()
