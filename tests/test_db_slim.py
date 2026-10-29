import json
import tempfile
import unittest
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


if __name__ == "__main__":
    unittest.main()
