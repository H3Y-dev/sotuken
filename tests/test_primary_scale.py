import math
import unittest
from unittest.mock import patch

import numpy as np

import scale_value_detect as scale

from primary_scale import split_number_bands, needs_primary_recheck


def labels(radius, values, angles=None):
    angles = angles or [135 + i * 270 / (len(values) - 1) for i in range(len(values))]
    return [dict(value=value, x=radius * math.cos(math.radians(angle)),
                 y=radius * math.sin(math.radians(angle)), score=0.99)
            for value, angle in zip(values, angles)]


class PrimaryScaleTests(unittest.TestCase):
    def test_separates_two_scales_and_keeps_sparse_outer_text_out(self):
        inner = labels(55, [0, 29, 58, 87, 116, 145])
        outer = labels(110, [0, .2, .4, .6, .8, 1])
        text = labels(150, [2026, 1], [80, 90])
        bands = split_number_bands(inner + outer + text, (0, 0), 100)
        self.assertEqual([6, 6, 2], [len(b['numbers']) for b in bands])
        supported = [b for b in bands if b['supported']]
        self.assertEqual(outer, supported[-1]['numbers'])
        self.assertTrue(needs_primary_recheck(bands, 100))

    def test_inner_single_scale_only_requests_recheck(self):
        numbers = labels(60, [0, 50, 100, 150])
        bands = split_number_bands(numbers, (0, 0), 100)
        self.assertTrue(needs_primary_recheck(bands, 100))
        self.assertEqual(numbers, bands[0]['numbers'])

    def test_close_radial_variation_is_one_band(self):
        numbers = labels(85, [0, 20, 40, 60])
        numbers[1]['x'] *= 1.05
        bands = split_number_bands(numbers, (0, 0), 100)
        self.assertEqual(1, len(bands))
        self.assertFalse(needs_primary_recheck(bands, 100))

    def test_single_inside_column_near_seventy_percent_does_not_trigger(self):
        for radius, expected in ((60, True), (64, True), (66, False), (69, False), (70, False)):
            with self.subTest(radius=radius):
                bands = split_number_bands(labels(radius, [0, 20, 40, 60]), (0, 0), 100)
                self.assertEqual(expected, needs_primary_recheck(bands, 100))

    def test_danger_numbers_do_not_form_a_primary_column(self):
        primary = labels(110, [0, .2, .4, .6, .8, 1])
        danger = labels(96, [80, 100, 120], [0, 10, 20])
        bands = split_number_bands(primary + danger, (0, 0), 100)
        self.assertTrue(needs_primary_recheck(bands, 100))
        self.assertEqual([primary], [b['numbers'] for b in bands if b['supported']])

    def test_empty_geometry_does_not_trigger(self):
        self.assertEqual([], split_number_bands([], (0, 0), 100))
        self.assertFalse(needs_primary_recheck([], 100))

    def test_conflicting_ocr_at_one_position_is_not_a_column(self):
        bands = split_number_bands(labels(110, [1, 10, 100], [90, 90, 90]), (0, 0), 100)
        self.assertFalse(bands[0]['supported'])

    def test_recovers_outer_scale_even_when_inner_scale_was_consistent(self):
        ticks = [dict(angle=math.radians(d) % (2 * math.pi),
                      centroid=(100 * math.cos(math.radians(d)), 100 * math.sin(math.radians(d))),
                      is_major=True) for d in range(135, 406, 9)]
        inner = labels(55, [0, 29, 58, 87, 116, 145])
        outer = labels(115, [0, .2, .4, .6, .8, 1])
        with patch.object(scale, 'read_scale_numbers', return_value=inner), \
                patch.object(scale, '_read_scale_numbers_tiled', return_value=inner + outer) as tiled, \
                patch.object(scale.tick_detect, 'detect_scale_ticks', return_value=ticks), \
                patch.object(scale.vlm_scale_value, 'read_min_max') as vlm:
            diagnostics, points = {}, {}
            result = scale.detect_scale_values(np.zeros((300, 300, 3), dtype=np.uint8), ticks,
                                               (0, 0), use_vlm=False, diagnostics_out=diagnostics,
                                               numbered_points_out=points)
        self.assertEqual((0, 1), (result['min_value'], result['max_value']))
        self.assertEqual(1, max(p['value'] for p in points['bound']))
        self.assertEqual('selected', diagnostics['primary_scale']['status'])
        tiled.assert_called_once()
        vlm.assert_not_called()

    def test_inner_single_scale_keeps_value_but_lowers_confidence(self):
        ticks = [dict(angle=math.radians(d) % (2 * math.pi),
                      centroid=(100 * math.cos(math.radians(d)), 100 * math.sin(math.radians(d))),
                      is_major=True) for d in range(135, 406, 9)]
        numbers = labels(60, [0, 30, 60, 90, 120, 150])
        with patch.object(scale, 'read_scale_numbers', return_value=numbers), \
                patch.object(scale, '_read_scale_numbers_tiled', return_value=numbers), \
                patch.object(scale.tick_detect, 'detect_scale_ticks', return_value=ticks):
            result = scale.detect_scale_values(np.zeros((300, 300, 3), dtype=np.uint8), ticks,
                                               (0, 0), use_vlm=False)
        self.assertEqual(150, result['max_value'])
        self.assertFalse(result['is_confident'])

    def test_inconsistent_outer_column_never_falls_back_to_inner_value(self):
        ticks = [dict(angle=math.radians(d) % (2 * math.pi),
                      centroid=(100 * math.cos(math.radians(d)), 100 * math.sin(math.radians(d))),
                      is_major=True) for d in range(135, 406, 9)]
        inner = labels(55, [0, 29, 58, 87, 116, 145])
        outer = labels(115, [0, .2, .4, .6, .8, 6])
        for use_vlm in (False, True):
            with self.subTest(use_vlm=use_vlm), \
                    patch.object(scale, 'read_scale_numbers', return_value=inner), \
                    patch.object(scale, '_read_scale_numbers_tiled', return_value=outer), \
                    patch.object(scale.tick_detect, 'detect_scale_ticks', return_value=ticks), \
                    patch.object(scale.vlm_scale_value, 'read_min_max') as vlm:
                diagnostics, points = {}, {}
                result = scale.detect_scale_values(np.zeros((300, 300, 3), dtype=np.uint8), ticks,
                                                   (0, 0), use_vlm=use_vlm,
                                                   diagnostics_out=diagnostics, numbered_points_out=points)
                self.assertIsNone(result)
                self.assertEqual('unverified_outer', diagnostics['primary_scale']['status'])
                self.assertEqual({}, points)
                vlm.assert_not_called()

    def test_failed_expanded_ocr_retains_single_inner_scale(self):
        numbers = labels(60, [0, 30, 60, 90, 120, 150])
        ticks = [dict(centroid=(100, 0))]
        with patch.object(scale, '_read_scale_numbers_tiled', side_effect=RuntimeError('OCR unavailable')):
            diagnostics, result, points = scale._recheck_primary_scale(None, numbers, ticks, (0, 0), 12, 3)
        self.assertEqual('retained', diagnostics['status'])
        self.assertTrue(diagnostics['ocr_failed'])
        self.assertIsNone(result)
        self.assertIsNone(points)

    def test_failed_optional_grid_attempt_does_not_raise(self):
        inner = labels(55, [0, 29, 58, 87, 116, 145])
        outer = labels(115, [0, .2, .4, .6, .8, 1])
        with patch.object(scale, '_read_scale_numbers_tiled', return_value=outer), \
                patch.object(scale, '_run_ocr_tick', side_effect=RuntimeError('invalid grid')):
            diagnostics, result, points = scale._recheck_primary_scale(
                None, inner, [dict(centroid=(100, 0))], (0, 0), 12, 3)
        self.assertEqual('unverified_outer', diagnostics['status'])
        self.assertIsNone(result)
        self.assertIsNone(points)


if __name__ == '__main__':
    unittest.main()
