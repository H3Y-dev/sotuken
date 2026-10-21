import math
import unittest
from contextlib import ExitStack
from unittest.mock import patch

import numpy as np

import meter_pipeline


class LocalPipelineTest(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.img = np.zeros((20, 20, 3), dtype=np.uint8)
        mocks = {
            '_detect_center': ((10, 10), 'hough'),
            'orientation.normalize_orientation': (self.img, 0, 0, 0),
            'tick_detect.apply_clahe': self.img,
            'tick_detect.detect_scale_ticks': [],
            'meter_reader.compute_reading': dict(value=50, ratio=.5, angle_deg=45),
            'meter_reader.detect_needle': dict(direction=(math.sqrt(.5), math.sqrt(.5)),
                                              angle_tip=math.pi / 4, needle_confidence={}),
        }
        self.mocks = {name: self.stack.enter_context(patch('meter_pipeline.' + name, return_value=value))
                      for name, value in mocks.items()}
        self.scale = dict(zero_pt=(15, 10), full_pt=(10, 15), min_value=0,
                          max_value=100, source='ocr_tick', is_confident=True)
        self.points = [dict(angle=0, value=0, score=.9),
                       dict(angle=math.pi / 2, value=100, score=.9)]
        self.stack.enter_context(patch('meter_pipeline.scale_value_detect.detect_scale_values',
                                      side_effect=self.detect_scale))

    def detect_scale(self, *args, **kwargs):
        if 'numbered_points_out' in kwargs:
            kwargs['numbered_points_out'].update(bound=self.points)
        return self.scale

    def test_default_result_exactly_preserves_original_keys_and_values(self):
        result = meter_pipeline.read_meter(self.img, use_vlm=False)
        expected = dict(stage='ok', value=50, ratio=.5, angle_deg=45,
                        min_value=0, max_value=100, center=(10, 10),
                        zero_pt=(15, 10), full_pt=(10, 15), n_ticks=0,
                        scale_source='ocr_tick', scale_confident=True,
                        scale_diagnostics=None, center_source='hough', cropped=False,
                        orientation_angle=0, processed_img=self.img, error=None, ticks=[])
        self.assertEqual(result.keys(), expected.keys())
        self.assertIs(result.pop('processed_img'), self.img)
        expected.pop('processed_img')
        self.assertEqual(result, expected)
        self.mocks['meter_reader.detect_needle'].assert_not_called()

    def test_cross_check_threshold_and_local_adoption(self):
        for global_value, flagged in ((47.5, False), (47.4999, True)):
            self.mocks['meter_reader.compute_reading'].return_value['value'] = global_value
            result = meter_pipeline.read_meter(self.img, use_vlm=False, local_read=True)
            self.assertAlmostEqual(result['value'], 50)
            self.assertEqual(result['read_method'], 'local')
            self.assertEqual(result['scale_confident'], not flagged)
            self.assertEqual(result['local_checks'], {key: 'off' for key in 'EBCD'})

    def test_local_recovers_when_global_scale_fails(self):
        self.scale = None
        result = meter_pipeline.read_meter(self.img, use_vlm=False, local_read=True)
        self.assertEqual(result['stage'], 'ok')
        self.assertEqual(result['value'], 50)
        self.assertIsNone(result['value_global'])
        self.assertIsNone(result['min_value'])
        self.assertFalse(result['scale_confident'])

    def test_local_outside_range_falls_back_to_global(self):
        self.mocks['meter_reader.detect_needle'].return_value['direction'] = (-1, 0)
        result = meter_pipeline.read_meter(self.img, use_vlm=False, local_read=True)
        self.assertEqual(result['stage'], 'ok')
        self.assertEqual(result['read_method'], 'global')
        self.assertEqual(result['value'], 50)
        self.assertIsNone(result['value_local'])
        self.assertTrue(result['scale_confident'])

    def test_tip_is_passed_to_both_methods(self):
        self.mocks['meter_reader.detect_needle'].return_value['angle_tip'] = math.pi / 8
        result = meter_pipeline.read_meter(self.img, use_vlm=False, local_read=True, needle_angle='tip')
        self.assertEqual(result['needle_angle_source'], 'tip')
        self.assertAlmostEqual(result['value_local'], 25)
        self.assertEqual(self.mocks['meter_reader.compute_reading'].call_args.kwargs['needle_angle'], 'tip')

    def test_future_checks_and_invalid_angle_are_rejected(self):
        with self.assertRaises(ValueError):
            meter_pipeline.read_meter(self.img, local_checks=('E',))
        with self.assertRaises(ValueError):
            meter_pipeline.read_meter(self.img, needle_angle='other')
