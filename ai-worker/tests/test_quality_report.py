import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from processing.quality_report import segmentation_quality_report


class SegmentationQualityReportTests(unittest.TestCase):
    def test_clean_sequence_preserves_selection_score(self):
        metrics = [{
            'bboxWidthRatio': 0.7,
            'alphaCoverage': 0.3,
            'touchesEdge': False,
        } for _ in range(36)]

        score, warnings, report = segmentation_quality_report(metrics, 93)

        self.assertEqual(score, 93)
        self.assertEqual(warnings, [])
        self.assertEqual(report['segmentation']['edgeTouchingFrames'], 0)

    def test_clipped_and_merged_sequence_is_marked_for_recapture(self):
        metrics = [{
            'bboxWidthRatio': 1.0,
            'alphaCoverage': 0.4,
            'touchesEdge': True,
        } for _ in range(35)]
        metrics.append({
            'bboxWidthRatio': 0.55,
            'alphaCoverage': 0.1,
            'touchesEdge': False,
        })

        score, warnings, report = segmentation_quality_report(metrics, 95)

        self.assertEqual(score, 20)
        self.assertTrue(any('35/36' in warning for warning in warnings))
        self.assertTrue(any('összetapadhatott' in warning for warning in warnings))
        self.assertEqual(report['segmentation']['fullWidthMaskFrames'], 35)


if __name__ == '__main__':
    unittest.main()
