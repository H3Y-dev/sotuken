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


class TestArcRatioWithTickAngles(unittest.TestCase):
    """
    目盛り角度を渡した場合、スケールの走査方向を推測せず確定できる。

    これを渡さないと、針がスケールの外（ゼロ点の手前など）を指したときに
    「0〜1に収まる方を採用する」というルールが裏目に出て、逆回りの弧に
    収まってしまい大きく誤った値を返す（2026-08-25に実機写真で確認）。
    """

    # ゼロ点135度 → フル点45度、目盛りは 135→225→315→45 の270度側に並ぶ
    ZERO = math.radians(135)
    FULL = math.radians(45)

    def _ticks(self):
        return [math.radians((135 + i * 270.0 / 20) % 360) for i in range(21)]

    def _ratio(self, needle_deg):
        return meter_reader.arc_ratio(
            math.radians(needle_deg % 360), self.ZERO, self.FULL,
            tick_angles=self._ticks())

    def test_in_range_readings_are_unchanged(self):
        """スケール上の針は従来どおりの比率を返す（退行しないこと）"""
        self.assertAlmostEqual(self._ratio(135), 0.0, places=6)
        self.assertAlmostEqual(self._ratio(225), 1.0 / 3.0, places=6)
        self.assertAlmostEqual(self._ratio(45), 1.0, places=6)

    def test_needle_just_before_zero_clamps_to_zero(self):
        """
        ゼロ点のわずか手前を指す針は0にクランプする。

        目盛り角度を渡さない場合、ここが逆回りに解釈され、0-400スケールで
        22.2（5度手前）や133.3（30度手前）を返していた。
        """
        for offset_deg in (2, 5, 15, 30):
            self.assertAlmostEqual(self._ratio(135 - offset_deg), 0.0, places=6)

    def test_needle_past_fullscale_clamps_to_one(self):
        """フルスケールを行き過ぎた針は1にクランプする"""
        for offset_deg in (2, 5, 20):
            self.assertAlmostEqual(self._ratio(45 + offset_deg), 1.0, places=6)

    def test_falls_back_when_tick_angles_absent(self):
        """目盛り角度が無い場合は従来の挙動を保つ（後方互換）"""
        with_ticks = self._ratio(225)
        without = meter_reader.arc_ratio(
            math.radians(225), self.ZERO, self.FULL)
        self.assertAlmostEqual(with_ticks, without, places=6)


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
