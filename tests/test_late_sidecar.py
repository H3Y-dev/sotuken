"""PC保存経路のデータ欠落（2026-10-15 実証）を再発させない回帰テスト。

B: 画像より後に届いた同名JSONの機器名・真値が、どこにも反映されなかった。
"""
import json
import os
import sqlite3
import sys
import tempfile
import threading
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
        self.pipeline = patcher.start()
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

    def test_positional_arguments_keep_their_old_meaning(self):
        # on_sidecar_updated は末尾に追加したので、既存の位置引数呼び出しは意味が変わらない
        w = watcher_module.FolderWatcher(self.watch_dir, None, None, None, True, True, (".png",))
        self.assertEqual((True, True, (".png",), None),
                         (w.auto_run_pipeline, w.use_vlm, w.valid_exts, w.on_sidecar_updated))

    def test_metadata_update_failure_never_inserts_duplicate(self):
        ingest_result(self.storage, self.image_path, None, {"stage": "ok", "value": 3.0},
                      self.images_dir)
        with mock.patch.object(self.storage, "update_reading_metadata",
                               side_effect=sqlite3.OperationalError("database is locked")):
            row = ingest_result(self.storage, self.image_path, SidecarMetadata(device_name="DG-10"),
                                {"stage": "ok", "value": 3.0}, self.images_dir)
        self.assertIsNone(row)
        readings = self.storage.get_all_readings()
        self.assertEqual(1, len(readings))
        self.assertEqual(self.sha, readings[0].image_sha256)

    def test_json_during_event_pipeline_is_applied_without_json_event(self):
        os.remove(self.image_path)
        w = self._watcher(side_effect=lambda p, use_vlm=False: (
            self._write_json({"device_name": "DG-11", "operator_value": 4.0}),
            {"stage": "ok", "value": 4.5})[1])
        _write(self.image_path)
        w._handler.on_created(FileCreatedEvent(self.image_path))  # JSONのイベントは送らない

        readings = self.storage.get_all_readings()
        self.assertEqual(1, self.pipeline.call_count)  # 再OCRしない
        self.assertEqual(1, len(readings))
        self.assertEqual(("DG-11", "corrected"), (readings[0].device_name, readings[0].input_method))

    def test_json_written_during_initial_scan_is_applied_when_watching_starts(self):
        other = os.path.join(self.watch_dir, "next.png")
        _write(other, b"other-image")

        def pipeline(path, use_vlm=False):
            if path.endswith("next.png"):  # meter.JPG の処理後、次の画像の処理中に届く
                self._write_json({"device_name": "DG-12", "operator_value": 2.0})
            return {"stage": "ok", "value": 1.0}

        w = self._watcher(side_effect=pipeline)
        w.scan_existing()

        def device_of_meter():
            return [r.device_name for r in self.storage.get_all_readings()
                    if r.image_sha256 == self.sha]

        self.assertEqual(["unknown"], device_of_meter())  # イベントも事後確認も無い隙間
        w.start()
        try:
            self.assertEqual(["DG-12"], device_of_meter())
        finally:
            w.stop()
        self.assertEqual(2, self.pipeline.call_count)
        self.assertEqual(2, len(self.storage.get_all_readings()))

    def test_concurrent_refresh_keeps_latest_json(self):
        # start() の読み直し（スレッドA）が v1 を読んだ直後に v2 が届き、Observer 側（スレッドB）
        # も読み直す。古い v1 の反映が v2 を上書きしないこと
        storage = Storage(os.path.join(self.watch_dir, "race.db"))  # スレッド間で使うのでファイルDB
        a_holds_v1, b_done = threading.Event(), threading.Event()

        def on_updated(path, sidecar):
            if sidecar.operator_value == 1.0:
                a_holds_v1.set()
                b_done.wait(1.0)  # ロックが無ければBがここで割り込んで先に終わる
            apply_sidecar(storage, calculate_file_hash(path), sidecar)

        self.pipeline = mock.patch.object(
            watcher_module, "execute_pipeline", return_value={"stage": "ok", "value": 1.5}).start()
        self.addCleanup(mock.patch.stopall)
        w = watcher_module.FolderWatcher(
            self.watch_dir,
            on_pipeline_result=lambda p, s, r: ingest_result(storage, p, s, r, self.images_dir),
            on_sidecar_updated=on_updated)
        w.scan_existing()
        self._write_json({"device_name": "DG-13", "operator_value": 1.0})

        thread_a = threading.Thread(target=w._refresh_sidecar, args=(os.path.abspath(self.image_path),))
        thread_a.start()
        self.assertTrue(a_holds_v1.wait(2.0))
        self._write_json({"device_name": "DG-13", "operator_value": 2.0})

        def run_b():
            w._refresh_sidecar(os.path.abspath(self.image_path))
            b_done.set()

        thread_b = threading.Thread(target=run_b)
        thread_b.start()
        thread_a.join(5.0)
        thread_b.join(5.0)

        self.assertEqual(2.0, storage.get_all_image_truths()[0].operator_value)
        self.assertEqual(2.0, w._last_sidecar[os.path.abspath(self.image_path)].operator_value)
        self.assertEqual(1, self.pipeline.call_count)
        self.assertEqual(1, len(storage.get_all_readings()))

    def test_image_detected_during_start_gets_late_json_after_its_row_exists(self):
        # Observer 起動直後に新しい画像を検出してパイプライン中に止まり、その間に JSON が届く。
        # start() の読み直しが記録の無いうちに「反映済み」と記憶してはいけない
        os.remove(self.image_path)
        storage = Storage(os.path.join(self.watch_dir, "start.db"))
        entered, release = threading.Event(), threading.Event()
        worker = []

        def pipeline(path, use_vlm=False):
            entered.set()
            self.assertTrue(release.wait(5))
            return {"stage": "scale", "value": None}

        w = watcher_module.FolderWatcher(
            self.watch_dir,
            on_pipeline_result=lambda p, s, r: ingest_result(storage, p, s, r, self.images_dir),
            on_sidecar_updated=lambda p, s: apply_sidecar(storage, calculate_file_hash(p), s))

        def observer_start():
            _write(self.image_path)
            worker.append(threading.Thread(target=w._handle_detected_image, args=(self.image_path,)))
            worker[0].start()
            self.assertTrue(entered.wait(2))
            self._write_json({"device_name": "DG-START", "operator_value": 12.5})

        observer = mock.Mock()
        observer.start.side_effect = observer_start
        with mock.patch.object(watcher_module, "Observer", return_value=observer),                 mock.patch.object(watcher_module, "execute_pipeline", side_effect=pipeline) as ocr:
            try:
                w.start()
            finally:
                release.set()
                worker[0].join(5)
        self.assertFalse(worker[0].is_alive())

        readings = storage.get_all_readings()
        self.assertEqual(1, ocr.call_count)
        self.assertEqual(1, len(readings))
        self.assertEqual(("DG-START", "manual"), (readings[0].device_name, readings[0].input_method))
        self.assertEqual(12.5, storage.get_all_image_truths()[0].operator_value)

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
