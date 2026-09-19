import os
import sys
import tempfile
import unittest

import cv2
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from manager.overlay import draw_detection_overlay, save_overlay


class TestDetectionOverlay(unittest.TestCase):

    def test_draws_detection_without_changing_image_size(self):
        image = np.zeros((80, 120, 3), dtype=np.uint8)
        result = {
            "center": (60, 40),
            "ticks": [{"centroid": (70, 40), "is_major": True}],
            "zero_pt": (40, 40),
            "full_pt": (80, 40),
        }

        overlay = draw_detection_overlay(image, result)

        self.assertEqual(image.shape, overlay.shape)
        self.assertFalse(np.array_equal(image, overlay))

    def test_returns_a_copy_when_center_is_missing(self):
        image = np.full((20, 30, 3), 15, dtype=np.uint8)

        overlay = draw_detection_overlay(image, {"center": None})

        self.assertTrue(np.array_equal(image, overlay))
        self.assertIsNot(image, overlay)

    def test_saves_jpeg_and_returns_relative_path(self):
        image = np.zeros((30, 30, 3), dtype=np.uint8)
        result = {
            "center": (15, 15),
            "ticks": [{"centroid": (20, 15), "is_major": False}],
        }
        old_cwd = os.getcwd()
        with tempfile.TemporaryDirectory() as temp_dir:
            try:
                os.chdir(temp_dir)
                relative_path = save_overlay(image, result, "overlays", "reading-1")
                self.assertEqual("overlays/reading-1.jpg", relative_path)
                self.assertTrue(os.path.isfile(os.path.join(temp_dir, relative_path)))
                self.assertIsNotNone(cv2.imread(os.path.join(temp_dir, relative_path)))
            finally:
                os.chdir(old_cwd)

    def test_returns_none_when_center_is_missing(self):
        image = np.zeros((30, 30, 3), dtype=np.uint8)

        self.assertIsNone(save_overlay(image, {"center": None}, "overlays", "reading-1"))


if __name__ == "__main__":
    unittest.main()
