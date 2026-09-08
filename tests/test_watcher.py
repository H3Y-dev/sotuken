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


if __name__ == "__main__":
    unittest.main()
