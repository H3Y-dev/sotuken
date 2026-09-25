import json
import os
import subprocess
import sys
import tempfile
import unittest

from manager.groundtruth_eval import build_rows
from manager.record import ImageTruth
from manager.storage import MeterReading, Storage
from evaluate import summarize


class TestGroundtruthEval(unittest.TestCase):

    def test_build_rows_keeps_only_complete_truths_and_failed_readings(self):
        complete_hash = "a" * 64
        failed_hash = "b" * 64
        incomplete_hash = "c" * 64
        readings = [
            MeterReading("meter-a", 12.0, "ok", "a.jpg", image_sha256=complete_hash,
                         reading_id="reading-ok", status="ok"),
            MeterReading("meter-b", None, "needle", "b.jpg", image_sha256=failed_hash,
                         reading_id="reading-failed", status="failed"),
            MeterReading("meter-c", 3.0, "ok", "c.jpg", image_sha256=incomplete_hash,
                         reading_id="reading-incomplete", status="ok"),
            MeterReading("meter-d", 4.0, "ok", "d.jpg", image_sha256="d" * 64,
                         reading_id="reading-unlabeled", status="ok"),
        ]
        truths = [
            ImageTruth(complete_hash, 10.0, None, 0.0, 100.0, "2026-09-20T00:00:00"),
            ImageTruth(failed_hash, 20.0, None, 0.0, 100.0, "2026-09-20T00:00:00"),
            ImageTruth(incomplete_hash, 3.0, None, None, 10.0, "2026-09-20T00:00:00"),
        ]

        rows = build_rows(readings, truths)

        self.assertEqual({"reading-ok", "reading-failed"}, {row["reading_id"] for row in rows})
        failed_row = next(row for row in rows if row["reading_id"] == "reading-failed")
        self.assertEqual("failed", failed_row["stage"])
        self.assertIsNone(failed_row["reference_error"])
        self.assertFalse(failed_row["within_tolerance"])

    def test_build_rows_uses_evaluate_metrics_in_summary(self):
        image_sha256 = "a" * 64
        rows = build_rows(
            [MeterReading("meter", 12.0, "ok", "meter.jpg", image_sha256=image_sha256,
                          reading_id="reading-1", status="ok")],
            [ImageTruth(image_sha256, 10.0, None, 0.0, 100.0, "2026-09-20T00:00:00")],
        )

        self.assertAlmostEqual(2.0, rows[0]["reference_error"])
        self.assertTrue(rows[0]["within_tolerance"])
        summary = summarize(rows)
        self.assertEqual(1, summary["total"])
        self.assertEqual(1, summary["read_ok"])
        self.assertEqual(1, summary["within_tolerance"])
        self.assertAlmostEqual(2.0, summary["mean_reference_error"])

    def test_cli_evaluates_stored_truths(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = os.path.join(temp_dir, "manager.db")
            output_path = os.path.join(temp_dir, "evaluation.json")
            storage = Storage(db_path)
            storage.save_reading(
                "meter", "meter.jpg", {"stage": "ok", "value": 12.0, "status": "ok"},
                image_sha256="a" * 64,
            )
            storage.save_reading(
                "meter", "failed.jpg", {"stage": "needle", "value": None, "status": "failed"},
                image_sha256="b" * 64,
            )
            storage.save_image_truth("a" * 64, operator_value=10.0, scale_min=0.0, scale_max=100.0)
            storage.save_image_truth("b" * 64, operator_value=20.0, scale_min=0.0, scale_max=100.0)

            result = subprocess.run(
                [
                    sys.executable,
                    os.path.join(os.path.dirname(__file__), "..", "manager", "groundtruth_eval.py"),
                    "--db", db_path,
                    "--output", output_path,
                ],
                check=True,
                capture_output=True,
                encoding="utf-8",
                env={**os.environ, "PYTHONIOENCODING": "utf-8"},
            )

            self.assertIn("評価対象: 2 件", result.stdout)
            self.assertIn("読取成功数: 1 件", result.stdout)
            with open(output_path, encoding="utf-8") as output_file:
                self.assertEqual(2, json.load(output_file)["summary"]["total"])

    def test_cli_handles_no_evaluation_targets(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = os.path.join(temp_dir, "manager.db")
            Storage(db_path)

            result = subprocess.run(
                [
                    sys.executable,
                    os.path.join(os.path.dirname(__file__), "..", "manager", "groundtruth_eval.py"),
                    "--db", db_path,
                ],
                check=True,
                capture_output=True,
                encoding="utf-8",
                env={**os.environ, "PYTHONIOENCODING": "utf-8"},
            )

            self.assertIn("評価対象のImageTruthがありません", result.stdout)


if __name__ == "__main__":
    unittest.main()
