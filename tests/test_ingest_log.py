import copy
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from manager.ingest import ingest_result
from manager.storage import Storage


class TestIngestLog(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        previous_dir = os.getcwd()
        os.chdir(self.temp_dir.name)
        self.addCleanup(os.chdir, previous_dir)
        self.storage = Storage(":memory:")
        self.addCleanup(self.storage._conn.close)
        self.result = {
            "stage": "scale_not_found",
            "value": None,
            "processed_img": [[[1, 2, 3]]],
            "ticks": [[1, 2], [3, 4]],
            "center": [100, 120],
            "zero_pt": [20, 80],
            "full_pt": [180, 80],
            "scale_diagnostics": {
                "numbers": [0, 10],
                "attempts": [{"error": "目盛り不足"}],
                "decision": "failed",
            },
        }

    def ingest(self):
        with mock.patch("manager.ingest.calculate_file_hash", return_value="sha256"), \
                mock.patch("manager.ingest.store_image", return_value="stored.png"):
            ingest_result(self.storage, "input.png", None, self.result)
        reading = self.storage.get_all_readings()[0]
        raw_json = self.storage._conn.execute(
            "SELECT raw_data_json FROM meter_readings"
        ).fetchone()[0]
        self.assertIsNone(reading.log_path)
        self.assertIsNone(reading.raw_data["log_path"])
        self.assertFalse(Path("logs").exists())
        return raw_json

    def test_diagnostics_stay_in_db_without_log_or_input_changes(self):
        original = copy.deepcopy(self.result)
        raw_json = self.ingest()

        saved = json.loads(raw_json)
        self.assertNotIn("processed_img", saved)
        self.assertNotIn("ticks", saved)
        self.assertIn("目盛り不足", raw_json)
        self.assertEqual(original, self.result)
        for key, value in original.items():
            if key not in {"processed_img", "ticks"}:
                self.assertEqual(value, saved[key])

    def test_large_processed_image_leaves_db_json_under_one_megabyte(self):
        image = [[[0, 0, 0]] * 2000 for _ in range(2000)]
        self.result["processed_img"] = image
        raw_json = self.ingest()

        self.assertLess(len(raw_json.encode("utf-8")), 1_000_000)
        self.assertIs(image, self.result["processed_img"])
        saved = json.loads(raw_json)
        self.assertNotIn("processed_img", saved)
        self.assertNotIn("ticks", saved)


if __name__ == "__main__":
    unittest.main()
