import math
import unittest
from unittest.mock import patch

import numpy as np

import scale_value_detect as scale


class TestTiledScaleOCR(unittest.TestCase):
    def test_maps_overlapping_crops_back_and_deduplicates_labels(self):
        image = np.zeros((100, 100, 3), dtype=np.uint8)
        # All four overlapping crops see the same label at (50, 50).
        detections = [
            [dict(value=20.0, x=x, y=y, score=0.9)]
            for x, y in [(100, 100), (20, 100), (100, 20), (20, 20)]
        ]
        detections[1][0]['score'] = 0.95
        with patch.object(scale, 'read_scale_numbers', side_effect=detections):
            numbers = scale._read_scale_numbers_tiled(image)
        self.assertEqual(1, len(numbers))
        self.assertEqual((50, 50), (numbers[0]['x'], numbers[0]['y']))
        self.assertEqual(0.95, numbers[0]['score'])

    def test_retries_only_if_existing_attempts_have_no_range(self):
        image = np.zeros((200, 200, 3), dtype=np.uint8)
        ticks = [dict(angle=a, centroid=(100 + 80 * math.cos(a),
                                        100 + 80 * math.sin(a)), is_major=True)
                 for a in [math.radians(d) % (2 * math.pi) for d in range(135, 406, 15)]]
        numbers = [dict(value=float(i * 10), x=t['centroid'][0],
                        y=t['centroid'][1], score=0.99)
                   for i, t in enumerate(ticks[::3])]
        for global_numbers in (numbers[:1], numbers):
            with self.subTest(global_count=len(global_numbers)), \
                    patch.object(scale, 'read_scale_numbers', return_value=global_numbers), \
                    patch.object(scale, '_read_scale_numbers_tiled', return_value=numbers) as tiled, \
                    patch.object(scale.tick_detect, 'detect_scale_ticks', return_value=ticks):
                points = {}
                result = scale.detect_scale_values(
                    image, ticks, (100, 100), use_vlm=False, numbered_points_out=points)
                self.assertIsNotNone(result)
                self.assertEqual((0, 60), (result['min_value'], result['max_value']))
                self.assertEqual(len(numbers), len(points['bound']))
                if len(global_numbers) == 1:
                    tiled.assert_called_once()
                    self.assertFalse(result['is_confident'])
                else:
                    tiled.assert_not_called()

    def test_rejects_monotonic_decimal_error_in_recovered_labels(self):
        center = (100, 100)
        ticks = [dict(angle=math.radians(d) % (2 * math.pi),
                      centroid=(100 + 80 * math.cos(math.radians(d)),
                                100 + 80 * math.sin(math.radians(d))),
                      is_major=True)
                 for d in range(135, 406, 15)]
        for last_value in (6.0, 1111.0):
            numbers = [dict(value=v, x=t['centroid'][0], y=t['centroid'][1], score=0.99)
                       for v, t in zip((0.0, 0.2, 0.4, last_value), ticks[::3])]
            result = scale._run_ocr_tick(None, ticks, center, 12, 3, numbers=numbers)
            self.assertIsNotNone(result)
            self.assertFalse(scale._is_consistent_recovery(numbers, result, center))

    def test_does_not_turn_insufficient_local_labels_into_a_range(self):
        image = np.zeros((100, 100, 3), dtype=np.uint8)
        with patch.object(scale, 'read_scale_numbers', return_value=[]), \
                patch.object(scale.tick_detect, 'detect_scale_ticks', return_value=[]):
            self.assertIsNone(scale.detect_scale_values(image, [], (50, 50), use_vlm=False))

    def test_accepts_pressure_preferred_series_only_when_requested(self):
        self.assertFalse(scale.is_plausible_fullscale(1.6))
        for maximum in (0.16, 1.6, 16.0, 160.0):
            self.assertTrue(scale.is_plausible_fullscale(maximum, extra_mantissas=(1.6,)))
        self.assertFalse(scale.is_plausible_fullscale(1111, extra_mantissas=(1.6,)))


if __name__ == '__main__':
    unittest.main()
