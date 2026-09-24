import io
import os
import sys
import unittest

import numpy as np
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from processing.studio_detail import (crop_edge_risk, padded_vehicle_crop,
                                      preserve_connected_soft_alpha, segment_studio_source)


class StudioDetailTests(unittest.TestCase):
    def test_connected_one_pixel_accessory_keeps_soft_alpha_and_noise_drops(self):
        raw = np.zeros((100, 150), dtype=np.float32)
        raw[40:85, 25:125] = .98
        raw[20, 40:115] = .18          # Long, one-pixel roof bar.
        raw[20:41, 70] = .15           # One-pixel support into the vehicle.
        raw[7:10, 7:10] = .95          # Unrelated background remnant.
        cleaned = preserve_connected_soft_alpha(raw)
        self.assertAlmostEqual(float(cleaned[20, 100]), .18, places=5)
        self.assertAlmostEqual(float(cleaned[28, 70]), .15, places=5)
        self.assertEqual(float(cleaned[8, 8]), 0.)
        self.assertEqual(int(np.where(cleaned >= .1)[0].min()), 20)

    def test_crop_padding_keeps_upper_accessory_and_edges_force_full_frame(self):
        self.assertEqual(padded_vehicle_crop((50, 55, 150, 145), (200, 200)),
                         (18, 23, 182, 177))
        self.assertLessEqual(padded_vehicle_crop((50, 55, 150, 145), (200, 200))[1], 24)
        self.assertEqual(padded_vehicle_crop((50, 1, 150, 145), (200, 200)),
                         (0, 0, 200, 200))

    def test_crop_top_margin_requests_retry(self):
        alpha = np.zeros((100, 150), dtype=np.float32)
        alpha[2:80, 25:125] = .8
        self.assertTrue(crop_edge_risk(alpha))
        alpha[:15] = 0
        self.assertFalse(crop_edge_risk(alpha))

    def test_studio_segmentation_keeps_alpha_soft_and_bbox_includes_rail(self):
        source = Image.new('RGB', (200, 120), (70, 100, 80))
        output = io.BytesIO()
        source.save(output, 'JPEG')

        def predict(image):
            alpha = np.zeros((image.height, image.width), dtype=np.uint8)
            alpha[45:100, 30:170] = 255
            alpha[15, 40:160] = 46
            alpha[15:46, 90] = 38
            alpha[5:8, 5:8] = 255
            return Image.fromarray(alpha, 'L')

        foreground, report = segment_studio_source(output.getvalue(), predict,
                                                    detail_pass=False)
        alpha = np.asarray(foreground.getchannel('A'))
        self.assertEqual(report['bbox'][1], 15)
        self.assertEqual(int(alpha[15, 120]), 46)
        self.assertEqual(int(alpha[6, 6]), 0)
        self.assertTrue(report['softAlpha'])

    def test_detail_inference_retries_when_crop_touches_top(self):
        source = Image.new('RGB', (1000, 800), (80, 100, 90))
        output = io.BytesIO()
        source.save(output, 'JPEG')
        calls = []

        def predict(image):
            calls.append(image.size)
            alpha = np.zeros((image.height, image.width), dtype=np.uint8)
            if len(calls) == 1:
                alpha[200:650, 200:800] = 255
            elif len(calls) == 2:
                alpha[:image.height-60, 80:image.width-80] = 255
            else:
                alpha[140:image.height-90, 140:image.width-140] = 255
            return Image.fromarray(alpha, 'L')

        _, report = segment_studio_source(output.getvalue(), predict)
        self.assertGreaterEqual(len(calls), 3)
        self.assertTrue(report['cropRetried'])
        self.assertGreater(calls[2][0], calls[1][0])


if __name__ == '__main__':
    unittest.main()
