import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from manager import watcher as watcher_module
from manager.ingest import ingest_result, device_name_from_sidecar
from manager.sidecar import SidecarMetadata
from manager.storage import Storage


class TestDeviceNameFromSidecar(unittest.TestCase):

    def test_uses_sidecar_device_name(self):
        sidecar = SidecarMetadata(device_name="P-101", operator_value=1.5)
        self.assertEqual("P-101", device_name_from_sidecar(sidecar))

    def test_falls_back_to_unknown_without_sidecar(self):
        self.assertEqual("unknown", device_name_from_sidecar(None))


class TestIngestResult(unittest.TestCase):

    def setUp(self):
        self.storage = Storage(":memory:")

    def test_saves_successful_result(self):
        row_id = ingest_result(
            self.storage, "C:/tmp/a.jpg",
            SidecarMetadata(device_name="P-101", operator_value=2.0),
            {"stage": "ok", "value": 1.25, "angle_deg": 30.0},
        )

        readings = self.storage.get_all_readings()
        self.assertEqual(1, len(readings))
        self.assertEqual(row_id, readings[0].id)
        self.assertEqual("P-101", readings[0].device_name)
        self.assertEqual(1.25, readings[0].value)
        self.assertEqual("ok", readings[0].stage)
        self.assertEqual(2.0, readings[0].raw_data.get("operator_value"))

    def test_saves_failed_result_too(self):
        ingest_result(
            self.storage, "C:/tmp/b.jpg", None,
            {"stage": "needle_not_found", "value": None, "error": "no needle"},
        )

        readings = self.storage.get_all_readings()
        self.assertEqual(1, len(readings))
        self.assertIsNone(readings[0].value)
        self.assertEqual("needle_not_found", readings[0].stage)
        self.assertEqual("unknown", readings[0].device_name)

    def test_drops_ticks_from_saved_payload(self):
        ingest_result(
            self.storage, "C:/tmp/c.jpg", None,
            {"stage": "ok", "value": 3.0, "ticks": [1, 2, 3]},
        )

        self.assertNotIn("ticks", self.storage.get_all_readings()[0].raw_data)


class TestWatcherToDatabase(unittest.TestCase):
    """監視フォルダに画像が置かれてからDBに残るまでの通し。"""

    def test_image_dropped_into_watch_dir_reaches_the_database(self):
        storage = Storage(":memory:")
        with tempfile.TemporaryDirectory() as watch_dir:
            image_path = os.path.join(watch_dir, "meter.jpg")
            with open(image_path, "wb") as image_file:
                image_file.write(b"dummy")

            fake_result = {"stage": "ok", "value": 4.5}
            with mock.patch.object(
                    watcher_module, "execute_pipeline", return_value=fake_result):
                folder_watcher = watcher_module.FolderWatcher(
                    watch_dir=watch_dir,
                    on_pipeline_result=lambda path, sidecar, result: ingest_result(
                        storage, path, sidecar, result),
                )
                found = folder_watcher.scan_existing()

        self.assertEqual(1, len(found))
        readings = storage.get_all_readings()
        self.assertEqual(1, len(readings))
        self.assertEqual(4.5, readings[0].value)
        self.assertTrue(readings[0].image_path.endswith("meter.jpg"))


if __name__ == "__main__":
    unittest.main()
