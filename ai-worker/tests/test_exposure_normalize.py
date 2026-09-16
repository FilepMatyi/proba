import os
import sys
import unittest

import numpy as np
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from processing.exposure_normalize import (
    apply_exposure_plan,
    build_exposure_plan,
    measure_exposure,
    normalize_exposure,
)


class ExposureNormalizeTests(unittest.TestCase):
    @staticmethod
    def _vehicle(value, size=(320, 180)):
        image = Image.new('RGBA', size, (0, 0, 0, 0))
        pixels = np.asarray(image).copy()
        pixels[30:150, 40:280] = (value, value, value, 255)
        return Image.fromarray(pixels, 'RGBA')

    def test_streaming_plan_matches_dictionary_normalization(self):
        images = {1: self._vehicle(60), 2: self._vehicle(130), 3: self._vehicle(205)}
        plan = build_exposure_plan(images)
        streamed = {index: apply_exposure_plan(image, plan[index]) for index, image in images.items()}
        normalized = normalize_exposure(images)

        for index in images:
            self.assertEqual(streamed[index].tobytes(), normalized[index].tobytes())

    def test_plan_reduces_foreground_luminance_spread(self):
        images = {1: self._vehicle(55), 2: self._vehicle(130), 3: self._vehicle(210)}
        before = [measure_exposure(image)[0] for image in images.values()]
        normalized = normalize_exposure(images)
        after = [measure_exposure(image)[0] for image in normalized.values()]

        self.assertLess(np.std(after), np.std(before))


if __name__ == '__main__':
    unittest.main()
