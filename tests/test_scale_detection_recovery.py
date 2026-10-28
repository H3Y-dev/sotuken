"""目盛り検出の起点を誤ると、正しい数字も範囲に対応できない。"""
import math
import unittest
from unittest.mock import patch

import numpy as np

import tick_detect


class TestCenterRecovery(unittest.TestCase):
    def test_retries_dial_center_only_when_seed_has_no_ticks(self):
        image = np.full((300, 400, 3), 220, dtype=np.uint8)
        center = (200, 150)
        ticks = [
            {'angle': angle, 'line_angle': angle, 'length': 10,
             'centroid': (center[0] + 100 * math.cos(angle),
                          center[1] + 100 * math.sin(angle)), 'is_major': True}
            for angle in (0, 1, 2, 3)
        ]
        with patch('tick_detect.detect_scale_ticks',
                   side_effect=lambda _img, point: ticks if point == center else []), \
                patch('detect_meter_center_v2.detect_meter_center',
                      return_value={'center': center, 'radius': 120}) as dial:
            actual, found = tick_detect.refine_center_iterative(image, (130, 150))
            self.assertEqual(center, actual)
            self.assertEqual(ticks, found)
            dial.assert_called_once()

            dial.reset_mock()
            actual, found = tick_detect.refine_center_iterative(image, center)
            self.assertEqual(center, actual)
            dial.assert_not_called()

    def test_does_not_accept_dial_center_without_ticks(self):
        with patch('tick_detect.detect_scale_ticks', return_value=[]), \
                patch('detect_meter_center_v2.detect_meter_center',
                      return_value={'center': (200, 150), 'radius': 120}):
            self.assertEqual((None, []), tick_detect.refine_center_iterative(
                np.zeros((300, 400, 3), dtype=np.uint8), (130, 150)))


class TestTickPolarityRecovery(unittest.TestCase):
    def test_retries_bright_ticks_only_after_dark_detection_fails(self):
        image = np.full((100, 100, 3), 20, dtype=np.uint8)
        ticks = [{'angle': angle} for angle in (0, 1, 2)]
        with patch('tick_detect._detect_scale_ticks',
                   side_effect=[[], ticks]) as detect:
            self.assertEqual(ticks, tick_detect.detect_scale_ticks(image, (50, 50)))
            np.testing.assert_array_equal(255 - image, detect.call_args.args[0])

        for background in (20, 220):
            image.fill(background)
            with patch('tick_detect._detect_scale_ticks', return_value=ticks) as detect:
                self.assertIs(ticks, tick_detect.detect_scale_ticks(image, (50, 50)))
                detect.assert_called_once()

        image.fill(220)
        with patch('tick_detect._detect_scale_ticks', return_value=[]) as detect:
            self.assertEqual([], tick_detect.detect_scale_ticks(image, (50, 50)))
            detect.assert_called_once()


if __name__ == '__main__':
    unittest.main()
