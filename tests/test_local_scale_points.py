import unittest
from unittest.mock import patch

import scale_value_detect


class LocalScalePointsTest(unittest.TestCase):
    def test_diagnostics_keep_bound_metadata_when_scale_fails(self):
        numbers = [dict(value=0, x=10, y=0, score=.91),
                   dict(value=100, x=0, y=10, score=.83)]
        ticks = [dict(angle=0, centroid=(10, 0), is_major=True),
                 dict(angle=1.5707963267948966, centroid=(0, 10), is_major=True, synthetic=True)]
        diagnostics = []
        with patch('scale_value_detect.read_scale_numbers', return_value=numbers), \
                patch('scale_value_detect.refine_major_ticks_from_numbers', return_value=ticks), \
                patch('scale_value_detect.extend_ticks_to_numbers', return_value=ticks), \
                patch('scale_value_detect.determine_min_max', return_value=None):
            result = scale_value_detect._run_ocr_tick(
                None, ticks, (0, 0), 12, 3, numbered_points_out=diagnostics)
        self.assertIsNone(result)
        self.assertEqual(diagnostics[0]['bound'], [
            dict(value=0, angle=0, score=.91, synthetic=False),
            dict(value=100, angle=1.5707963267948966, score=.83, synthetic=True)])

    def test_evaluation_counts_local_successes_and_cross_check_flags(self):
        from evaluate import summarize
        summary = summarize([
            dict(stage='ok', value_local=20, cross_check_diff_fs=2.5),
            dict(stage='ok', value_local=30, cross_check_diff_fs=2.5001),
            dict(stage='scale', value_local=None),
            dict(stage='unlabeled', value_local=None),
        ])
        self.assertEqual(summary['total'], 3)
        self.assertEqual(summary['local_success_count'], 2)
        self.assertEqual(summary['local_success_rate'], 2 / 3)
        self.assertEqual(summary['cross_check_flagged_count'], 1)
