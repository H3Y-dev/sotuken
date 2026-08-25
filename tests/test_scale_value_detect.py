"""
scale_value_detect のうち、画像に依存しない判定部分のテスト。

実行:
    venv\\Scripts\\python.exe -m unittest discover -s tests
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import scale_value_detect


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


if __name__ == '__main__':
    unittest.main()
