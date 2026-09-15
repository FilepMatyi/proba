import io
import os
import sys
import unittest

import numpy as np
from PIL import Image, ImageDraw

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from processing.stabilization import (
    apply_sequence_roll_plan,
    build_sequence_layout,
    estimate_vehicle_roll,
    estimate_visual_roll,
    level_source_image,
    smooth_roll_measurements,
    stabilize_vehicle_sequence,
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

        self.assertGreater(result.width, image.width)
        self.assertGreater(result.height, image.height)
        self.assertIsNotNone(result.getbbox())

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
        return image

    def test_vehicle_roll_uses_left_and_right_contact_zones(self):
        vehicle = self._vehicle_mask(280, 315)

        estimate = estimate_vehicle_roll(vehicle)

        self.assertGreater(estimate['angle'], 3.0)
        self.assertGreater(estimate['confidence'], 0.3)

    def test_vehicle_sequence_leveling_reduces_contact_delta(self):
        images = {
            index: self._vehicle_mask(280 + index % 2, 315 + index % 2)
            for index in range(1, 9)
        }

        _, report = stabilize_vehicle_sequence(images)

        self.assertLess(report['contactDeltaAfter'], report['contactDeltaBefore'] * 0.35)


if __name__ == '__main__':
    unittest.main()
