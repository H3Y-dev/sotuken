import math
import os
import sys
import unittest

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from center_estimate import estimate_center


def _radial_tick(center, angle, radius=80.0, angle_error=0.0):
    cx, cy = center
    return {
        'centroid': (
            cx + radius * math.cos(angle),
            cy + radius * math.sin(angle),
        ),
        'line_angle': angle + angle_error,
    }


class TestEstimateCenter(unittest.TestCase):
    def test_recovers_known_center_from_radial_ticks(self):
        expected = (120.5, 94.25)
        ticks = [
            _radial_tick(expected, angle, angle_error=error)
            for angle, error in zip(
                np.linspace(0.15, 2.95, 12),
                [0.004, -0.006, 0.002, -0.003] * 3,
            )
        ]

        actual = estimate_center(np.zeros((240, 320, 3), dtype=np.uint8), ticks)

        self.assertIsNotNone(actual)
        self.assertAlmostEqual(actual[0], expected[0], delta=1.0)
        self.assertAlmostEqual(actual[1], expected[1], delta=1.0)

    def test_can_return_center_outside_image(self):
        expected = (-45.0, 130.0)
        ticks = [
            _radial_tick(expected, angle, radius=140.0)
            for angle in np.linspace(-0.8, 0.9, 9)
        ]

        actual = estimate_center(np.zeros((100, 100, 3), dtype=np.uint8), ticks)

        self.assertIsNotNone(actual)
        self.assertAlmostEqual(actual[0], expected[0], delta=1e-6)
        self.assertAlmostEqual(actual[1], expected[1], delta=1e-6)
        self.assertLess(actual[0], 0.0)

    def test_ignores_non_radial_outlier_lines(self):
        expected = (160.0, 110.0)
        inliers = [
            _radial_tick(expected, angle, angle_error=error)
            for angle, error in zip(
                np.linspace(0.0, 2.8, 10),
                [0.003, -0.004, 0.002, -0.003, 0.0] * 2,
            )
        ]
        outliers = [
            {'centroid': (25.0, 20.0), 'line_angle': 0.1},
            {'centroid': (290.0, 25.0), 'line_angle': 1.7},
            {'centroid': (40.0, 205.0), 'line_angle': 2.2},
            {'centroid': (270.0, 210.0), 'line_angle': 0.8},
        ]

        actual = estimate_center(
            np.zeros((240, 320, 3), dtype=np.uint8), inliers + outliers)

        self.assertIsNotNone(actual)
        self.assertAlmostEqual(actual[0], expected[0], delta=1.0)
        self.assertAlmostEqual(actual[1], expected[1], delta=1.0)

    def test_returns_none_when_fewer_than_three_valid_ticks_exist(self):
        ticks = [
            _radial_tick((50.0, 50.0), 0.0),
            _radial_tick((50.0, 50.0), 1.0),
        ]

        self.assertIsNone(
            estimate_center(np.zeros((100, 100, 3), dtype=np.uint8), ticks)
        )

    def test_returns_none_for_parallel_lines(self):
        ticks = [
            {'centroid': (10.0, y), 'line_angle': 0.0}
            for y in (10.0, 30.0, 50.0, 70.0)
        ]

        self.assertIsNone(
            estimate_center(np.zeros((100, 100, 3), dtype=np.uint8), ticks)
        )


if __name__ == '__main__':
    unittest.main()
