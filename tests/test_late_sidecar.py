"""PC保存経路のデータ欠落（2026-10-15 実証）を再発させない回帰テスト。

B: 画像より後に届いた同名JSONの機器名・真値が、どこにも反映されなかった。
"""
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from watchdog.events import FileCreatedEvent, FileModifiedEvent

from manager import watcher as watcher_module
from manager.batch import calculate_file_hash
from manager.ingest import apply_sidecar, ingest_result
from manager.sidecar import SidecarMetadata
from manager.storage import Storage


def _write(path, data=b"meter-image"):
    with open(path, "wb") as f:
        f.write(data)


class TestLateSidecar(unittest.TestCase):
    """Fix B: 画像の後に届いたJSONの機器名・真値を既存記録へ反映すること。"""

    def setUp(self):
        self.storage = Storage(":memory:")
        self.tmp = tempfile.TemporaryDirectory()
        self.watch_dir = self.tmp.name
        self.images_dir = os.path.join(self.watch_dir, "images")
        self.image_path = os.path.join(self.watch_dir, "meter.JPG")
        self.json_path = os.path.join(self.watch_dir, "meter.json")
        _write(self.image_path)
        self.sha = calculate_file_hash(self.image_path)

    def tearDown(self):
        self.tmp.cleanup()

    def _watcher(self, result=None, side_effect=None):
        result = result or {"stage": "ok", "value": 4.5}
        patcher = mock.patch.object(watcher_module, "execute_pipeline",
                                    return_value=result, side_effect=side_effect)
        patcher.start()
        self.addCleanup(patcher.stop)
        return watcher_module.FolderWatcher(
            watch_dir=self.watch_dir,
            on_pipeline_result=lambda p, s, r: ingest_result(
                self.storage, p, s, r, self.images_dir, os.path.join(self.watch_dir, "ov")),
            on_sidecar_updated=lambda p, s: apply_sidecar(
                self.storage, calculate_file_hash(p), s),
        )

    def _write_json(self, payload):
        with open(self.json_path, "w", encoding="utf-8") as f:
            f.write(payload if isinstance(payload, str) else json.dumps(payload))

    def _snapshot(self):
        return [(x.id, x.reading_id, x.value, x.status, x.image_sha256, x.pipeline_version,
                 x.image_path) for x in self.storage.get_all_readings()]

    def test_late_json_updates_device_and_truth_without_new_record(self):
        w = self._watcher()
        w.scan_existing()
        before = self._snapshot()
        self.assertEqual("unknown", self.storage.get_all_readings()[0].device_name)

        self._write_json({"device_name": "DG-03", "operator_value": 4.0, "operator_note": "late"})
        w._handler.on_created(FileCreatedEvent(self.json_path))

        readings = self.storage.get_all_readings()
        self.assertEqual(before, self._snapshot())  # 値・SHA・版・reading_id・件数は不変
        self.assertEqual("DG-03", readings[0].device_name)
        self.assertEqual("corrected", readings[0].input_method)
        self.assertEqual("ok", readings[0].status)
        truths = self.storage.get_all_image_truths()
        self.assertEqual([(self.sha, 4.0, "late")],
                         [(t.image_sha256, t.operator_value, t.operator_note) for t in truths])

    def test_late_json_without_truth_sets_device_only(self):
        w = self._watcher()
        w.scan_existing()
        self._write_json({"device_name": "DG-04", "operator_value": None})
        w._handler.on_created(FileCreatedEvent(self.json_path))

        reading = self.storage.get_all_readings()[0]
        self.assertEqual(("DG-04", "auto"), (reading.device_name, reading.input_method))
        self.assertEqual([], self.storage.get_all_image_truths())

    def test_json_arriving_during_processing_is_applied(self):
        def pipeline(path, use_vlm=False):
            self._write_json({"device_name": "DG-05", "operator_value": 1.0})
            return {"stage": "ok", "value": 1.2}

        w = self._watcher(side_effect=pipeline)
        w.scan_existing()  # sidecar は処理前に読まれるので、この時点では未反映
        w._handler.on_created(FileCreatedEvent(self.json_path))

        readings = self.storage.get_all_readings()
        self.assertEqual(1, len(readings))
        self.assertEqual(("DG-05", "corrected"), (readings[0].device_name, readings[0].input_method))

    def test_empty_or_broken_then_completed_json(self):
        w = self._watcher()
        w.scan_existing()
        for broken in ("", "{\"device_name\": \"DG", "[1, 2]"):
            self._write_json(broken)
            w._handler.on_created(FileCreatedEvent(self.json_path))  # 落ちない
        self.assertEqual("unknown", self.storage.get_all_readings()[0].device_name)

        self._write_json({"device_name": "DG-06", "operator_value": 2.0})
        w._handler.on_modified(FileModifiedEvent(self.json_path))
        self.assertEqual("DG-06", self.storage.get_all_readings()[0].device_name)
        self.assertEqual(1, len(self.storage.get_all_image_truths()))

    def test_json_before_image_detection_is_left_to_image_event(self):
        w = self._watcher()
        self._write_json({"device_name": "DG-07"})
        w._handler.on_created(FileCreatedEvent(self.json_path))  # 画像未検出: 何もしない
        self.assertEqual([], self.storage.get_all_readings())
        w.scan_existing()  # 画像検出時に従来どおり読む
        self.assertEqual("DG-07", self.storage.get_all_readings()[0].device_name)

    def test_failed_status_is_kept_and_input_method_becomes_manual(self):
        w = self._watcher(result={"stage": "needle", "value": None, "error": "x"})
        w.scan_existing()
        self._write_json({"operator_value": 7.0})
        w._handler.on_created(FileCreatedEvent(self.json_path))

        reading = self.storage.get_all_readings()[0]
        self.assertEqual(("failed", "manual"), (reading.status, reading.input_method))
        self.assertEqual("needle", reading.failure_stage)

    def test_partial_json_does_not_erase_existing_truth(self):
        apply_sidecar(self.storage, self.sha, SidecarMetadata(operator_value=5.0, scale_max=10.0))
        apply_sidecar(self.storage, self.sha, SidecarMetadata(operator_note="memo"))
        t = self.storage.get_all_image_truths()[0]
        self.assertEqual((5.0, "memo", 10.0), (t.operator_value, t.operator_note, t.scale_max))

    def test_named_device_is_not_overwritten(self):
        self.storage.save_reading("P-101", "x.jpg", {"stage": "ok", "value": 1.0},
                                  image_sha256=self.sha)
        apply_sidecar(self.storage, self.sha, SidecarMetadata(device_name="OTHER"))
        self.assertEqual("P-101", self.storage.get_all_readings()[0].device_name)

    def test_reprocessed_versions_stay_separate_records(self):
        ingest_result(self.storage, self.image_path, None, {"stage": "ok", "value": 1.0},
                      self.images_dir)
        self.storage.save_reading("unknown", "x.jpg",
                                  {"stage": "ok", "value": 1.1, "pipeline_version": "v2"},
                                  image_sha256=self.sha)
        apply_sidecar(self.storage, self.sha, SidecarMetadata(device_name="DG-08", operator_value=1.0))
        readings = self.storage.get_all_readings()
        self.assertEqual(2, len(readings))
        self.assertEqual({"DG-08"}, {r.device_name for r in readings})
        self.assertEqual({1.0, 1.1}, {r.value for r in readings})

    def test_duplicate_image_reingest_saves_truth_without_new_record(self):
        ingest_result(self.storage, self.image_path, None, {"stage": "ok", "value": 3.0},
                      self.images_dir)
        row = ingest_result(self.storage, self.image_path,
                            SidecarMetadata(device_name="DG-09", operator_value=3.1),
                            {"stage": "ok", "value": 3.0}, self.images_dir)
        self.assertIsNone(row)
        readings = self.storage.get_all_readings()
        self.assertEqual(1, len(readings))
        self.assertEqual(("DG-09", "corrected"), (readings[0].device_name, readings[0].input_method))
        self.assertEqual(3.1, self.storage.get_all_image_truths()[0].operator_value)


if __name__ == "__main__":
    unittest.main()
