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

    def test_global_only_preserves_original_keys_and_values(self):
        result = meter_pipeline.read_meter(self.img, use_vlm=False, local_read=False)
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

    def test_default_uses_local_read(self):
        result = meter_pipeline.read_meter(self.img, use_vlm=False)
        self.assertIn('value_local', result)
        self.assertEqual(result['read_method'], 'local')
        self.assertAlmostEqual(result['value'], 50)

    def test_cross_check_threshold_and_local_adoption(self):
        for global_value, flagged in ((47.5, False), (47.4999, True)):
            self.mocks['meter_reader.compute_reading'].return_value['value'] = global_value
            result = meter_pipeline.read_meter(self.img, use_vlm=False, local_read=True)
            # 食い違いが2.5%FSを超えたら全体方式の値を採り、要確認にする（2026-10-21の設計変更）
            self.assertAlmostEqual(result['value'], global_value if flagged else 50)
            self.assertEqual(result['read_method'], 'global_flagged' if flagged else 'local')
            self.assertAlmostEqual(result['value_local'], 50)
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
        self.assertIsNone(result['ratio'])
        self.assertIsNone(result['zero_pt'])
        self.assertIsNone(result['full_pt'])
        self.mocks['meter_reader.compute_reading'].assert_not_called()

    def test_local_adoption_preserves_global_geometry_and_ratio(self):
        self.mocks['meter_reader.compute_reading'].return_value['value'] = 48
        result = meter_pipeline.read_meter(self.img, use_vlm=False, local_read=True)
        self.assertAlmostEqual(result['value'], 50)
        self.assertEqual(result['value_global'], 48)
        self.assertEqual(result['ratio'], .5)
        self.assertEqual(result['angle_deg'], 45)
        self.assertEqual(result['min_value'], 0)
        self.assertEqual(result['max_value'], 100)
        self.assertEqual(result['zero_pt'], (15, 10))

    def test_both_readings_fail_without_scale_or_bracket(self):
        self.scale = None
        self.points = []
        result = meter_pipeline.read_meter(self.img, use_vlm=False, local_read=True)
        self.assertEqual(result['stage'], 'scale')
        self.assertIsNone(result['value'])

    def test_local_can_recover_global_needle_calculation_failure(self):
        self.mocks['meter_reader.compute_reading'].return_value = None
        result = meter_pipeline.read_meter(self.img, use_vlm=False, local_read=True)
        self.assertEqual(result['stage'], 'ok')
        self.assertEqual(result['read_method'], 'local')
        self.assertFalse(result['scale_confident'])

    def test_tip_only_preserves_global_method(self):
        result = meter_pipeline.read_meter(self.img, use_vlm=False, local_read=False, needle_angle='tip')
        self.assertEqual(result['read_method'], 'global')
        self.assertEqual(result['value_global'], 50)
        self.assertIsNone(result['value_local'])

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
            meter_pipeline.read_meter(self.img, local_checks=('C',))
        with self.assertRaises(ValueError):
            meter_pipeline.read_meter(self.img, local_checks=('D',))
        with self.assertRaises(ValueError):
            meter_pipeline.read_meter(self.img, needle_angle='other')

    def test_local_checks_eb_pass_on_clean_scale(self):
        # 0, 50, 100 の3点と等間隔目盛り
        ticks = [{'angle': i * math.pi / 10} for i in range(11)]
        self.mocks['tick_detect.detect_scale_ticks'].return_value = ticks
        scale_ret = {
            'zero_pt': {'angle': 0.0}, 'full_pt': {'angle': math.pi},
            'min_value': 0, 'max_value': 100, 'source': 'ocr_tick', 'is_confident': True,
            'ticks': ticks,
            'calibration': [(0.0, 0), (math.pi / 2, 50), (math.pi, 100)],
        }
        # 針は pi/4 (値 25)
        self.mocks['meter_reader.detect_needle'].return_value['direction'] = (math.cos(math.pi / 4), math.sin(math.pi / 4))
        self.mocks['meter_reader.compute_reading'].return_value = {'value': 25.0, 'ratio': 0.25, 'angle_deg': 45.0}
        with patch('meter_pipeline.scale_value_detect.detect_scale_values', return_value=scale_ret):
            result = meter_pipeline.read_meter(self.img, use_vlm=False, local_read=True, local_checks=('E', 'B'))
        self.assertEqual(result['read_method'], 'local')
        self.assertAlmostEqual(result['value'], 25.0)
        self.assertEqual(result['local_checks'], {'E': 'pass', 'B': 'pass', 'C': 'off', 'D': 'off'})

    def test_local_checks_eb_fixes_108_to_100(self):
        # 0, 50, 108(誤読、本来100) の3点と等間隔目盛り
        ticks = [{'angle': i * math.pi / 10} for i in range(11)]
        self.mocks['tick_detect.detect_scale_ticks'].return_value = ticks

        def fake_scale(img, ticks_arg, center, use_vlm=True, diagnostics_out=None, numbered_points_out=None):
            if numbered_points_out is not None:
                numbered_points_out.update(
                    bound=[
                        {'value': 0, 'angle': 0.0, 'score': 0.9},
                        {'value': 50, 'angle': math.pi / 2, 'score': 0.9},
                        {'value': 108, 'angle': math.pi, 'score': 0.85},
                    ],
                    calibration=[(0.0, 0), (math.pi / 2, 50), (math.pi, 108)],
                    ticks=ticks,
                )
            return {
                'zero_pt': {'angle': 0.0}, 'full_pt': {'angle': math.pi},
                'min_value': 0, 'max_value': 108, 'source': 'ocr_tick', 'is_confident': True,
                'ticks': ticks,
                'calibration': [(0.0, 0), (math.pi / 2, 50), (math.pi, 108)],
            }

        # 針は 3*pi/4 (50と100の中間 -> 75.0)
        self.mocks['meter_reader.detect_needle'].return_value['direction'] = (math.cos(3 * math.pi / 4), math.sin(3 * math.pi / 4))
        self.mocks['meter_reader.compute_reading'].return_value = {'value': 81.0, 'ratio': 0.75, 'angle_deg': 135.0}
        with patch('meter_pipeline.scale_value_detect.detect_scale_values', side_effect=fake_scale):
            result = meter_pipeline.read_meter(self.img, use_vlm=False, local_read=True, local_checks=('E', 'B'))
        self.assertEqual(result['local_checks'], {'E': 'fixed', 'B': 'fixed', 'C': 'off', 'D': 'off'})
        self.assertAlmostEqual(result['value_local'], 75.0)

    def test_local_checks_e_only_fails_and_falls_back_to_global(self):
        # Eのみで108を検出した場合、修正できないのでfailになり全体方式へフォールバックする
        ticks = [{'angle': i * math.pi / 10} for i in range(11)]
        self.mocks['tick_detect.detect_scale_ticks'].return_value = ticks

        def fake_scale(img, ticks_arg, center, use_vlm=True, diagnostics_out=None, numbered_points_out=None):
            if numbered_points_out is not None:
                numbered_points_out.update(
                    bound=[
                        {'value': 0, 'angle': 0.0, 'score': 0.9},
                        {'value': 50, 'angle': math.pi / 2, 'score': 0.9},
                        {'value': 108, 'angle': math.pi, 'score': 0.85},
                    ],
                    calibration=[(0.0, 0), (math.pi / 2, 50), (math.pi, 108)],
                    ticks=ticks,
                )
            return {
                'zero_pt': {'angle': 0.0}, 'full_pt': {'angle': math.pi},
                'min_value': 0, 'max_value': 108, 'source': 'ocr_tick', 'is_confident': True,
                'ticks': ticks,
                'calibration': [(0.0, 0), (math.pi / 2, 50), (math.pi, 108)],
            }

        self.mocks['meter_reader.detect_needle'].return_value['direction'] = (math.cos(3 * math.pi / 4), math.sin(3 * math.pi / 4))
        self.mocks['meter_reader.compute_reading'].return_value = {'value': 81.0, 'ratio': 0.75, 'angle_deg': 135.0}
        with patch('meter_pipeline.scale_value_detect.detect_scale_values', side_effect=fake_scale):
            result = meter_pipeline.read_meter(self.img, use_vlm=False, local_read=True, local_checks=('E',))
        self.assertEqual(result['read_method'], 'global')
        self.assertIsNone(result['value_local'])
        self.assertAlmostEqual(result['value'], 81.0)
        self.assertEqual(result['local_checks'], {'E': 'fail', 'B': 'off', 'C': 'off', 'D': 'off'})
