import os
import json
import sys
import tempfile
import unittest
from unittest import mock

import cv2
import numpy as np
import qrcode
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from manager import watcher as watcher_module
from manager.batch import calculate_file_hash
from manager.ingest import apply_sidecar, ingest_result, device_name_from_sidecar
from manager.devices import get_device, list_devices
from manager.qr_label import build_payload
from manager.sidecar import SidecarMetadata, load_sidecar
from manager.storage import Storage


class TestDeviceNameFromSidecar(unittest.TestCase):

    def test_uses_sidecar_device_name(self):
        sidecar = SidecarMetadata(device_name="P-101", operator_value=1.5)
        self.assertEqual("P-101", device_name_from_sidecar(sidecar))

    def test_missing_or_unknown_name_uses_legacy_placeholder(self):
        for sidecar in (None, SidecarMetadata(), SidecarMetadata(device_name="unknown")):
            self.assertEqual("unknown", device_name_from_sidecar(sidecar))


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

    def test_does_not_write_pipeline_log_and_saves_null_path(self):
        old_cwd = os.getcwd()
        with tempfile.TemporaryDirectory() as temp_dir:
            try:
                os.chdir(temp_dir)
                ingest_result(
                    self.storage, "C:/tmp/c.jpg", None,
                    {"stage": "ok", "value": 3.0, "detail": "kept in DB"},
                )
                reading = self.storage.get_all_readings()[0]
                self.assertIsNotNone(reading.reading_id)
                self.assertIsNone(reading.log_path)
                self.assertFalse(os.path.exists("logs"))
                self.assertEqual("kept in DB", reading.raw_data["detail"])
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


class TestIngestDeviceIdentity(unittest.TestCase):

    def setUp(self):
        self.storage = Storage(":memory:")
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.image_path = os.path.join(self.temp.name, "incoming", "meter.png")
        os.makedirs(os.path.dirname(self.image_path))
        self.images_dir = os.path.join(self.temp.name, "images")
        self.write_qrs()

    def write_qrs(self, *payloads):
        images = []
        for payload in payloads:
            qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M,
                               box_size=8, border=4)
            qr.add_data(payload)
            qr.make(fit=True)
            images.append(np.array(qr.make_image().convert("RGB")))
        height = max((image.shape[0] for image in images), default=60) + 40
        width = sum(image.shape[1] for image in images) + 40 * (len(images) + 1)
        canvas = np.full((height, width, 3), 255, dtype=np.uint8)
        x = 20
        for image in images:
            h, w = image.shape[:2]
            canvas[20:20 + h, x:x + w] = image
            x += w + 40
        ok, encoded = cv2.imencode(".png", canvas)
        self.assertTrue(ok)
        encoded.tofile(self.image_path)

    def sidecar(self, **values):
        path = os.path.splitext(self.image_path)[0] + ".json"
        with open(path, "w", encoding="utf-8") as stream:
            json.dump(values, stream)
        return load_sidecar(path)

    def ingest(self, sidecar=None, **result):
        return ingest_result(self.storage, self.image_path, sidecar,
                             {"stage": "scale", "value": None, **result}, self.images_dir)

    def row(self):
        with self.storage.connection() as conn:
            cursor = conn.execute("SELECT * FROM meter_readings ORDER BY id DESC")
            return dict(zip((column[0] for column in cursor.description), cursor.fetchone()))

    def test_valid_sidecar_id_takes_priority_without_decoding_qr(self):
        self.write_qrs(build_payload("QR-001", "QR meter"))
        for source, expected in (("qr", "sidecar_qr"), ("manual", "sidecar_manual"),
                                 ("list", "sidecar_list"), (None, "sidecar")):
            with self.subTest(source=source):
                with self.storage.connection() as conn:
                    conn.execute("DELETE FROM meter_readings")
                with mock.patch("manager.ingest.read_device_qr") as decode:
                    self.ingest(self.sidecar(device_id="SC-001", device_name="Sidecar meter",
                                             device_id_source=source))
                decode.assert_not_called()
                row = self.row()
                self.assertEqual(("SC-001", expected, None),
                                 (row["device_id"], row["device_id_source"], row["device_id_issue"]))
                self.assertEqual("Sidecar meter", get_device(self.storage, "SC-001")["device_name"])

    def test_invalid_sidecar_id_falls_back_to_qr_and_keeps_issue(self):
        self.write_qrs(build_payload("QR-001", "QR meter"))
        self.ingest(self.sidecar(device_id="invalid id", device_name="Wrong name"))
        row = self.row()
        self.assertEqual(("QR-001", "QR meter", "pc_qr", "id_invalid"),
                         (row["device_id"], row["device_name"], row["device_id_source"], row["device_id_issue"]))

    def test_qr_only_sets_id_name_source_and_registers_device(self):
        self.write_qrs(build_payload("QR-001", "QR meter"))
        self.ingest()
        row = self.row()
        self.assertEqual(("QR-001", "QR meter", "pc_qr", None),
                         (row["device_id"], row["device_name"], row["device_id_source"], row["device_id_issue"]))
        self.assertEqual("QR meter", get_device(self.storage, "QR-001")["device_name"])

    def test_multiple_device_qrs_leave_id_empty(self):
        self.write_qrs(build_payload("DEV-001", "圧力計1"), build_payload("DEV-002", "圧力計2"))
        self.ingest()
        row = self.row()
        self.assertEqual((None, None, "qr_multiple"),
                         (row["device_id"], row["device_id_source"], row["device_id_issue"]))
        self.assertEqual([], list_devices(self.storage))

    def test_late_sidecar_fills_empty_id_and_clears_issue(self):
        self.ingest()
        before = self.row()
        self.assertEqual("qr_not_found", before["device_id_issue"])
        self.assertIsNone(self.ingest(self.sidecar(device_id="LATE-001", device_name="Late meter",
                                                 device_id_source="manual",
                                                 captured_at="2026-11-04T10:00:00+09:00")))
        row = self.row()
        self.assertEqual(("LATE-001", "sidecar_manual", None, "2026-11-04T01:00:00Z"),
                         (row["device_id"], row["device_id_source"], row["device_id_issue"], row["captured_at"]))
        self.assertEqual("Late meter", get_device(self.storage, "LATE-001")["device_name"])
        for key in ("id", "reading_id", "value", "status", "pipeline_version", "received_at", "image_rel"):
            self.assertEqual(before[key], row[key], key)

    def test_late_conflicting_id_does_not_overwrite_identity_or_register_it(self):
        self.ingest(self.sidecar(device_id="FIRST", device_name="First"))
        self.ingest(self.sidecar(device_id="OTHER", device_name="Other"))
        row = self.row()
        self.assertEqual(("FIRST", "First", "sidecar", "id_conflict"),
                         (row["device_id"], row["device_name"], row["device_id_source"], row["device_id_issue"]))
        self.assertIsNone(get_device(self.storage, "OTHER"))

    def test_late_missing_or_invalid_id_preserves_existing_identity(self):
        self.ingest(self.sidecar(device_id="FIRST", device_name="First"))
        before = self.row()
        for device_id in (None, "unknown", "invalid id", "FIRST"):
            self.ingest(self.sidecar(device_id=device_id))
            for key in ("device_id", "device_id_source", "device_id_issue", "device_name"):
                self.assertEqual(before[key], self.row()[key], key)

    def test_unknown_id_is_null_and_name_is_not_registered(self):
        self.ingest(self.sidecar(device_id="unknown", device_name="unknown"))
        row = self.row()
        self.assertIsNone(row["device_id"])
        self.assertEqual("unknown", row["device_name"])
        self.assertEqual([], list_devices(self.storage))

    def test_new_columns_use_incoming_mtime_relative_image_and_supplied_version(self):
        timestamp = 1793750400
        os.utime(self.image_path, (timestamp, timestamp))
        self.ingest(self.sidecar(captured_at="2026-11-04T10:00:00+09:00"), pipeline_version="v-test")
        row = self.row()
        self.assertEqual("2026-11-04T01:00:00Z", row["captured_at"])
        self.assertEqual(datetime.fromtimestamp(timestamp, timezone.utc),
                         datetime.fromisoformat(row["received_at"].replace("Z", "+00:00")))
        self.assertEqual("images/" + os.path.basename(row["image_path"]), row["image_rel"])
        self.assertEqual("v-test", row["pipeline_version"])
        self.assertTrue(os.path.isfile(self.image_path))

    def test_pipeline_version_falls_back_to_git(self):
        with mock.patch("manager.ingest.subprocess.check_output", return_value="v1.2-3-g123\n"):
            self.ingest()
        self.assertEqual("v1.2-3-g123", self.row()["pipeline_version"])

    def test_git_unavailable_leaves_pipeline_version_null(self):
        with mock.patch("manager.ingest.subprocess.check_output", side_effect=FileNotFoundError):
            self.ingest()
        self.assertIsNone(self.row()["pipeline_version"])

    def test_non_device_qr_sets_issue_without_registering_device(self):
        self.write_qrs("https://example.com/meter")
        self.ingest()
        self.assertEqual("qr_not_device", self.row()["device_id_issue"])
        self.assertEqual([], list_devices(self.storage))

    def test_late_captured_at_updates_even_without_id_and_missing_does_not_erase_it(self):
        self.ingest()
        sha = self.row()["image_sha256"]
        apply_sidecar(self.storage, sha, self.sidecar(captured_at="2026-11-04T10:00:00+09:00"))
        apply_sidecar(self.storage, sha, self.sidecar())
        self.assertEqual("2026-11-04T01:00:00Z", self.row()["captured_at"])

    def test_unknown_name_does_not_register_even_with_valid_id(self):
        self.ingest(self.sidecar(device_id="UNNAMED", device_name="unknown"))
        self.assertEqual("UNNAMED", self.row()["device_id"])
        self.assertEqual([], list_devices(self.storage))

    def test_registration_keeps_existing_name_and_reports_conflict(self):
        self.ingest(self.sidecar(device_id="FIRST", device_name="Original"))
        with mock.patch("builtins.print") as output:
            self.ingest(self.sidecar(device_id="FIRST", device_name="Changed"))
        self.assertEqual("Original", get_device(self.storage, "FIRST")["device_name"])
        self.assertTrue(any("name_conflict" in str(call) for call in output.call_args_list))

    def test_late_id_populates_all_readings_of_same_image(self):
        self.ingest()
        sha = self.row()["image_sha256"]
        self.storage.save_reading("unknown", "x.png", {"stage": "ok", "value": 2}, image_sha256=sha)
        apply_sidecar(self.storage, sha, self.sidecar(device_id="LATE", device_name="Meter"))
        with self.storage.connection() as conn:
            rows = conn.execute("SELECT device_id, device_id_issue FROM meter_readings").fetchall()
        self.assertEqual([("LATE", None), ("LATE", None)], rows)


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
