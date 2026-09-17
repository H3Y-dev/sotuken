import os
import tempfile
import unittest
from unittest import mock

from manager.reprocess import reprocess_all, reprocess_image
from manager.storage import Storage


class TestReprocess(unittest.TestCase):

    def setUp(self):
        self.storage = Storage(":memory:")

    def test_reprocess_image_saves_pipeline_version(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            image_path = os.path.join(temp_dir, "meter.jpg")
            with open(image_path, "wb") as image_file:
                image_file.write(b"meter-image")

            with mock.patch("manager.reprocess.cv2.imdecode", return_value=object()), mock.patch(
                "meter_pipeline.read_meter", return_value={"stage": "ok", "value": 12.5}
            ):
                row_id = reprocess_image(self.storage, image_path, "v2")

            readings = self.storage.get_all_readings()
            self.assertEqual(1, len(readings))
            self.assertEqual(row_id, readings[0].id)
            self.assertEqual("v2", readings[0].pipeline_version)
            self.assertEqual(image_path, readings[0].image_path)

    def test_reprocessing_same_image_keeps_both_pipeline_versions(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            image_path = os.path.join(temp_dir, "meter.jpg")
            with open(image_path, "wb") as image_file:
                image_file.write(b"same-meter-image")

            with mock.patch("manager.reprocess.cv2.imdecode", return_value=object()), mock.patch(
                "meter_pipeline.read_meter", return_value={"stage": "ok", "value": 12.5}
            ):
                reprocess_image(self.storage, image_path, "v1")
                reprocess_image(self.storage, image_path, "v2")

            readings = self.storage.get_all_readings()
            self.assertEqual(2, len(readings))
            self.assertEqual({"v1", "v2"}, {reading.pipeline_version for reading in readings})
            self.assertEqual(1, len({reading.image_sha256 for reading in readings}))

    def test_reprocess_all_processes_each_supported_image(self):
        with tempfile.TemporaryDirectory() as images_dir:
            for filename in ("one.jpg", "two.jpeg", "three.png", "ignored.txt"):
                with open(os.path.join(images_dir, filename), "wb") as image_file:
                    image_file.write(filename.encode())

            with mock.patch("manager.reprocess.cv2.imdecode", return_value=object()), mock.patch(
                "meter_pipeline.read_meter", return_value={"stage": "ok", "value": 12.5}
            ) as read_meter:
                succeeded, failed = reprocess_all(self.storage, images_dir, "v3")

            self.assertEqual(3, succeeded)
            self.assertEqual([], failed)
            self.assertEqual(3, read_meter.call_count)
            self.assertEqual(3, len(self.storage.get_all_readings()))

    def test_reprocess_all_continues_after_a_failed_image(self):
        with tempfile.TemporaryDirectory() as images_dir:
            first_path = os.path.join(images_dir, "one.jpg")
            failed_path = os.path.join(images_dir, "two.png")
            for image_path in (first_path, failed_path):
                with open(image_path, "wb") as image_file:
                    image_file.write(b"dummy")

            with mock.patch(
                "manager.reprocess.cv2.imdecode", side_effect=[object(), None]
            ), mock.patch(
                "meter_pipeline.read_meter", return_value={"stage": "ok", "value": 12.5}
            ):
                succeeded, failed = reprocess_all(self.storage, images_dir, "v3")

            self.assertEqual(1, succeeded)
            self.assertEqual([failed_path], failed)
            self.assertEqual(1, len(self.storage.get_all_readings()))


if __name__ == "__main__":
    unittest.main()
