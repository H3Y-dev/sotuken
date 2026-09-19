import json
import os
import subprocess
import sys
import tempfile
import unittest

from evaluate import evaluate_entry
from manager.groundtruth import build_groundtruth_entries, export_groundtruth
from manager.record import ImageTruth
from manager.storage import MeterReading, Storage


class TestGroundtruth(unittest.TestCase):

    def test_build_groundtruth_entries_joins_latest_reading_and_excludes_incomplete_data(self):
        readings = [
            MeterReading("meter", 1.0, "ok", "old.jpg", id=1,
                         timestamp="2026-09-20T10:00:00", image_sha256="complete"),
            MeterReading("meter", 1.0, "ok", "latest.jpg", id=2,
                         timestamp="2026-09-20T11:00:00", image_sha256="complete"),
            MeterReading("meter", 1.0, "ok", "no-truth.jpg", id=3,
                         timestamp="2026-09-20T12:00:00", image_sha256="no-truth"),
        ]
        truths = [
            ImageTruth("complete", 12.5, None, 0.0, 20.0, "2026-09-20T12:00:00"),
            ImageTruth("missing-value", None, None, 0.0, 20.0, "2026-09-20T12:00:00"),
            ImageTruth("missing-min", 1.0, None, None, 20.0, "2026-09-20T12:00:00"),
            ImageTruth("missing-max", 1.0, None, 0.0, None, "2026-09-20T12:00:00"),
            ImageTruth("no-reading", 1.0, None, 0.0, 20.0, "2026-09-20T12:00:00"),
        ]

        entries, excluded_count = build_groundtruth_entries(readings, truths)

        self.assertEqual(
            [{
                "image": "latest.jpg",
                "true_value": 12.5,
                "min_value": 0.0,
                "max_value": 20.0,
                "scope": "round",
            }],
            entries,
        )
        self.assertEqual(5, excluded_count)

    def test_export_groundtruth_writes_evaluate_compatible_array(self):
        entries = [{
            "image": "image.jpg",
            "true_value": 12.5,
            "min_value": 0.0,
            "max_value": 20.0,
            "scope": "round",
        }]
        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = os.path.join(temp_dir, "groundtruth.json")

            export_groundtruth(entries, output_path)

            with open(output_path, encoding="utf-8") as output_file:
                actual = json.load(output_file)
        self.assertEqual(entries, actual)
        self.assertEqual(
            {"image", "true_value", "min_value", "max_value", "scope"},
            set(actual[0]),
        )

    def test_cli_exports_entries_accepted_by_evaluate_entry(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = os.path.join(temp_dir, "manager.db")
            output_path = os.path.join(temp_dir, "groundtruth.json")
            image_path = os.path.join(temp_dir, "captured.jpg")
            storage = Storage(db_path)
            storage.save_reading(
                "meter",
                image_path,
                {"value": 3.5, "stage": "ok"},
                image_sha256="a" * 64,
            )
            storage.save_image_truth(
                "a" * 64,
                operator_value=3.5,
                scale_min=0.0,
                scale_max=20.0,
            )

            result = subprocess.run(
                [
                    sys.executable,
                    os.path.join(os.path.dirname(__file__), "..", "manager", "groundtruth.py"),
                    "--db",
                    db_path,
                    "--output",
                    output_path,
                ],
                check=True,
                capture_output=True,
                encoding="utf-8",
                env={**os.environ, "PYTHONIOENCODING": "utf-8"},
            )

            self.assertIn("1件を", result.stdout)
            self.assertIn("0件を", result.stdout)
            with open(output_path, encoding="utf-8") as output_file:
                entry = json.load(output_file)[0]
            row = evaluate_entry(entry, temp_dir, use_vlm=False)
        self.assertEqual("image_not_found", row["stage"])
        self.assertEqual(3.5, row["true_value"])
        self.assertEqual(0.0, row["true_min"])
        self.assertEqual(20.0, row["true_max"])


if __name__ == "__main__":
    unittest.main()
