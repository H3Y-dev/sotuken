import os
import tempfile
import unittest

from manager.batch import calculate_file_hash
from manager.image_store import image_path_for, store_image, verify_stored_image


class TestImageStore(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.images_dir = os.path.join(self.temp_dir.name, "images")
        self.source_path = os.path.join(self.temp_dir.name, "meter.JPG")
        self.image_bytes = b"original meter image bytes"
        with open(self.source_path, "wb") as image_file:
            image_file.write(self.image_bytes)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_stores_image_at_content_hash_path_without_changing_bytes(self):
        image_sha256 = calculate_file_hash(self.source_path)

        stored_path = store_image(self.source_path, self.images_dir)

        self.assertEqual(
            stored_path,
            image_path_for(image_sha256, self.images_dir, ".jpg"),
        )
        self.assertTrue(os.path.isabs(stored_path))
        with open(stored_path, "rb") as stored_file:
            self.assertEqual(stored_file.read(), self.image_bytes)
        self.assertEqual(calculate_file_hash(stored_path), image_sha256)

    def test_storing_same_image_twice_is_idempotent(self):
        first_path = store_image(self.source_path, self.images_dir)
        second_path = store_image(self.source_path, self.images_dir)

        self.assertEqual(first_path, second_path)
        self.assertEqual(os.listdir(self.images_dir), [os.path.basename(first_path)])

    def test_verify_stored_image_detects_modified_contents(self):
        stored_path = store_image(self.source_path, self.images_dir)

        with open(stored_path, "wb") as stored_file:
            stored_file.write(b"modified meter image bytes")

        self.assertFalse(verify_stored_image(stored_path))

    def test_rejects_unsupported_extension(self):
        source_path = os.path.join(self.temp_dir.name, "meter.gif")
        with open(source_path, "wb") as image_file:
            image_file.write(self.image_bytes)

        with self.assertRaises(ValueError):
            store_image(source_path, self.images_dir)

    def test_raises_for_missing_source_path(self):
        missing_path = os.path.join(self.temp_dir.name, "missing.jpg")

        with self.assertRaises(FileNotFoundError):
            store_image(missing_path, self.images_dir)


if __name__ == "__main__":
    unittest.main()
