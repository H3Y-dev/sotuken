import unittest

import numpy as np

from manager.storage import Storage


class TestStorage(unittest.TestCase):

    def setUp(self):
        # メモリ上のSQLite（テスト用DB）を作成
        self.storage = Storage(":memory:")

    def test_save_reading_with_numpy_values(self):
        """meter_pipeline の戻り値に混ざる numpy 値を保存できること。

        素の json.dumps は ndarray で TypeError を投げる。これを踏んで
        フォルダ監視からの取り込みが1枚目で必ず落ちていた（2026-09-13に実機相当の
        通し検証で発覚）。既存のテストは dict のモックで numpy が入らず素通りしていた。
        """
        result_with_numpy = {
            "stage": "ok",
            "value": np.float64(12.5),
            "center": np.array([638, 478]),
            "ticks": [np.array([1.0, 2.0]), np.array([3.0, 4.0])],
            "count": np.int64(39),
            "error": None,
        }

        row_id = self.storage.save_reading(
            device_name="NumpyDevice",
            image_path="/path/to/numpy.jpg",
            read_result=result_with_numpy,
        )
        self.assertIsNotNone(row_id)

        readings = self.storage.get_all_readings()
        saved = [r for r in readings if r.device_name == "NumpyDevice"]
        self.assertEqual(len(saved), 1)

        # 読み戻した raw_data に、配列が入れ子のまま残っていること
        raw = saved[0].raw_data
        self.assertEqual(raw["center"], [638, 478])
        self.assertEqual(raw["ticks"], [[1.0, 2.0], [3.0, 4.0]])
        self.assertEqual(raw["count"], 39)
        self.assertEqual(raw["stage"], "ok")

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
