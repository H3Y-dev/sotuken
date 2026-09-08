import os
import tempfile
import unittest
from unittest.mock import patch, MagicMock

import numpy as np
import cv2

from manager.pipeline_caller import execute_pipeline
from manager.watcher import FolderWatcher


class TestPipelineCaller(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_execute_pipeline_file_not_found(self):
        result = execute_pipeline("non_existent_file.jpg")
        self.assertEqual(result["stage"], "image_not_found")
        self.assertIsNone(result["value"])
        self.assertIn("not found", result["error"])

    def test_execute_pipeline_unreadable_file(self):
        broken_file = os.path.join(self.temp_dir.name, "broken.jpg")
        with open(broken_file, "wb") as f:
            f.write(b"not an image file content")

        result = execute_pipeline(broken_file)
        self.assertEqual(result["stage"], "image_unreadable")
        self.assertIsNone(result["value"])

    @patch("meter_pipeline.read_meter")
    def test_execute_pipeline_success(self, mock_read_meter):
        mock_read_meter.return_value = {
            "stage": "ok",
            "value": 12.34,
            "ratio": 0.5,
            "angle_deg": 180.0,
            "error": None,
        }

        # 正常なダミー画像を作成
        img_path = os.path.join(self.temp_dir.name, "valid_meter.png")
        dummy_img = np.zeros((100, 100, 3), dtype=np.uint8)
        cv2.imwrite(img_path, dummy_img)

        result = execute_pipeline(img_path, use_vlm=False)
        self.assertEqual(result["stage"], "ok")
        self.assertEqual(result["value"], 12.34)
        mock_read_meter.assert_called_once()

    @patch("meter_pipeline.read_meter")
    def test_execute_pipeline_failure_stage(self, mock_read_meter):
        mock_read_meter.return_value = {
            "stage": "center",
            "value": None,
            "error": "Failed to detect center",
        }

        img_path = os.path.join(self.temp_dir.name, "bad_center.png")
        dummy_img = np.zeros((100, 100, 3), dtype=np.uint8)
        cv2.imwrite(img_path, dummy_img)

        result = execute_pipeline(img_path, use_vlm=False)
        self.assertEqual(result["stage"], "center")
        self.assertIsNone(result["value"])
        self.assertEqual(result["error"], "Failed to detect center")


class TestFolderWatcherPipelineIntegration(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.temp_dir.cleanup()

    @patch("manager.watcher.execute_pipeline")
    def test_watcher_auto_runs_pipeline_on_image(self, mock_execute_pipeline):
        mock_execute_pipeline.return_value = {
            "stage": "ok",
            "value": 45.0,
            "error": None,
        }

        received = []
        watcher = FolderWatcher(
            watch_dir=self.temp_dir.name,
            on_pipeline_result=lambda p, s, r: received.append((p, s, r)),
            auto_run_pipeline=True,
        )

        img_path = os.path.join(self.temp_dir.name, "scan_meter.jpg")
        with open(img_path, "wb") as f:
            f.write(b"dummy image")

        found = watcher.scan_existing()
        self.assertEqual(len(found), 1)
        self.assertEqual(len(received), 1)
        res_path, res_sidecar, res_pipeline = received[0]
        self.assertEqual(res_path, os.path.abspath(img_path))
        self.assertEqual(res_pipeline["stage"], "ok")
        self.assertEqual(res_pipeline["value"], 45.0)


if __name__ == "__main__":
    unittest.main()
