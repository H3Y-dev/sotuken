import os
import sys
import tempfile
import unittest
from unittest import mock

import cv2
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from manager import watcher as watcher_module
from manager.batch import calculate_file_hash
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
        self.assertIsNone(readings[0].overlay_path)

    def test_saves_overlay_for_successful_result(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            image_path = os.path.join(temp_dir, "meter.jpg")
            image = np.zeros((30, 30, 3), dtype=np.uint8)
            encoded_ok, encoded = cv2.imencode(".jpg", image)
            self.assertTrue(encoded_ok)
            encoded.tofile(image_path)

            ingest_result(
                self.storage,
                image_path,
                None,
                {
                    "stage": "ok",
                    "value": 3.0,
                    "center": (15, 15),
                    "ticks": [{"centroid": (20, 15), "is_major": False}],
                },
                os.path.join(temp_dir, "images"),
                os.path.join(temp_dir, "overlays"),
            )

            reading = self.storage.get_all_readings()[0]
            self.assertIsNotNone(reading.overlay_path)
            self.assertTrue(os.path.isfile(os.path.abspath(reading.overlay_path)))

    def test_drops_ticks_from_saved_payload(self):
        ingest_result(
            self.storage, "C:/tmp/c.jpg", None,
            {"stage": "ok", "value": 3.0, "ticks": [1, 2, 3]},
        )

        self.assertNotIn("ticks", self.storage.get_all_readings()[0].raw_data)

    def test_writes_pipeline_log_and_saves_its_relative_path(self):
        old_cwd = os.getcwd()
        with tempfile.TemporaryDirectory() as temp_dir:
            try:
                os.chdir(temp_dir)
                ingest_result(
                    self.storage, "C:/tmp/c.jpg", None,
                    {"stage": "ok", "value": 3.0, "detail": "kept in log"},
                )
                reading = self.storage.get_all_readings()[0]
                self.assertIsNotNone(reading.reading_id)
                self.assertEqual(f"logs/{reading.reading_id}.log", reading.log_path)
                with open(reading.log_path, encoding="utf-8") as log_file:
                    self.assertIn("kept in log", log_file.read())
                self.assertIsNone(reading.overlay_path)
            finally:
                os.chdir(old_cwd)

    def test_saves_image_hash_and_permanent_image_path(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            image_path = os.path.join(temp_dir, "meter.jpg")
            images_dir = os.path.join(temp_dir, "images")
            with open(image_path, "wb") as image_file:
                image_file.write(b"meter-image")

            row_id = ingest_result(
                self.storage, image_path, None, {"stage": "ok", "value": 3.0}, images_dir,
            )

            image_hash = calculate_file_hash(image_path)
            reading = self.storage.get_all_readings()[0]
            expected_path = os.path.join(images_dir, f"{image_hash}.jpg")
            self.assertEqual(row_id, reading.id)
            self.assertEqual(image_hash, reading.image_sha256)
            self.assertEqual(os.path.abspath(expected_path), reading.image_path)
            self.assertTrue(os.path.isfile(expected_path))

    def test_saves_image_truth_when_sidecar_has_truth_values(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            image_path = os.path.join(temp_dir, "meter.jpg")
            with open(image_path, "wb") as image_file:
                image_file.write(b"truth-image")

            ingest_result(
                self.storage,
                image_path,
                SidecarMetadata(scale_min=0.0, scale_max=10.0),
                {"stage": "ok", "value": 3.0},
                os.path.join(temp_dir, "images"),
            )

            truths = self.storage.get_all_image_truths()
            self.assertEqual(1, len(truths))
            self.assertEqual(calculate_file_hash(image_path), truths[0].image_sha256)
            self.assertEqual(0.0, truths[0].scale_min)
            self.assertEqual(10.0, truths[0].scale_max)

    def test_does_not_save_image_truth_when_sidecar_has_no_truth_values(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            image_path = os.path.join(temp_dir, "meter.jpg")
            with open(image_path, "wb") as image_file:
                image_file.write(b"empty-truth-image")

            ingest_result(
                self.storage,
                image_path,
                SidecarMetadata(),
                {"stage": "ok", "value": 3.0},
                os.path.join(temp_dir, "images"),
            )

            self.assertEqual([], self.storage.get_all_image_truths())

    def test_skips_duplicate_image_hash(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            image_path = os.path.join(temp_dir, "meter.jpg")
            with open(image_path, "wb") as image_file:
                image_file.write(b"same-meter-image")

            first_row_id = ingest_result(
                self.storage, image_path, None, {"stage": "ok", "value": 3.0},
                os.path.join(temp_dir, "images"),
            )
            duplicate_row_id = ingest_result(
                self.storage, image_path, None, {"stage": "ok", "value": 3.0},
                os.path.join(temp_dir, "images"),
            )

            self.assertIsNotNone(first_row_id)
            self.assertIsNone(duplicate_row_id)
            self.assertEqual(1, len(self.storage.get_all_readings()))


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
                        storage, path, sidecar, result,
                        os.path.join(watch_dir, "images")),
                )
                found = folder_watcher.scan_existing()

            readings = storage.get_all_readings()
            image_hash = calculate_file_hash(image_path)
            expected_path = os.path.join(watch_dir, "images", f"{image_hash}.jpg")
            self.assertEqual(1, len(found))
            self.assertEqual(1, len(readings))
            self.assertEqual(4.5, readings[0].value)
            self.assertEqual(image_hash, readings[0].image_sha256)
            self.assertEqual(os.path.abspath(expected_path), readings[0].image_path)
            self.assertTrue(os.path.isfile(expected_path))


if __name__ == "__main__":
    unittest.main()
