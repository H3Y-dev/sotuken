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


if __name__ == '__main__':
    unittest.main()
