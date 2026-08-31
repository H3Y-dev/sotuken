"""
scale_value_detect のうち、画像に依存しない判定部分のテスト。

実行:
    venv\\Scripts\\python.exe -m unittest discover -s tests
"""
import math
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import scale_value_detect


class TestScaleDiagnostics(unittest.TestCase):
    """OCR候補をLLMで補正した経路を、採用元まで追跡できるようにする。"""

    @staticmethod
    def _ocr_result():
        return {
            'zero_pt': (10, 20),
            'full_pt': (30, 40),
            'min_value': 0.0,
            'max_value': 108.0,
            'n_used': 3,
            'n_total': 4,
        }

    def test_records_hybrid_decision_per_endpoint(self):
        diagnostics = {}
        detected_numbers = [
            {'value': 108.0, 'score': 0.82, 'x': 30.0, 'y': 40.0},
        ]
        with mock.patch.object(
                scale_value_detect.tick_detect, 'apply_clahe', side_effect=lambda img, _clip: img), \
             mock.patch.object(
                 scale_value_detect.tick_detect, 'detect_scale_ticks', return_value=[]), \
             mock.patch.object(
                 scale_value_detect, '_run_ocr_tick',
                 side_effect=lambda *_args, **_kwargs: self._ocr_result()), \
             mock.patch.object(
                 scale_value_detect, 'read_scale_numbers', return_value=detected_numbers), \
             mock.patch.object(
                 scale_value_detect, 'refine_major_ticks_from_numbers', return_value=[]), \
             mock.patch.object(
                 scale_value_detect.vlm_scale_value, 'read_min_max', return_value=(0.0, 100.0)), \
             mock.patch.object(
                 scale_value_detect, 'bind_numbers_to_ticks', return_value=[]), \
             mock.patch.object(
                 scale_value_detect, '_make_occlusion_check', return_value=None), \
             mock.patch.object(
                 scale_value_detect, '_resolve_scale_position', return_value=((50, 60), False)):
            result = scale_value_detect.detect_scale_values(
                object(), [], (0, 0), diagnostics_out=diagnostics)

        self.assertEqual('hybrid', result['source'])
        self.assertEqual(100.0, result['max_value'])
        self.assertEqual(108.0, diagnostics['ocr']['max_value'])
        self.assertEqual(100.0, diagnostics['vlm']['max_value'])
        self.assertEqual(detected_numbers, diagnostics['ocr']['numbers'])
        self.assertEqual('ocr', diagnostics['decision']['min_source'])
        self.assertEqual('vlm', diagnostics['decision']['max_source'])
        self.assertTrue(diagnostics['decision']['fallback_used'])
        self.assertEqual(diagnostics, result['diagnostics'])

    def test_returns_diagnostics_even_when_no_scale_can_be_adopted(self):
        diagnostics = {}
        with mock.patch.object(
                scale_value_detect.tick_detect, 'apply_clahe', side_effect=lambda img, _clip: img), \
             mock.patch.object(
                 scale_value_detect.tick_detect, 'detect_scale_ticks', return_value=[]), \
             mock.patch.object(scale_value_detect, '_run_ocr_tick', return_value=None), \
             mock.patch.object(scale_value_detect, 'read_scale_numbers', return_value=[]), \
             mock.patch.object(
                 scale_value_detect, 'refine_major_ticks_from_numbers', return_value=[]), \
             mock.patch.object(
                 scale_value_detect.vlm_scale_value, 'read_min_max', return_value=None):
            result = scale_value_detect.detect_scale_values(
                object(), [], (0, 0), diagnostics_out=diagnostics)

        self.assertIsNone(result)
        self.assertFalse(diagnostics['ocr']['available'])
        self.assertFalse(diagnostics['vlm']['available'])
        self.assertEqual('no_result', diagnostics['decision']['relation'])


class TestIsPlausibleFullscale(unittest.TestCase):
    """
    フルスケールが「標準数」かどうかの判定。

    OCRが目盛り線を数字と誤読すると 1111 のような現実にはあり得ない
    フルスケール値が出る。2026-08-25の実測では 20260817_134619.jpg が
    20〜1111 と誤検出され、真値45に対し1101.91（引用誤差880%FS）と読み、
    この1枚だけで全体の平均引用誤差が16%FSから60%FSへ跳ね上がっていた。
    """

    def test_accepts_real_instrument_fullscales(self):
        """このプロジェクトで実際に扱っている計器のフルスケールは全て通す"""
        for value in (8, 10, 20, 30, 60, 100, 150, 400):
            self.assertTrue(scale_value_detect.is_plausible_fullscale(value),
                            '実在する計器の値が弾かれた: %s' % value)

    def test_accepts_other_standard_numbers(self):
        """標準数の他の並び（1.5系・2.5系・7.5系、10のべき乗違い）も通す"""
        for value in (1.5, 2.5, 5, 7.5, 50, 120, 300, 750, 1000):
            self.assertTrue(scale_value_detect.is_plausible_fullscale(value),
                            '標準数が弾かれた: %s' % value)

    def test_rejects_ocr_misreadings(self):
        """目盛り線の誤読で生じる中途半端な値は弾く"""
        for value in (1111, 2030, 111, 13, 17, 23, 999):
            self.assertFalse(scale_value_detect.is_plausible_fullscale(value),
                             '誤読値がすり抜けた: %s' % value)

    def test_rejects_non_positive_and_none(self):
        """0・負値・未検出は弾く"""
        for value in (0, -5, None):
            self.assertFalse(scale_value_detect.is_plausible_fullscale(value))


class TestSplitMergedNumberBoxes(unittest.TestCase):
    """幅が不自然に広いOCR数字ボックスだけを安全に分割する。"""

    @staticmethod
    def _candidate(text, left, width):
        return {
            'text': text,
            'value': float(text),
            'x_left': float(left),
            'x_right': float(left + width),
            'y': 100.0,
            'score': 0.9,
        }

    def test_splits_wide_even_digit_box_that_completes_progression(self):
        candidates = [
            self._candidate('10', 700, 107),
            self._candidate('2030', 1056, 450),
            self._candidate('60', 1466, 143),
        ]

        result = scale_value_detect._split_merged_number_boxes(candidates)

        self.assertEqual([10.0, 20.0, 30.0, 60.0],
                         [candidate['value'] for candidate in result])
        self.assertEqual(1168.5, result[1]['x'])
        self.assertEqual(1393.5, result[2]['x'])

    def test_keeps_normal_width_box_intact(self):
        candidates = [
            self._candidate('10', 700, 107),
            self._candidate('2030', 1056, 280),
            self._candidate('60', 1466, 143),
        ]

        result = scale_value_detect._split_merged_number_boxes(candidates)

        self.assertEqual([10.0, 2030.0, 60.0],
                         [candidate['value'] for candidate in result])

    def test_keeps_split_with_leading_zero_intact(self):
        candidates = [
            self._candidate('10', 700, 107),
            self._candidate('2000', 1056, 450),
            self._candidate('60', 1466, 143),
        ]

        result = scale_value_detect._split_merged_number_boxes(candidates)

        self.assertEqual([10.0, 2000.0, 60.0],
                         [candidate['value'] for candidate in result])


class TestDetermineMinMaxMinimumExtension(unittest.TestCase):
    """OCRで読めなかった最小値を、実在する主目盛りへ1本ずつ補完する。"""

    @staticmethod
    def _tick(angle, x, is_major=True):
        return {'angle': angle, 'centroid': (x, 50), 'is_major': is_major}

    def _bound_pairs(self, values):
        return [
            {'value': value, 'angle': index * 0.1,
             'tick': self._tick(index * 0.1, 100 + index * 10)}
            for index, value in enumerate(values)
        ]

    def test_extends_minimum_to_previous_major_tick(self):
        bound_pairs = self._bound_pairs([100.0, 200.0, 300.0, 400.0])
        ticks = [self._tick(-0.1, 90)] + [pair['tick'] for pair in bound_pairs]

        result = scale_value_detect.determine_min_max(bound_pairs, ticks=ticks)

        self.assertEqual(0.0, result['min_value'])
        self.assertEqual((90, 50), result['zero_pt'])

    def test_does_not_extend_below_zero_when_all_observations_are_non_negative(self):
        bound_pairs = self._bound_pairs([0.0, 10.0, 20.0, 30.0])
        ticks = [self._tick(-0.1, 90)] + [pair['tick'] for pair in bound_pairs]

        result = scale_value_detect.determine_min_max(bound_pairs, ticks=ticks)

        self.assertEqual(0.0, result['min_value'])
        self.assertEqual((100, 50), result['zero_pt'])

    def test_does_not_extend_without_previous_major_tick(self):
        bound_pairs = self._bound_pairs([10.0, 20.0, 30.0, 40.0])
        ticks = [pair['tick'] for pair in bound_pairs]

        result = scale_value_detect.determine_min_max(bound_pairs, ticks=ticks)

        self.assertEqual(10.0, result['min_value'])
        self.assertEqual((100, 50), result['zero_pt'])


class TestExtendTicksToNumbers(unittest.TestCase):
    """検出漏れした主目盛りを、数字と格子の両方で確認して補う。"""

    @staticmethod
    def _tick(center, angle, length=10.0):
        radius = 100.0
        return {
            'angle': angle,
            'centroid': (center[0] + radius * math.cos(angle),
                         center[1] + radius * math.sin(angle)),
            'line_angle': angle,
            'length': length,
            'is_major': False,
        }

    def _grid_inputs(self, extra_numbers=()):
        center = (200.0, 150.0)
        period = math.radians(15.0)
        # slot 0 の主目盛りだけを検出漏れとし、数字0だけは残った状態を作る。
        ticks = [self._tick(center, slot * period)
                 for slot in range(1, 20)]
        numbers = [
            {'value': 0.0, 'x': 300.0, 'y': 150.0},
            {'value': 20.0,
             'x': 200.0 + 130.0 * math.cos(5 * period),
             'y': 150.0 + 130.0 * math.sin(5 * period)},
            {'value': 40.0,
             'x': 200.0 + 130.0 * math.cos(10 * period),
             'y': 150.0 + 130.0 * math.sin(10 * period)},
            {'value': 60.0,
             'x': 200.0 + 130.0 * math.cos(15 * period),
             'y': 150.0 + 130.0 * math.sin(15 * period)},
        ]
        return center, numbers + list(extra_numbers), ticks

    def test_synthesizes_missing_major_tick_at_number_position(self):
        center, numbers, ticks = self._grid_inputs()

        result = scale_value_detect.extend_ticks_to_numbers(numbers, ticks, center)

        synthetic = [tick for tick in result if tick.get('synthetic')]
        self.assertEqual(1, len(synthetic))
        self.assertTrue(synthetic[0]['is_major'])
        self.assertAlmostEqual(0.0, synthetic[0]['angle'], places=6)
        self.assertAlmostEqual(300.0, synthetic[0]['centroid'][0], places=6)
        self.assertAlmostEqual(150.0, synthetic[0]['centroid'][1], places=6)

    def test_rejects_number_whose_angle_disagrees_with_grid(self):
        # 値80なら格子は300度を示すが、数字は315度にある。格子だけを根拠に
        # 合成すると誤読でも盤面上へ点を置いてしまうため、12度の安全弁で捨てる。
        bad_number = {
            'value': 80.0,
            'x': 200.0 + 130.0 * math.cos(math.radians(315.0)),
            'y': 150.0 + 130.0 * math.sin(math.radians(315.0)),
        }
        center, numbers, ticks = self._grid_inputs([bad_number])

        result = scale_value_detect.extend_ticks_to_numbers(numbers, ticks, center)

        self.assertEqual(1, sum(tick.get('synthetic', False) for tick in result))

    def test_rejects_number_beyond_grid_extension_limit(self):
        center = (200.0, 150.0)
        period = math.radians(15.0)
        ticks = [self._tick(center, slot * period) for slot in range(1, 11)]
        numbers = [
            {'value': 0.0, 'x': 300.0, 'y': 150.0},
            {'value': 20.0,
             'x': 200.0 + 130.0 * math.cos(3 * period),
             'y': 150.0 + 130.0 * math.sin(3 * period)},
            {'value': 40.0,
             'x': 200.0 + 130.0 * math.cos(6 * period),
             'y': 150.0 + 130.0 * math.sin(6 * period)},
            {'value': 60.0,
             'x': 200.0 + 130.0 * math.cos(9 * period),
             'y': 150.0 + 130.0 * math.sin(9 * period)},
            # 値120の格子位置は270度で数字の位置とも一致するが、検出範囲から
            # 主目盛り2区間を超えているため、外挿の暴走を避けて捨てる。
            {'value': 120.0,
             'x': 200.0 + 130.0 * math.cos(math.radians(270.0)),
             'y': 150.0 + 130.0 * math.sin(math.radians(270.0))},
        ]

        result = scale_value_detect.extend_ticks_to_numbers(numbers, ticks, center)

        self.assertEqual(1, sum(tick.get('synthetic', False) for tick in result))


if __name__ == '__main__':
    unittest.main()
