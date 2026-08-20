"""
meter_reader（針の角度→数値の変換）のテスト。

角度から値を求める部分は、画像に依存しない純粋な計算なので
実画像なしで検証できる。ここが壊れると全ての読み取り結果が
静かにずれるため、テストで固定しておく。

実行:
    venv\\Scripts\\python.exe -m unittest discover -s tests
"""
import math
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import meter_reader


class TestArcRatio(unittest.TestCase):
    """ゼロ点・フルスケール点・針の角度から、目盛り上の位置比率を求める"""

    def test_needle_at_zero_is_ratio_0(self):
        self.assertAlmostEqual(
            meter_reader.arc_ratio(math.pi, math.pi, 0.0), 0.0, places=6)

    def test_needle_at_fullscale_is_ratio_1(self):
        self.assertAlmostEqual(
            meter_reader.arc_ratio(0.0, math.pi, 0.0), 1.0, places=6)

    def test_needle_at_midpoint_is_ratio_half(self):
        # ゼロ=180°, フル=0°, 針=90°。短い方の弧（180°）の真ん中にあたる
        self.assertAlmostEqual(
            meter_reader.arc_ratio(math.pi / 2, math.pi, 0.0), 0.5, places=6)

    def test_quarter_position(self):
        # ゼロ=180°, フル=0°, 針=135° → ゼロから45°進んだ位置＝1/4
        self.assertAlmostEqual(
            meter_reader.arc_ratio(math.radians(135), math.pi, 0.0), 0.25, places=6)

    def test_direction_is_inferred_from_shorter_arc(self):
        # 反時計回りに進むメーター（ゼロが右、フルが左）でも正しく0.5になる
        self.assertAlmostEqual(
            meter_reader.arc_ratio(math.pi / 2, 0.0, math.pi), 0.5, places=6)

    def test_arc_crossing_the_180_degree_boundary(self):
        # ゼロ=135°, フル=-135°(=225°)。180°をまたぐ90°の弧の中点は180°
        ratio = meter_reader.arc_ratio(
            math.pi, math.radians(135), math.radians(-135))
        self.assertAlmostEqual(ratio, 0.5, places=6)

    def test_ratio_is_clamped_into_valid_range(self):
        # 針がスケール範囲の外を向いていても、比率は0..1に収める
        ratio = meter_reader.arc_ratio(
            math.radians(-90), math.radians(135), math.radians(-135))
        self.assertGreaterEqual(ratio, 0.0)
        self.assertLessEqual(ratio, 1.0)


class TestRatioToValue(unittest.TestCase):
    """比率と目盛りの最小値・最大値から実際の測定値を求める"""

    def test_maps_ratio_onto_value_range(self):
        self.assertAlmostEqual(meter_reader.ratio_to_value(0.0, 0.0, 5.0), 0.0)
        self.assertAlmostEqual(meter_reader.ratio_to_value(1.0, 0.0, 5.0), 5.0)
        self.assertAlmostEqual(meter_reader.ratio_to_value(0.6, 0.0, 5.0), 3.0)

    def test_supports_ranges_not_starting_at_zero(self):
        self.assertAlmostEqual(meter_reader.ratio_to_value(0.5, 20.0, 40.0), 30.0)


if __name__ == '__main__':
    unittest.main()
