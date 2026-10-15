"""PC保存経路のデータ欠落（2026-10-15 実証）を再発させない回帰テスト。

A: Web手動読み取りで temp 画像を消すと DB の image_path が消えたファイルを指していた。
"""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from manager.batch import calculate_file_hash
from manager.manager import MeterManager


def _write(path, data=b"meter-image"):
    with open(path, "wb") as f:
        f.write(data)


class TestManualUploadKeepsOriginal(unittest.TestCase):
    """Fix A: 手動読み取りの原画像・ハッシュ・判定が残ること。"""

    def setUp(self):
        self.manager = MeterManager(":memory:")
        self.tmp = tempfile.TemporaryDirectory()
        self.images_dir = os.path.join(self.tmp.name, "images")
        self.temp_path = os.path.join(self.tmp.name, "temp_upload.JPG")
        _write(self.temp_path)
        self.sha = calculate_file_hash(self.temp_path)

    def tearDown(self):
        self.tmp.cleanup()

    def _process(self, result):
        return self.manager.process_image(
            self.temp_path, "Gauge_01", lambda p: result, images_dir=self.images_dir)

    def test_image_survives_temp_removal_with_hash_and_status(self):
        self._process({"stage": "ok", "value": 12.5})
        os.remove(self.temp_path)  # app.py が読み取り後に temp を消す

        reading = self.manager.get_history()[0]
        self.assertTrue(os.path.isfile(reading.image_path))
        self.assertEqual(os.path.abspath(os.path.join(self.images_dir, f"{self.sha}.jpg")),
                         reading.image_path)
        self.assertEqual(self.sha, reading.image_sha256)
        self.assertEqual(self.sha, calculate_file_hash(reading.image_path))
        self.assertEqual("ok", reading.status)
        self.assertEqual("auto", reading.input_method)
        self.assertIsNone(reading.failure_stage)

    def test_low_confidence_is_recorded(self):
        self._process({"stage": "ok", "value": 3.0, "scale_confident": False})
        self.assertEqual("low_confidence", self.manager.get_history()[0].status)

    def test_failure_is_recorded(self):
        self._process({"stage": "needle", "value": None, "error": "no needle"})
        reading = self.manager.get_history()[0]
        self.assertEqual("failed", reading.status)
        self.assertEqual(("needle", "needle_not_detected", "no needle"),
                         (reading.failure_stage, reading.failure_code, reading.failure_detail))
        self.assertEqual(self.sha, reading.image_sha256)

    def test_copy_failure_creates_no_record_and_keeps_temp(self):
        _write(self.images_dir, b"not a directory")  # 保存先が作れない
        with self.assertRaises(OSError):
            self._process({"stage": "ok", "value": 12.5})
        self.assertEqual([], self.manager.get_history())
        self.assertTrue(os.path.isfile(self.temp_path))

    def test_without_images_dir_still_judges_status(self):
        # 既存の偽パス呼び出し（images_dir なし）は従来どおり動き、判定だけ補われる
        self.manager.process_image("/tmp/missing.jpg", "G", lambda p: {"stage": "ok", "value": 1.0})
        reading = self.manager.get_history()[0]
        self.assertEqual("/tmp/missing.jpg", reading.image_path)
        self.assertEqual("ok", reading.status)


if __name__ == "__main__":
    unittest.main()
