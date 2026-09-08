import json
import os
import tempfile
import unittest

from manager.sidecar import SidecarMetadata, get_sidecar_path, load_sidecar


class TestSidecar(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_get_sidecar_path(self):
        self.assertEqual(
            get_sidecar_path("/path/to/meter_01.jpg"),
            "/path/to/meter_01.json",
        )
        self.assertEqual(
            get_sidecar_path("C:\\data\\test.png"),
            "C:\\data\\test.json",
        )

    def test_load_sidecar_full_values(self):
        img_path = os.path.join(self.temp_dir.name, "meter_01.jpg")
        json_path = os.path.join(self.temp_dir.name, "meter_01.json")
        with open(img_path, "wb") as f:
            f.write(b"fake image")

        data = {
            "local_id": "loc-12345",
            "captured_at": "2026-09-08T01:00:00Z",
            "device_name": "圧力計A",
            "operator_value": 2.5,
            "operator_note": "正常稼働中",
        }
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)

        metadata = load_sidecar(img_path)
        self.assertIsNotNone(metadata)
        self.assertEqual(metadata.local_id, "loc-12345")
        self.assertEqual(metadata.captured_at, "2026-09-08T01:00:00Z")
        self.assertEqual(metadata.device_name, "圧力計A")
        self.assertEqual(metadata.operator_value, 2.5)
        self.assertEqual(metadata.operator_note, "正常稼働中")

    def test_load_sidecar_with_null_and_missing_values(self):
        img_path = os.path.join(self.temp_dir.name, "meter_null.jpg")
        json_path = os.path.join(self.temp_dir.name, "meter_null.json")
        with open(img_path, "wb") as f:
            f.write(b"fake image")

        data = {
            "local_id": "loc-999",
            "captured_at": "2026-09-08T01:05:00Z",
            "device_name": None,
            "operator_value": None,
            "operator_note": None,
        }
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(data, f)

        metadata = load_sidecar(img_path)
        self.assertIsNotNone(metadata)
        self.assertEqual(metadata.local_id, "loc-999")
        self.assertEqual(metadata.captured_at, "2026-09-08T01:05:00Z")
        self.assertIsNone(metadata.device_name)
        self.assertIsNone(metadata.operator_value)
        self.assertIsNone(metadata.operator_note)

    def test_load_sidecar_missing_json_file(self):
        img_path = os.path.join(self.temp_dir.name, "no_json.jpg")
        with open(img_path, "wb") as f:
            f.write(b"fake image")

        metadata = load_sidecar(img_path)
        self.assertIsNone(metadata)

    def test_load_sidecar_broken_json(self):
        img_path = os.path.join(self.temp_dir.name, "broken.jpg")
        json_path = os.path.join(self.temp_dir.name, "broken.json")
        with open(img_path, "wb") as f:
            f.write(b"fake image")
        with open(json_path, "w", encoding="utf-8") as f:
            f.write("not a json")

        metadata = load_sidecar(img_path)
        self.assertIsNone(metadata)


if __name__ == "__main__":
    unittest.main()
