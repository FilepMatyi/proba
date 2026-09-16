import io
import os
import sys
import unittest

import numpy as np
from PIL import Image, ImageDraw

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from processing.source_detail import attach_mask_to_source


class SourceDetailTests(unittest.TestCase):
    def test_restores_full_resolution_pixels_from_inference_mask(self):
        source = Image.new('RGB', (1600, 900), (18, 32, 48))
        source_array = np.asarray(source).copy()
        source_array[300:600, 500:1100] = (190, 80, 35)
        source = Image.fromarray(source_array, 'RGB')
        source_buffer = io.BytesIO()
        source.save(source_buffer, format='PNG')

        inference = Image.new('RGBA', (800, 450), (0, 0, 0, 0))
        ImageDraw.Draw(inference).rectangle((250, 150, 549, 299), fill=(1, 2, 3, 255))

        restored = attach_mask_to_source(source_buffer.getvalue(), inference)

        self.assertEqual(restored.size, source.size)
        self.assertEqual(restored.getpixel((800, 450)), (190, 80, 35, 255))
        self.assertEqual(restored.getpixel((50, 50)), (0, 0, 0, 0))

    def test_caps_extreme_sources_without_upscaling_small_ones(self):
        source = Image.new('RGB', (4200, 2100), 'gray')
        source_buffer = io.BytesIO()
        source.save(source_buffer, format='JPEG')
        inference = Image.new('RGBA', (800, 400), (20, 30, 40, 255))

        restored = attach_mask_to_source(source_buffer.getvalue(), inference, max_side=2400)

        self.assertEqual(restored.size, (2400, 1200))


if __name__ == '__main__':
    unittest.main()
