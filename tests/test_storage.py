import os
import sqlite3
import tempfile
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

    def test_image_sha256_is_saved_and_returned(self):
        image_sha256 = "a" * 64
        self.storage.save_reading(
            device_name="TestDevice",
            image_path="/path/to/img.jpg",
            read_result={"stage": "ok", "value": 10.5},
            image_sha256=image_sha256,
        )

        self.assertEqual(self.storage.get_all_readings()[0].image_sha256, image_sha256)
        self.assertEqual(self.storage.get_processed_hashes(), {image_sha256})

    def test_saves_and_returns_extended_reading_fields(self):
        self.storage.save_reading(
            device_name="TestDevice",
            image_path="/path/to/img.jpg",
            read_result={
                "stage": "ok",
                "value": 10.5,
                "reading_id": "reading-123",
                "status": "low_confidence",
                "input_method": "corrected",
                "confidence": 0.75,
                "failure_stage": "scale",
                "failure_code": "scale_range_unresolved",
                "failure_detail": "OCR timed out",
                "pipeline_version": "v1.2.3",
                "log_path": "logs/reading-123.log",
                "overlay_path": None,
            },
        )

        reading = self.storage.get_all_readings()[0]
        self.assertEqual("reading-123", reading.reading_id)
        self.assertEqual("low_confidence", reading.status)
        self.assertEqual("corrected", reading.input_method)
        self.assertEqual(0.75, reading.confidence)
        self.assertEqual("scale", reading.failure_stage)
        self.assertEqual("scale_range_unresolved", reading.failure_code)
        self.assertEqual("OCR timed out", reading.failure_detail)
        self.assertEqual("v1.2.3", reading.pipeline_version)
        self.assertEqual("logs/reading-123.log", reading.log_path)
        self.assertIsNone(reading.overlay_path)

    def test_generates_reading_id_when_result_omits_it(self):
        self.storage.save_reading(
            device_name="TestDevice",
            image_path="/path/to/img.jpg",
            read_result={"stage": "ok", "value": 10.5},
        )

        self.assertIsNotNone(self.storage.get_all_readings()[0].reading_id)

    def test_existing_database_is_migrated_without_losing_rows(self):
        fd, db_path = tempfile.mkstemp()
        os.close(fd)
        try:
            conn = sqlite3.connect(db_path)
            try:
                conn.execute(
                    """
                    CREATE TABLE meter_readings (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        timestamp TEXT NOT NULL,
                        device_name TEXT NOT NULL,
                        value REAL,
                        stage TEXT NOT NULL,
                        image_path TEXT NOT NULL,
                        raw_data_json TEXT
                    )
                    """
                )
                conn.execute(
                    """
                    INSERT INTO meter_readings
                    (timestamp, device_name, value, stage, image_path, raw_data_json)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    ("2026-01-01 00:00:00", "Legacy", 1.0, "ok", "/old.jpg", "{}"),
                )
                conn.commit()
            finally:
                conn.close()

            storage = Storage(db_path)
            self.assertEqual(storage.get_all_readings()[0].device_name, "Legacy")
            conn = sqlite3.connect(db_path)
            try:
                columns = {row[1] for row in conn.execute("PRAGMA table_info(meter_readings)")}
            finally:
                conn.close()
            self.assertIn("image_sha256", columns)
            self.assertIn("reading_id", columns)
            self.assertIn("status", columns)
        finally:
            os.remove(db_path)


if __name__ == "__main__":
    unittest.main()
