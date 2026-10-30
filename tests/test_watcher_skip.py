import os
import contextlib
import io
import json
import tempfile
import unittest
from unittest.mock import Mock, patch

from manager.watcher import FolderWatcher
from manager import watch_inbox
from manager.ingest import ingest_result
from manager.storage import Storage


class TestSkipPipeline(unittest.TestCase):
    def test_skip_in_both_detection_paths(self):
        for scan in (True, False):
            for skip in (True, False, None):
                with self.subTest(scan=scan, skip=skip), tempfile.TemporaryDirectory() as directory:
                    image = os.path.join(directory, "image.png")
                    with open(image, "wb") as stream:
                        stream.write(b"image")
                    detected, item, result = Mock(), Mock(), Mock()
                    kwargs = {} if skip is None else {"skip_pipeline_if": Mock(return_value=skip)}
                    watcher = FolderWatcher(directory, on_image_detected=detected,
                                            on_item_detected=item, on_pipeline_result=result, **kwargs)
                    with patch("manager.watcher.execute_pipeline") as pipeline, \
                            patch.object(watcher, "_refresh_sidecar") as refresh:
                        if scan:
                            watcher.scan_existing()
                            watcher.scan_existing()
                        else:
                            watcher._handle_detected_image(image)
                            watcher._handle_detected_image(image)
                        self.assertEqual(pipeline.call_count, 0 if skip else 1)
                        self.assertEqual(result.call_count, 0 if skip else 1)
                        detected.assert_called_once_with(image)
                        item.assert_called_once_with(image, None)
                        refresh.assert_called_once_with(image)

    def test_watch_inbox_skips_saved_image_and_reloads_hashes_for_live_events(self):
        with tempfile.TemporaryDirectory() as directory:
            incoming = os.path.join(directory, "incoming")
            os.mkdir(incoming)
            old = os.path.join(incoming, "old.png")
            new = os.path.join(incoming, "new.png")
            for path, data in ((old, b"old"), (new, b"new")):
                with open(path, "wb") as stream:
                    stream.write(data)
            db = os.path.join(directory, "manager.db")
            images = os.path.join(directory, "images")
            overlays = os.path.join(directory, "overlays")
            storage = Storage(db)
            result = {"stage": "failed", "error": "test"}
            ingest_result(storage, old, None, result, images, overlays)
            # 監視停止中に届いたJSONも、推論を飛ばして既存記録へ反映する。
            with open(os.path.join(incoming, "old.json"), "w", encoding="utf-8") as stream:
                json.dump({"device_name": "late-device", "operator_value": 12}, stream)
            argv = ["watch_inbox", "--watch-dir", incoming, "--db", db,
                    "--images-dir", images, "--overlays-dir", overlays]
            output = io.StringIO()

            def live_events(watcher):
                # 同じ内容を別名で再投入したイベントも省略する。
                copy = os.path.join(incoming, "copy.png")
                with open(copy, "wb") as stream:
                    stream.write(b"new")
                watcher._handle_detected_image(copy)

            with patch("sys.argv", argv), contextlib.redirect_stdout(output), \
                    patch("manager.watcher.execute_pipeline", return_value=result) as pipeline, \
                    patch.object(FolderWatcher, "start", live_events), \
                    patch.object(FolderWatcher, "stop"), \
                    patch.object(Storage, "get_processed_hashes", autospec=True,
                                 side_effect=Storage.get_processed_hashes) as hashes, \
                    patch("manager.watch_inbox.time.sleep", side_effect=KeyboardInterrupt):
                watch_inbox.main()
            pipeline.assert_called_once_with(new, use_vlm=False)
            self.assertIn("2枚中1枚は処理済みのため推論を飛ばした", output.getvalue())
            self.assertEqual(len(storage.get_all_readings()), 2)
            self.assertEqual(hashes.call_count, 3)  # 起動時・新規取込時・新着イベント時
            saved_old = next(row for row in storage.get_all_readings() if row.device_name == "late-device")
            self.assertIsNotNone(saved_old)


if __name__ == "__main__":
    unittest.main()
