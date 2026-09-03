import unittest

from manager.storage import Storage


class TestStorage(unittest.TestCase):

    def setUp(self):
        # メモリ上のSQLite（テスト用DB）を作成
        self.storage = Storage(":memory:")

    def test_save_and_get_reading(self):
        # 正常系のダミーデータ
        dummy_ok = {
            "stage": "ok",
            "value": 10.5,
            "ratio": 0.1,
            "angle_deg": 45.0,
            "error": None,
        }

        # 保存のテスト
        row_id = self.storage.save_reading(
            device_name="TestDevice",
            image_path="/path/to/img.jpg",
            read_result=dummy_ok,
        )
        self.assertIsNotNone(row_id)

        # 取得のテスト
        readings = self.storage.get_all_readings()
        self.assertEqual(len(readings), 1)

        r = readings[0]
        self.assertEqual(r.device_name, "TestDevice")
        self.assertEqual(r.stage, "ok")
        self.assertEqual(r.value, 10.5)

    def test_save_failed_reading(self):
        # 異常系（読み取り失敗）のダミーデータ
        dummy_ng = {
            "stage": "needle",
            "value": None,
            "ratio": None,
            "angle_deg": None,
            "error": "Failed",
        }

        self.storage.save_reading(
            device_name="TestDeviceNG",
            image_path="/path/to/ng.jpg",
            read_result=dummy_ng,
        )

        readings = self.storage.get_all_readings()
        self.assertEqual(len(readings), 1)

        r = readings[0]
        self.assertEqual(r.stage, "needle")
        self.assertIsNone(r.value)


if __name__ == "__main__":
    unittest.main()
