"""
評価指標の計算と、パイプラインが異常入力で落ちないことのテスト。

指標の定義を間違えると、精度評価そのものが信用できなくなるので
（そして卒論にそのまま載る数字になるので）ここで固定しておく。
"""
import os
import sys
import unittest

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import evaluate
import meter_pipeline


class TestErrorMetrics(unittest.TestCase):

    def test_absolute_error(self):
        self.assertAlmostEqual(evaluate.absolute_error(3.2, 3.0), 0.2)
        self.assertAlmostEqual(evaluate.absolute_error(2.8, 3.0), 0.2)

    def test_relative_error_is_percent_of_true_value(self):
        # 真値3.0に対して0.3ずれている → 10%
        self.assertAlmostEqual(evaluate.relative_error(3.3, 3.0), 10.0)

    def test_relative_error_is_undefined_at_zero(self):
        # 真値0では相対誤差が定義できない（ゼロ除算）ので None を返す
        self.assertIsNone(evaluate.relative_error(0.1, 0.0))

    def test_reference_error_is_percent_of_full_scale(self):
        # フルスケール5.0(0〜5)に対して0.125ずれている → 2.5%
        self.assertAlmostEqual(
            evaluate.reference_error(3.125, 3.0, 0.0, 5.0), 2.5)

    def test_reference_error_works_at_zero_reading(self):
        # 引用誤差は真値が0でも計算できる。これが主指標に適する理由
        self.assertAlmostEqual(
            evaluate.reference_error(0.25, 0.0, 0.0, 5.0), 5.0)

    def test_reference_error_handles_offset_range(self):
        # レンジ20〜40（フルスケール幅20）で2.0ずれ → 10%
        self.assertAlmostEqual(
            evaluate.reference_error(32.0, 30.0, 20.0, 40.0), 10.0)

    def test_passes_within_jis_class_tolerance(self):
        # JIS C 1102 2.5級 = ±2.5%FS。5Aレンジなら±0.125Aまで合格
        self.assertTrue(evaluate.is_within_tolerance(3.12, 3.0, 0.0, 5.0, 2.5))
        self.assertFalse(evaluate.is_within_tolerance(3.13, 3.0, 0.0, 5.0, 2.5))


class TestSummarize(unittest.TestCase):

    def test_summary_counts_and_averages(self):
        rows = [
            {'stage': 'ok', 'reference_error': 1.0, 'within_tolerance': True},
            {'stage': 'ok', 'reference_error': 3.0, 'within_tolerance': False},
            {'stage': 'center', 'reference_error': None, 'within_tolerance': False},
        ]
        s = evaluate.summarize(rows)
        self.assertEqual(s['total'], 3)
        self.assertEqual(s['read_ok'], 2)
        self.assertEqual(s['within_tolerance'], 1)
        # 読み取れた2件の平均引用誤差
        self.assertAlmostEqual(s['mean_reference_error'], 2.0)
        self.assertEqual(s['failure_stages']['center'], 1)

    def test_summary_of_empty_input_does_not_crash(self):
        s = evaluate.summarize([])
        self.assertEqual(s['total'], 0)
        self.assertIsNone(s['mean_reference_error'])


class TestScaleSourceAccuracy(unittest.TestCase):
    """真値がある評価時は、OCRとVLMのどちらが誤ったかを分ける。"""

    @staticmethod
    def _diagnostics(ocr_range, vlm_range):
        return {
            'ocr': {
                'min_value': None if ocr_range is None else ocr_range[0],
                'max_value': None if ocr_range is None else ocr_range[1],
            },
            'vlm': {
                'min_value': None if vlm_range is None else vlm_range[0],
                'max_value': None if vlm_range is None else vlm_range[1],
            },
        }

    def test_classifies_both_correct(self):
        result = evaluate.classify_scale_sources(
            self._diagnostics((0, 100), (0, 100)), 0, 100)

        self.assertEqual('both_correct', result['code'])
        self.assertTrue(result['ocr_correct'])
        self.assertTrue(result['vlm_correct'])

    def test_classifies_only_ocr_as_wrong(self):
        result = evaluate.classify_scale_sources(
            self._diagnostics((0, 108), (0, 100)), 0, 100)

        self.assertEqual('ocr_only_wrong', result['code'])
        self.assertFalse(result['ocr_correct'])
        self.assertTrue(result['vlm_correct'])

    def test_classifies_only_vlm_as_wrong(self):
        result = evaluate.classify_scale_sources(
            self._diagnostics((0, 100), (0, 108)), 0, 100)

        self.assertEqual('vlm_only_wrong', result['code'])

    def test_classifies_both_wrong(self):
        result = evaluate.classify_scale_sources(
            self._diagnostics((0, 108), (10, 100)), 0, 100)

        self.assertEqual('both_wrong', result['code'])

    def test_marks_vlm_as_not_evaluated_when_disabled_or_unavailable(self):
        result = evaluate.classify_scale_sources(
            self._diagnostics((0, 100), None), 0, 100)

        self.assertEqual('vlm_unavailable', result['code'])
        self.assertTrue(result['ocr_correct'])
        self.assertIsNone(result['vlm_correct'])


class TestPipelineRobustness(unittest.TestCase):

    def test_blank_image_fails_gracefully_instead_of_raising(self):
        # 真っ白な画像には中心も目盛りも針も無い。例外ではなく
        # 「どの段階で失敗したか」を返すことが評価スクリプトの前提になる
        blank = np.full((200, 200, 3), 255, dtype=np.uint8)
        result = meter_pipeline.read_meter(blank, use_vlm=False)
        self.assertIn(
            result['stage'],
            (meter_pipeline.STAGE_CENTER,
             meter_pipeline.STAGE_SCALE,
             meter_pipeline.STAGE_NEEDLE))
        self.assertIsNone(result['value'])


if __name__ == '__main__':
    unittest.main()
