import os
import sys
import unittest

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from processing.target_lock import (
    mask_needs_refinement,
    mask_profile,
    select_primary_component,
    should_use_refined_mask,
    target_crop_box,
)


class TargetLockTests(unittest.TestCase):
    def test_primary_component_prefers_centered_vehicle_over_larger_edge_object(self):
        alpha = np.zeros((100, 100), dtype=np.uint8)
        alpha[:, :38] = 255
        alpha[42:84, 47:84] = 255

        selected, details = select_primary_component(alpha, target_center=(0.62, 0.62))

        self.assertEqual(details['componentCount'], 2)
        self.assertEqual(int(selected[60, 60]), 255)
        self.assertEqual(int(selected[50, 10]), 0)

    def test_scenery_spanning_full_height_requests_refinement(self):
        alpha = np.zeros((100, 100), dtype=np.uint8)
        alpha[:, 5:95] = 255

        self.assertTrue(mask_needs_refinement(mask_profile(alpha)))

    def test_refined_mask_must_improve_and_not_touch_crop_boundary(self):
        base = np.ones((100, 100), dtype=np.uint8) * 255
        refined = np.zeros((100, 100), dtype=np.uint8)
        refined[28:82, 18:84] = 255

        base_profile = mask_profile(base)
        refined_profile = mask_profile(refined)

        self.assertTrue(should_use_refined_mask(base_profile, refined_profile))
        self.assertFalse(should_use_refined_mask(
            base_profile, refined_profile, crop_boundary_touched=True
        ))

    def test_target_crop_matches_capture_safe_zone(self):
        self.assertEqual(target_crop_box(1080, 1920), (0, 307, 1080, 1843))


if __name__ == '__main__':
    unittest.main()
