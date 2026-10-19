import json
import os
import tempfile
import time
import unittest

from manager.watcher import FolderWatcher


class TestFolderWatcher(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.watch_dir = self.temp_dir.name

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_scan_existing_images(self):
        # 監視フォルダ内に既存画像を作成
        img1 = os.path.join(self.watch_dir, "test1.jpg")
        txt1 = os.path.join(self.watch_dir, "test1.txt")
        with open(img1, "wb") as f:
            f.write(b"dummy image 1")
        with open(txt1, "wb") as f:
            f.write(b"dummy text")

        detected = []
        watcher = FolderWatcher(self.watch_dir, on_image_detected=lambda p: detected.append(p))

        # 走査実行
        found = watcher.scan_existing()
        self.assertEqual(len(found), 1)
        self.assertEqual(os.path.abspath(img1), found[0])
        self.assertEqual(detected, [os.path.abspath(img1)])

        # 2回目の走査では既に検出済みのため再検出されないこと（1回のみ検出）
        found_again = watcher.scan_existing()
        self.assertEqual(len(found_again), 0)
        self.assertEqual(len(detected), 1)

    def test_realtime_detection_on_file_created(self):
        detected = []
        watcher = FolderWatcher(self.watch_dir, on_image_detected=lambda p: detected.append(p))
        watcher.start()
        self.assertTrue(watcher.is_running())

        try:
            # フォルダに画像を1枚置く
            img_path = os.path.join(self.watch_dir, "camera_shot.png")
            with open(img_path, "wb") as f:
                f.write(b"dummy png content")

            # イベント検出待機（ポーリング待機）
            timeout = 3.0
            start_t = time.time()
            while time.time() - start_t < timeout:
                if len(detected) > 0:
                    break
                time.sleep(0.1)

            # 1回だけ検出されたことを確認
            self.assertEqual(len(detected), 1)
            self.assertEqual(detected[0], os.path.abspath(img_path))
            self.assertEqual(watcher.detected_images, [os.path.abspath(img_path)])

        finally:
            watcher.stop()
            self.assertFalse(watcher.is_running())

    def test_ignore_non_image_files(self):
        detected = []
        watcher = FolderWatcher(self.watch_dir, on_image_detected=lambda p: detected.append(p))
        watcher.start()

        try:
            non_img = os.path.join(self.watch_dir, "camera_shot.json")
            with open(non_img, "wb") as f:
                f.write(b'{"device_name": "meter"}')

            time.sleep(0.5)
            self.assertEqual(len(detected), 0)
            self.assertEqual(len(watcher.detected_images), 0)

        finally:
            watcher.stop()

    def test_detection_with_sidecar_metadata(self):
        items = []
        watcher = FolderWatcher(
            self.watch_dir,
            on_item_detected=lambda p, s: items.append((p, s)),
        )
        watcher.start()

        try:
            base_name = "20260908T010000_loc-1"
            json_path = os.path.join(self.watch_dir, f"{base_name}.json")
            img_path = os.path.join(self.watch_dir, f"{base_name}.jpg")

            # Android側の仕様に沿ってJSONを先に書き込み、画像を後に配置
            with open(json_path, "w", encoding="utf-8") as f:
                json.dump({
                    "local_id": "loc-1",
                    "captured_at": "2026-09-08T01:00:00Z",
                    "device_name": "圧力計X",
                    "operator_value": 1.23,
                    "operator_note": "正常点検",
                }, f)

            with open(img_path, "wb") as f:
                f.write(b"fake image data")

            timeout = 3.0
            start_t = time.time()
            while time.time() - start_t < timeout:
                if len(items) > 0:
                    break
                time.sleep(0.1)

            self.assertEqual(len(items), 1)
            detected_path, sidecar = items[0]
            self.assertEqual(detected_path, os.path.abspath(img_path))
            self.assertIsNotNone(sidecar)
            self.assertEqual(sidecar.device_name, "圧力計X")
            self.assertEqual(sidecar.operator_value, 1.23)
            self.assertEqual(sidecar.operator_note, "正常点検")
        finally:
            watcher.stop()



    def test_retry_on_permission_error(self):
        import unittest.mock
        img_path = os.path.join(self.watch_dir, "locked_image.jpg")
        with open(img_path, "wb") as f:
            f.write(b"dummy image")

        call_count = 0
        original_open = open

        def mock_open(file, mode="r", *args, **kwargs):
            nonlocal call_count
            if os.path.abspath(str(file)) == os.path.abspath(img_path) and "b" in str(mode) and "w" not in str(mode):
                call_count += 1
                if call_count <= 2:
                    raise PermissionError("[WinError 32] アクセス拒否")
            return original_open(file, mode, *args, **kwargs)

        detected = []
        watcher = FolderWatcher(self.watch_dir, on_image_detected=lambda p: detected.append(p))

        with unittest.mock.patch("builtins.open", side_effect=mock_open):
            with unittest.mock.patch("time.sleep", return_value=None):
                found = watcher.scan_existing()

        self.assertEqual(len(found), 1)
        self.assertEqual(call_count, 3)
        self.assertEqual(detected, [os.path.abspath(img_path)])


if __name__ == "__main__":
    unittest.main()
