import math
import unittest
from unittest.mock import patch

import numpy as np

import meter_reader


class NeedleAnglesTest(unittest.TestCase):
    def test_tip_angle_is_from_center_and_keeps_segment_direction(self):
        img = np.zeros((200, 200, 3), dtype=np.uint8)
        with patch('meter_reader.cv2.HoughLinesP', return_value=np.array([
            [[100, 103, 180, 103]], [[100, 100, 100, 140]],
        ])), patch('meter_reader.select_indicator_candidate', return_value=(100, 103, 180, 103)):
            needle = meter_reader.detect_needle(img, (100, 100))
        self.assertEqual(needle['direction'], (1.0, 0.0))
        self.assertAlmostEqual(needle['angle_tip'], math.atan2(3, 80))
        confidence = needle['needle_confidence']
        self.assertEqual(confidence['candidate_count'], 2)
        self.assertAlmostEqual(confidence['length_ratio'], 2.0)
        self.assertEqual(confidence['edge_continuity'], 0.0)

    def test_compute_reading_switches_angle_without_changing_default(self):
        needle = {'direction': (1.0, 0.0), 'angle_tip': math.pi / 4,
                  'line': (50, 50, 100, 50), 'tip': (100, 100)}
        with patch('meter_reader.detect_needle', return_value=needle):
            args = (np.zeros((150, 150, 3), dtype=np.uint8), (50, 50),
                    (100, 50), (50, 100), 0, 100)
            default = meter_reader.compute_reading(*args)
            segment = meter_reader.compute_reading(*args, needle_angle='segment')
            tip = meter_reader.compute_reading(*args, needle_angle='tip')
        self.assertEqual(default, segment)
        self.assertEqual(default['value'], 0)
        self.assertAlmostEqual(tip['value'], 50)


if __name__ == '__main__':
    unittest.main()
