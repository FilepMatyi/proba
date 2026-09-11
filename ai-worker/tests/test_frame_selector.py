import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from processing.frame_selector import quality_score, select_optimal_frames


class FrameSelectorTests(unittest.TestCase):
    def setUp(self):
        self.frames = [f'frame-{index:03d}.jpg' for index in range(1, 109)]

    def test_temporal_fallback_returns_36_ordered_groups(self):
        groups, beta, gamma = select_optimal_frames(None, self.frames, 36)

        self.assertEqual(len(groups), 36)
        self.assertEqual(beta, 0)
        self.assertEqual(gamma, 0)
        centers = [group[0]['index'] for group in groups]
        self.assertEqual(len(set(centers)), 36)
        self.assertEqual(centers, sorted(centers))

    def test_sensor_rotation_is_distributed_across_the_orbit(self):
        samples = [
            {'time': index * 100, 'alpha': (index * 4) % 360, 'beta': 90, 'gamma': 0}
            for index in range(91)
        ]
        groups, beta, gamma = select_optimal_frames(samples, self.frames, 36)

        self.assertEqual(len(groups), 36)
        self.assertEqual(beta, 90)
        self.assertEqual(gamma, 0)
        self.assertLess(groups[0][0]['index'], groups[-1][0]['index'])

    def test_too_few_candidates_are_rejected(self):
        with self.assertRaises(ValueError):
            select_optimal_frames(self.frames[:20], self.frames[:20], 36)

    def test_quality_score_balances_focus_and_exposure(self):
        balanced = quality_score({
            'sharpness': 420,
            'brightness': 128,
            'contrast': 50,
            'black_clip_ratio': 0.01,
            'white_clip_ratio': 0.01,
        })
        overexposed = quality_score({
            'sharpness': 420,
            'brightness': 238,
            'contrast': 18,
            'black_clip_ratio': 0.0,
            'white_clip_ratio': 0.42,
        })

        self.assertGreater(balanced, 80)
        self.assertLess(overexposed, balanced - 25)


if __name__ == '__main__':
    unittest.main()
