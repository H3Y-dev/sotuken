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


class TestRatioToValueWithCalibration(unittest.TestCase):
    """
    T2-1: 両端（val_min/val_max）だけでなく、OCRで対応付いた中間の目盛り点も
    使った区分線形補間で、可動鉄片形などの非線形スケールに対応する。
    """

    def test_matches_linear_interpolation_when_only_two_points(self):
        """較正点が両端の2点だけなら、従来の線形補間と完全に一致する"""
        calibration = [(0.0, 0.0), (1.0, 100.0)]
        for ratio in (0.0, 0.25, 0.6, 1.0):
            self.assertAlmostEqual(
                meter_reader.ratio_to_value(ratio, 0.0, 100.0, calibration=calibration),
                meter_reader.ratio_to_value(ratio, 0.0, 100.0),
                places=6,
            )

    def test_none_calibration_is_identical_to_plain_linear(self):
        self.assertAlmostEqual(
            meter_reader.ratio_to_value(0.6, 0.0, 5.0, calibration=None),
            meter_reader.ratio_to_value(0.6, 0.0, 5.0),
        )

    def test_interior_point_bends_the_interpolation(self):
        # 可動鉄片形のような、低い側が圧縮されたスケール:
        # ratio 0〜0.2 の間に値0〜80が詰まっている
        calibration = [(0.2, 80.0)]
        value_at_bend = meter_reader.ratio_to_value(
            0.2, 0.0, 100.0, calibration=calibration)
        self.assertAlmostEqual(value_at_bend, 80.0, places=6)

        # 較正点が無い（=線形補間）なら ratio 0.2 は値20のはず
        linear_value = meter_reader.ratio_to_value(0.2, 0.0, 100.0)
        self.assertAlmostEqual(linear_value, 20.0, places=6)

    def test_nonlinear_scale_is_more_accurate_than_linear(self):
        """複数の較正点を使った補間のほうが、2点線形補間より真値に近いこと"""
        true_calibration = [
            (0.0, 0.0), (0.1, 10.0), (0.3, 40.0), (0.6, 75.0), (1.0, 100.0),
        ]
        # (0.3, 40.0) と (0.6, 75.0) の間、ratio=0.45 の真値
        true_value_at_045 = 40.0 + (75.0 - 40.0) * (0.45 - 0.3) / (0.6 - 0.3)

        via_calibration = meter_reader.ratio_to_value(
            0.45, 0.0, 100.0, calibration=true_calibration[1:-1])
        via_linear = meter_reader.ratio_to_value(0.45, 0.0, 100.0)

        self.assertAlmostEqual(via_calibration, true_value_at_045, places=6)
        self.assertLess(
            abs(via_calibration - true_value_at_045),
            abs(via_linear - true_value_at_045),
        )

    def test_non_monotonic_outlier_is_excluded_without_crashing(self):
        """OCR誤読で値が逆転した外れ値が混ざっていても、例外にならず除外される"""
        calibration = [
            (0.2, 20.0),
            (0.5, 5.0),   # 外れ値: 直前より小さい値
            (0.8, 80.0),
        ]
        value = meter_reader.ratio_to_value(0.5, 0.0, 100.0, calibration=calibration)
        # 外れ値(5.0)がそのまま採用されていないこと
        self.assertNotAlmostEqual(value, 5.0, places=1)
        # 外れ値を除いた(0.2,20.0)→(0.8,80.0)の線形補間に近いはず
        self.assertAlmostEqual(value, 50.0, places=1)

    def test_monotonic_but_wrong_ocr_value_is_excluded(self):
        """
        OCRが「30」を「38」と誤読したケース（2026-08-28、meter2.jpgで実際に
        発生・退行を確認）。20 < 38 < 40 なので単調増加という条件だけは
        満たしてしまうが、他の点が10刻みの等差数列（0,10,20,40,...,100）に
        なっているので、38だけが刻みからずれていると検出できるはずである。
        """
        calibration = [
            (0.1, 10.0), (0.2, 20.0), (0.3, 38.0), (0.4, 40.0),
            (0.5, 50.0), (0.6, 60.0), (0.7, 70.0), (0.8, 80.0),
        ]
        value_at_030 = meter_reader.ratio_to_value(
            0.3, 0.0, 100.0, calibration=calibration)
        # 38がそのまま採用されていれば38.0に近くなるはずだが、
        # 20と40の間を等差数列として補間した30.0に近い値になるべき
        self.assertLess(abs(value_at_030 - 30.0), abs(value_at_030 - 38.0))
        self.assertAlmostEqual(value_at_030, 30.0, delta=1.0)

    def test_result_stays_monotonic_even_with_outliers(self):
        calibration = [(0.2, 20.0), (0.5, 5.0), (0.8, 80.0)]
        values = [
            meter_reader.ratio_to_value(r, 0.0, 100.0, calibration=calibration)
            for r in (0.0, 0.2, 0.4, 0.5, 0.6, 0.8, 1.0)
        ]
        for a, b in zip(values, values[1:]):
            self.assertLessEqual(a, b)


class TestCalibrationToRatios(unittest.TestCase):
    """OCRで対応付いた目盛りの(角度, 値)を、ratio_to_valueが使える(ratio, 値)へ変換する"""

    # TestArcRatioWithTickAngles と同じ幾何（ゼロ点135度→フル点45度、270度側）
    ZERO = math.radians(135)
    FULL = math.radians(45)

    def _ticks(self):
        return [math.radians((135 + i * 270.0 / 20) % 360) for i in range(21)]

    def test_converts_angles_along_the_scale_to_ratios(self):
        # ゼロ(135°)から時計回りに225°進んだ位置(=45°=フル)の中間、225°はratio=1/3
        calibration_angles = [(math.radians(225), 50.0)]
        result = meter_reader.calibration_to_ratios(
            calibration_angles, self.ZERO, self.FULL, tick_angles=self._ticks())
        self.assertEqual(len(result), 1)
        ratio, value = result[0]
        self.assertAlmostEqual(ratio, 1.0 / 3.0, places=6)
        self.assertAlmostEqual(value, 50.0)

    def test_returns_empty_when_direction_cannot_be_resolved(self):
        """走査方向を確定できる目盛り角度が無ければ、安全に空リストへフォールバックする"""
        result = meter_reader.calibration_to_ratios(
            [(math.radians(225), 50.0)], self.ZERO, self.FULL, tick_angles=None)
        self.assertEqual(result, [])

    def test_returns_empty_for_no_calibration(self):
        self.assertEqual(
            meter_reader.calibration_to_ratios(None, self.ZERO, self.FULL), [])
        self.assertEqual(
            meter_reader.calibration_to_ratios([], self.ZERO, self.FULL), [])


if __name__ == '__main__':
    unittest.main()
