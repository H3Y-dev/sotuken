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
            "scale_min": "0.0",
            "scale_max": 10,
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
        self.assertEqual(metadata.scale_min, 0.0)
        self.assertEqual(metadata.scale_max, 10.0)

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
        self.assertIsNone(metadata.scale_min)
        self.assertIsNone(metadata.scale_max)

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



    def test_load_sidecar_bom_utf8(self):
        img_path = os.path.join(self.temp_dir.name, "meter_bom.jpg")
        json_path = os.path.join(self.temp_dir.name, "meter_bom.json")
        with open(img_path, "wb") as f:
            f.write(b"fake image")

        data = {"device_name": "BOM計器", "operator_value": 100.0}
        with open(json_path, "w", encoding="utf-8-sig") as f:
            json.dump(data, f, ensure_ascii=False)

        metadata = load_sidecar(img_path)
        self.assertIsNotNone(metadata)
        self.assertEqual(metadata.device_name, "BOM計器")
        self.assertEqual(metadata.operator_value, 100.0)

    def test_load_sidecar_nobom_utf8(self):
        img_path = os.path.join(self.temp_dir.name, "meter_nobom.jpg")
        json_path = os.path.join(self.temp_dir.name, "meter_nobom.json")
        with open(img_path, "wb") as f:
            f.write(b"fake image")

        data = {"device_name": "NoBOM計器", "operator_value": 200.0}
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)

        metadata = load_sidecar(img_path)
        self.assertIsNotNone(metadata)
        self.assertEqual(metadata.device_name, "NoBOM計器")
        self.assertEqual(metadata.operator_value, 200.0)


class TestSidecarDeviceMetadata(unittest.TestCase):
    def load_metadata(self, data):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "meter.json")
            with open(path, "w", encoding="utf-8") as stream:
                json.dump(data, stream)
            metadata = load_sidecar(path)
        self.assertIsNotNone(metadata)
        return metadata

    def test_valid_device_ids_are_trimmed_and_preserved(self):
        for device_id in (" A-z_0.9 ", "a", "A" * 32):
            with self.subTest(device_id=device_id):
                metadata = self.load_metadata({"device_id": device_id})
                self.assertEqual(metadata.device_id, device_id.strip())
                self.assertIsNone(metadata.device_id_issue)

    def test_invalid_device_ids_have_issue(self):
        for device_id in ("圧力計", "A B", "a" * 33, "A/B", "A!", 123, False, [], {}):
            with self.subTest(device_id=device_id):
                metadata = self.load_metadata({"device_id": device_id})
                self.assertIsNone(metadata.device_id)
                self.assertEqual(metadata.device_id_issue, "id_invalid")

    def test_missing_device_ids_have_no_issue(self):
        for data in ({}, {"device_id": None}, {"device_id": ""}, {"device_id": "  "}):
            with self.subTest(data=data):
                metadata = self.load_metadata(data)
                self.assertIsNone(metadata.device_id)
                self.assertIsNone(metadata.device_id_issue)

    def test_unknown_device_id_is_missing(self):
        for device_id in ("unknown", "UNKNOWN", " UnKnOwN "):
            with self.subTest(device_id=device_id):
                metadata = self.load_metadata({"device_id": device_id})
                self.assertIsNone(metadata.device_id)
                self.assertIsNone(metadata.device_id_issue)

    def test_device_id_source_is_validated(self):
        for source in ("qr", "manual", None, "QR", "other", "", 123, [], {}):
            with self.subTest(source=source):
                metadata = self.load_metadata({"device_id": "P-101", "device_id_source": source})
                self.assertEqual(metadata.device_id_source, source if source in ("qr", "manual") else None)

    def test_device_id_source_requires_device_id(self):
        for device_id in (None, "", "unknown", "不正"):
            with self.subTest(device_id=device_id):
                metadata = self.load_metadata({"device_id": device_id, "device_id_source": "qr"})
                self.assertIsNone(metadata.device_id_source)

    def test_legacy_json_still_loads(self):
        metadata = self.load_metadata({"device_name": "P-101", "operator_value": 2.5})
        self.assertEqual(metadata.device_name, "P-101")
        self.assertEqual(metadata.operator_value, 2.5)
        self.assertIsNone(metadata.device_id)
        self.assertIsNone(metadata.device_id_source)
        self.assertIsNone(metadata.device_id_issue)

    def test_to_dict_includes_new_optional_fields(self):
        self.assertEqual(SidecarMetadata().to_dict(), {
            "local_id": None, "captured_at": None, "device_name": None,
            "operator_value": None, "operator_note": None, "scale_min": None,
            "scale_max": None, "device_id": None, "device_id_source": None,
            "device_id_issue": None, "inspection_id": None, "inspection_name": None,
        })
        metadata = self.load_metadata({"device_id": "P-101", "device_id_source": "manual"})
        self.assertEqual(metadata.to_dict()["device_id"], "P-101")
        self.assertEqual(metadata.to_dict()["device_id_source"], "manual")
        self.assertEqual(self.load_metadata({"device_id": "!"}).to_dict()["device_id_issue"], "id_invalid")

    def test_normalize_captured_at(self):
        from manager.sidecar import normalize_captured_at

        cases = (
            ("2026-10-30T09:12:00+09:00", "2026-10-30T00:12:00Z"),
            ("2026-10-30T00:12:00Z", "2026-10-30T00:12:00Z"),
            ("2026-10-30T00:12:00+00:00", "2026-10-30T00:12:00Z"),
            ("2026-10-30T09:12:00.999999+09:00", "2026-10-30T00:12:00Z"),
            ("2026-10-30T00:12:00.123Z", "2026-10-30T00:12:00Z"),
            ("2026-10-30T00:12:00-05:00", "2026-10-30T05:12:00Z"),
            ("2026-10-30T00:12:00+09:00", "2026-10-29T15:12:00Z"),
            ("2026-10-30T09:12:00", "2026-10-30T09:12:00"),
            ("2026-10-30T09:12:00.123", "2026-10-30T09:12:00.123"),
            ("not-a-date", None), ("2026-02-30T00:00:00Z", None),
            ("0001-01-01T00:00:00+09:00", None),
            ("", None), (None, None), (123, None), ([], None),
        )
        for text, expected in cases:
            with self.subTest(text=text):
                self.assertEqual(normalize_captured_at(text), expected)

    def test_load_sidecar_normalizes_captured_at(self):
        for text, expected in (
            ("2026-10-30T09:12:00+09:00", "2026-10-30T00:12:00Z"),
            ("2026-10-30T09:12:00", "2026-10-30T09:12:00"),
            ("not-a-date", None), (None, None), (123, None),
        ):
            with self.subTest(text=text):
                self.assertEqual(self.load_metadata({"captured_at": text}).captured_at, expected)


if __name__ == "__main__":
    unittest.main()
