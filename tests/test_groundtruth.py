import json
import os
import subprocess
import sys
import tempfile
import unittest

from manager.groundtruth import export_groundtruth
from manager.record import ImageTruth
from manager.storage import Storage


class TestGroundtruth(unittest.TestCase):

    def test_export_groundtruth_writes_image_hash_keyed_json(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = os.path.join(temp_dir, "groundtruth.json")
            truth = ImageTruth(
                image_sha256="a" * 64,
                operator_value=12.5,
                operator_note="目視確認済み",
                scale_min=0.0,
                scale_max=20.0,
                entered_at="2026-09-20T12:00:00",
            )

            export_groundtruth([truth], output_path)

            with open(output_path, encoding="utf-8") as output_file:
                actual = json.load(output_file)
            self.assertEqual(
                {
                    "a" * 64: {
                        "operator_value": 12.5,
                        "operator_note": "目視確認済み",
                        "scale_min": 0.0,
                        "scale_max": 20.0,
                        "entered_at": "2026-09-20T12:00:00",
                    }
                },
                actual,
            )

    def test_cli_exports_stored_image_truths(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = os.path.join(temp_dir, "manager.db")
            output_path = os.path.join(temp_dir, "groundtruth.json")
            Storage(db_path).save_image_truth("b" * 64, operator_value=3.5)

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
            )

            self.assertIn("1件のImageTruth", result.stdout)
            with open(output_path, encoding="utf-8") as output_file:
                self.assertEqual(3.5, json.load(output_file)["b" * 64]["operator_value"])


if __name__ == "__main__":
    unittest.main()
