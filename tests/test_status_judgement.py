import unittest
from unittest import mock

import numpy as np

import meter_pipeline
from manager.ingest import ingest_result
from manager.record import judge_failure, judge_input_method, judge_status
from manager.sidecar import SidecarMetadata
from manager.storage import Storage


class TestStatusJudgement(unittest.TestCase):

    def test_failure_stages_map_to_fixed_failure_metadata(self):
        cases = {
            "center": ("center", "center_not_found"),
            "scale": ("scale", "scale_range_unresolved"),
            "needle": ("needle", "needle_not_detected"),
        }

        for pipeline_stage, expected in cases.items():
            with self.subTest(pipeline_stage=pipeline_stage):
                self.assertEqual(expected, judge_failure({"stage": pipeline_stage, "value": None})[:2])

    def test_failure_detail_uses_pipeline_error(self):
        self.assertEqual(
            ("scale", "scale_range_unresolved", "OCR timed out"),
            judge_failure({"stage": "scale", "value": None, "error": "OCR timed out"}),
        )

    def test_unmapped_failure_stage_is_unknown(self):
        self.assertEqual(
            ("unknown", "unknown_failure", None),
            judge_failure({"stage": "other", "value": None}),
        )

    def test_success_has_no_failure_metadata(self):
        self.assertEqual(
            (None, None, None),
            judge_failure({"stage": "ok", "value": 1.0, "scale_confident": True}),
        )

    def test_low_confidence_is_not_a_failure(self):
        self.assertEqual(
            (None, None, None),
            judge_failure({"stage": "ok", "value": 1.0, "scale_confident": False}),
        )

    def test_failure_code_is_machine_readable(self):
        failure_code = judge_failure({"stage": "needle", "value": None})[1]
        self.assertRegex(failure_code, r"^[A-Za-z0-9_]+$")
    def test_non_ok_stage_is_failed(self):
        self.assertEqual("failed", judge_status({"stage": "needle", "value": 1.0}))

    def test_none_value_is_failed(self):
        self.assertEqual("failed", judge_status({"stage": "ok", "value": None}))

    def test_unconfident_scale_is_low_confidence(self):
        self.assertEqual(
            "low_confidence", judge_status({"stage": "ok", "value": 1.0, "scale_confident": False})
        )

    def test_confident_scale_is_ok(self):
        self.assertEqual(
            "ok", judge_status({"stage": "ok", "value": 1.0, "scale_confident": True})
        )

    def test_missing_confidence_flag_is_ok(self):
        self.assertEqual("ok", judge_status({"stage": "ok", "value": 1.0}))

    def test_auto_failure_with_operator_value_is_failed_and_manual(self):
        pipeline_result = {"stage": "scale", "value": None}
        self.assertEqual("failed", judge_status(pipeline_result))
        self.assertEqual("manual", judge_input_method(pipeline_result["value"], 12.0))

    def test_input_method_is_auto_for_auto_value_only(self):
        self.assertEqual("auto", judge_input_method(0.0, None))

    def test_input_method_is_manual_for_operator_value_only(self):
        self.assertEqual("manual", judge_input_method(None, 0.0))

    def test_input_method_is_corrected_for_both_values(self):
        self.assertEqual("corrected", judge_input_method(1.0, 2.0))

    def test_input_method_is_auto_when_both_values_are_missing(self):
        self.assertEqual("auto", judge_input_method(None, None))

    @mock.patch("meter_pipeline.meter_reader.compute_reading")
    @mock.patch("meter_pipeline.scale_value_detect.detect_scale_values")
    @mock.patch("meter_pipeline.tick_detect.detect_scale_ticks", return_value=[])
    @mock.patch("meter_pipeline.tick_detect.apply_clahe")
    @mock.patch("meter_pipeline.orientation.normalize_orientation", side_effect=lambda img: (img, 0, 0, 0))
    @mock.patch("meter_pipeline._detect_center", return_value=((5, 5), "hough"))
    def test_pipeline_exposes_scale_confidence(
        self, _detect_center, _normalize, _apply_clahe, _detect_ticks, detect_scale_values, compute_reading
    ):
        detect_scale_values.return_value = {
            "zero_pt": (1, 1), "full_pt": (9, 9), "min_value": 0.0,
            "max_value": 10.0, "is_confident": False,
        }
        compute_reading.return_value = {"value": 1.0, "ratio": 0.1, "angle_deg": 10.0}

        result = meter_pipeline.read_meter(np.zeros((10, 10, 3), dtype=np.uint8), use_vlm=False)

        self.assertIs(result["scale_confident"], False)


class TestIngestStatusJudgement(unittest.TestCase):
    def test_ingest_saves_independent_status_and_input_method(self):
        storage = Storage(":memory:")
        sidecar = SidecarMetadata(device_name="P-101", operator_value=2.0)

        ingest_result(storage, "C:/tmp/a.jpg", sidecar, {"stage": "scale", "value": None})

        saved = storage.get_all_readings()[0].raw_data
        self.assertEqual("failed", saved["status"])
        self.assertEqual("manual", saved["input_method"])
        self.assertEqual("scale", saved["failure_stage"])
        self.assertEqual("scale_range_unresolved", saved["failure_code"])
        self.assertIsNone(saved["failure_detail"])


class TestFailureStageMatchesPipeline(unittest.TestCase):
    """judge_failure の対応表が meter_pipeline の stage 定数と乖離していないこと。

    judge_failure は 'center' / 'scale' / 'needle' という文字列を直接持っている。
    meter_pipeline 側の定数が変わっても、judge_failure は黙って unknown を返すだけで
    エラーにならない。他のテストも同じ文字列をハードコードしているため、
    乖離しても全部緑のまま failure_stage が全件 unknown になる。
    そこで実際の定数を読み込んで突き合わせる。
    """

    def test_pipeline_failure_stages_are_all_mapped(self):
        import meter_pipeline

        for stage in (
            meter_pipeline.STAGE_CENTER,
            meter_pipeline.STAGE_SCALE,
            meter_pipeline.STAGE_NEEDLE,
        ):
            failure_stage, failure_code, _ = judge_failure(
                {"stage": stage, "value": None, "error": "dummy"}
            )
            self.assertEqual(
                stage, failure_stage,
                "meter_pipeline の stage '{}' が judge_failure の対応表から漏れている".format(stage),
            )
            self.assertNotEqual("unknown_failure", failure_code)

    def test_pipeline_ok_stage_is_not_a_failure(self):
        import meter_pipeline

        self.assertEqual(
            (None, None, None),
            judge_failure({"stage": meter_pipeline.STAGE_OK, "value": 1.0}),
        )


if __name__ == "__main__":
    unittest.main()
