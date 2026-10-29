import json
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

import numpy as np

from manager.manager import MeterManager
from manager.storage import Storage


class TestSlimStorage(unittest.TestCase):
    def setUp(self):
        self.storage = Storage(":memory:")
        self.addCleanup(self.storage._conn.close)

    def test_save_excludes_image_without_mutating_result(self):
        image = np.zeros((3, 4, 3), dtype=np.uint8)
        result = {"value": 12.5, "stage": "ok", "processed_img": image,
                  "center": np.array([1, 2])}
        self.storage.save_reading("meter", "image.png", result)
        raw_json = self.storage._conn.execute(
            "SELECT raw_data_json FROM meter_readings").fetchone()[0]
        self.assertEqual(json.loads(raw_json),
                         {"value": 12.5, "stage": "ok", "center": [1, 2]})
        self.assertIs(result["processed_img"], image)

    def test_include_raw_preserves_default_and_can_skip_column(self):
        self.storage.save_reading("meter", "image.png", {"value": 12.5})
        self.assertEqual(self.storage.get_all_readings()[0].raw_data, {"value": 12.5})
        self.assertEqual(self.storage.get_all_readings(include_raw=True)[0].raw_data,
                         {"value": 12.5})
        queries = []
        self.storage._conn.set_trace_callback(queries.append)
        self.assertIsNone(self.storage.get_all_readings(include_raw=False)[0].raw_data)
        self.assertTrue(queries)
        self.assertFalse(any("raw_data_json" in sql.lower() for sql in queries))
        self.storage._conn.set_trace_callback(None)
        # Malformed legacy data must not be fetched or decoded for the list.
        self.storage._conn.execute("UPDATE meter_readings SET raw_data_json = 'invalid'")
        self.assertIsNone(self.storage.get_all_readings(include_raw=False)[0].raw_data)
        with self.assertRaises(json.JSONDecodeError):
            self.storage.get_all_readings(include_raw=True)

    def test_manager_forwards_flag_and_reuses_loaded_readings(self):
        manager = MeterManager(":memory:")
        self.addCleanup(manager.storage._conn.close)
        manager.storage.save_reading("meter", "image.png", {"value": 12.5})
        self.assertEqual(manager.get_history(include_raw=True)[0].raw_data, {"value": 12.5})
        readings = manager.get_history(include_raw=False)
        self.assertIsNone(readings[0].raw_data)
        with patch.object(manager, "get_history", side_effect=AssertionError("reload")):
            self.assertEqual(manager.format_history_for_ui(readings)[0]["value"], 12.5)
            self.assertEqual(manager.format_history_for_ui([]), [])
        with patch.object(manager, "get_history", return_value=readings) as load:
            manager.format_history_for_ui()
            load.assert_called_once_with(include_raw=False)


class TestSlimDatabaseScript(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.db_path = Path(temp.name) / "small.db"
        self.rows = [
            json.dumps({"value": 12.5, "note": "日本語", "processed_img": [[1, 2], [3, 4]]},
                       ensure_ascii=False),
            json.dumps({"value": 7}),
            json.dumps({"value": 1, "processed_img": [1, 2], "stage": "ok"}),
            json.dumps({"nested": {"value": 3, "processed_img": [1, 2]}}),
            '{"value": invalid, "processed_img": [1, 2]}',
            json.dumps({"value": 4, "processed_img": {"nested": ["escaped\\\"", 2]}}),
            json.dumps({"value": 5, "processed_img": [0] * 40000}),
        ]
        with closing(sqlite3.connect(self.db_path)) as conn, conn:
            conn.execute("CREATE TABLE meter_readings (id INTEGER PRIMARY KEY, raw_data_json TEXT)")
            conn.executemany("INSERT INTO meter_readings (raw_data_json) VALUES (?)",
                             [(row,) for row in self.rows])

    def run_script(self, *options):
        script = Path(__file__).resolve().parents[1] / "tools" / "slim_db.py"
        result = subprocess.run([sys.executable, str(script), str(self.db_path), *options],
                                capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout

    def read_rows(self):
        with closing(sqlite3.connect(self.db_path)) as conn:
            return [row[0] for row in conn.execute(
                "SELECT raw_data_json FROM meter_readings ORDER BY id")]

    def test_slim_removes_only_final_top_level_image(self):
        output = self.run_script()
        rows = self.read_rows()
        self.assertEqual(json.loads(rows[0]), {"value": 12.5, "note": "日本語"})
        self.assertEqual(rows[1:5], self.rows[1:5])
        self.assertEqual(json.loads(rows[5]), {"value": 4})
        self.assertEqual(json.loads(rows[6]), {"value": 5})
        self.assertIn("VACUUM", output)
        self.assertIn("skipped", output)
        self.assertFalse(Path(str(self.db_path) + ".bak").exists())

    def test_dry_run_reports_sizes_without_modifying_database(self):
        before = self.db_path.read_bytes()
        output = self.run_script("--dry-run")
        self.assertEqual(self.db_path.read_bytes(), before)
        self.assertEqual(self.read_rows(), self.rows)
        for row_id, original in enumerate(self.rows, 1):
            self.assertIn(f"id={row_id} bytes={len(original.encode('utf-8'))}", output)
        self.assertIn("->", output)
        self.assertNotIn("VACUUM", output)


if __name__ == "__main__":
    unittest.main()
