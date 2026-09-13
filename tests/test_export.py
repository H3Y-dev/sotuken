import json
import os
import tempfile
import unittest
from datetime import date
from manager.export import (
    export_to_csv,
    export_to_jsonl,
    filter_readings,
    group_by_device,
    readings_to_series,
)
from manager.storage import MeterReading


class DummyReading:
    def __init__(self, reading_id, captured_at, device_name, value, status="ok", failure_stage=None, image_path="", stage="test"):
        self.reading_id = reading_id
        self.captured_at = captured_at
        self.timestamp = captured_at
        self.device_name = device_name
        self.value = value
        self.status = status
        self.failure_stage = failure_stage
        self.image_path = image_path
        self.stage = stage


class TestExportToCsv(unittest.TestCase):
    def setUp(self):
        self.test_file = "tests/test_temp_output.csv"

    def tearDown(self):
        if os.path.exists(self.test_file):
            os.remove(self.test_file)

    def test_writes_header_and_rows(self):
        readings = [
            DummyReading(1, "2026-08-20 10:00:00", "meter1", 10.5, "ok", None, "a.jpg"),
            DummyReading(2, "2026-08-20 11:00:00", "meter2", 20.0, "failed", "needle", "b.jpg"),
        ]
        export_to_csv(readings, self.test_file)

        with open(self.test_file, "r", encoding="utf-8-sig") as f:
            lines = [line.strip() for line in f.readlines()]

        self.assertEqual(len(lines), 3)
        self.assertEqual(lines[0], "reading_id,captured_at,device_name,value,status,failure_stage,image_path")
        self.assertEqual(lines[1], "1,2026-08-20 10:00:00,meter1,10.5,ok,,a.jpg")
        self.assertEqual(lines[2], "2,2026-08-20 11:00:00,meter2,20.0,failed,needle,b.jpg")

    def test_empty_list_writes_header_only(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "out.csv")
            export_to_csv([], path)
            with open(path, "r", encoding="utf-8-sig") as f:
                lines = [line.strip() for line in f.readlines()]
            self.assertEqual(len(lines), 1)
            self.assertEqual(lines[0], "reading_id,captured_at,device_name,value,status,failure_stage,image_path")

    def test_filter_by_device_name(self):
        readings = [
            DummyReading(1, "2026-08-20 10:00:00", "meter1", 10.0),
            DummyReading(2, "2026-08-20 11:00:00", "meter2", 20.0),
        ]
        result = filter_readings(readings, device_name="meter1")
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].reading_id, 1)

    def test_filter_by_date_range(self):
        readings = [
            DummyReading(1, "2026-08-20 10:00:00", "meter1", 10.0),
            DummyReading(2, "2026-08-21 10:00:00", "meter1", 20.0),
            DummyReading(3, "2026-08-22 10:00:00", "meter1", 30.0),
        ]
        result = filter_readings(readings, date_from=date(2026, 8, 21), date_to=date(2026, 8, 21))
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].reading_id, 2)

    def test_no_filter_returns_all(self):
        readings = [
            DummyReading(1, "2026-08-20 10:00:00", "meter1", 10.0),
        ]
        result = filter_readings(readings)
        self.assertEqual(len(result), 1)

    def test_group_by_device(self):
        readings = [
            DummyReading(1, "2026-08-20 10:00:00", "meter1", 10.0),
            DummyReading(2, "2026-08-21 10:00:00", "meter2", 20.0),
            DummyReading(3, "2026-08-22 10:00:00", "meter1", 30.0),
        ]
        groups = group_by_device(readings)
        self.assertEqual(len(groups["meter1"]), 2)
        self.assertEqual(len(groups["meter2"]), 1)

    def test_readings_to_series_normal(self):
        readings = [
            DummyReading(1, "2026-08-20T10:00:00", "meter1", 10.0),
            DummyReading(2, "2026-08-21T10:00:00", "meter1", 15.5),
        ]
        series = readings_to_series(readings)
        self.assertEqual(series, {"2026-08-20T10:00:00": 10.0, "2026-08-21T10:00:00": 15.5})

    def test_readings_to_series_with_none_value(self):
        readings = [
            DummyReading(1, "2026-08-20T10:00:00", "meter1", 10.0),
            DummyReading(2, "2026-08-21T10:00:00", "meter1", None, status="failed"),
        ]
        series = readings_to_series(readings)
        self.assertEqual(series, {"2026-08-20T10:00:00": 10.0})

    def test_readings_to_series_empty(self):
        series = readings_to_series([])
        self.assertEqual(series, {})


class TestFilterReadings(unittest.TestCase):
    def setUp(self):
        self.readings = [
            MeterReading("meter1", 10.0, "ok", "a.jpg", id=1, timestamp="2026-08-20 23:59:59"),
            MeterReading("meter1", 20.0, "ok", "b.jpg", id=2, timestamp="2026-08-21 00:00:00"),
            MeterReading("meter2", 30.0, "ok", "c.jpg", id=3, timestamp="2026-08-21 23:59:59"),
            MeterReading("meter1", 40.0, "ok", "d.jpg", id=4, timestamp="2026-08-22 00:00:00"),
        ]

    def test_filters_by_device_name(self):
        result = filter_readings(self.readings, device_name="meter1")
        self.assertEqual([reading.id for reading in result], [1, 2, 4])

    def test_filters_by_date_range_including_both_boundaries(self):
        result = filter_readings(
            self.readings, date_from=date(2026, 8, 21), date_to=date(2026, 8, 21)
        )
        self.assertEqual([reading.id for reading in result], [2, 3])

    def test_filters_by_device_name_and_date_range(self):
        result = filter_readings(
            self.readings,
            device_name="meter1",
            date_from=date(2026, 8, 21),
            date_to=date(2026, 8, 21),
        )
        self.assertEqual([reading.id for reading in result], [2])

    def test_returns_all_readings_without_filters(self):
        self.assertEqual(filter_readings(self.readings, device_name="すべて"), self.readings)


class TestExportToJsonl(unittest.TestCase):
    def setUp(self):
        self.test_file = "tests/test_temp_output.jsonl"

    def tearDown(self):
        if os.path.exists(self.test_file):
            os.remove(self.test_file)

    def test_export_to_jsonl(self):
        schema_fields = [
            "reading_id", "local_id", "captured_at", "received_at", "processed_at", "device_name",
            "value", "unit", "status", "input_method", "confidence", "image_path", "image_sha256",
            "failure_stage", "failure_code", "failure_detail", "pipeline_version", "log_path", "overlay_path",
        ]
        readings = [
            {
                "reading_id": "uuid-1",
                "local_id": "local-01",
                "captured_at": "2026-08-20T10:00:00",
                "received_at": "2026-08-20T10:01:00",
                "processed_at": "2026-08-20T10:02:00",
                "device_name": "meter_圧力計1号",
                "value": 42.5,
                "unit": "MPa",
                "status": "ok",
                "input_method": "auto",
                "confidence": 0.95,
                "image_path": "images/1.jpg",
                "image_sha256": "abcdef123456",
                "failure_stage": None,
                "failure_code": None,
                "failure_detail": None,
                "pipeline_version": "v1.0.0",
                "log_path": "logs/1.log",
                "overlay_path": "overlays/1.jpg",
            },
            {
                "reading_id": "uuid-2",
                "local_id": None,
                "captured_at": "2026-08-20T11:00:00",
                "received_at": None,
                "processed_at": "2026-08-20T11:02:00",
                "device_name": "meter_圧力計2号",
                "value": None,
                "unit": "kPa",
                "status": "failed",
                "input_method": "auto",
                "confidence": None,
                "image_path": "images/2.jpg",
                "image_sha256": "fedcba654321",
                "failure_stage": "needle",
                "failure_code": "ERR_NEEDLE_NOT_FOUND",
                "failure_detail": "針が検出できませんでした",
                "pipeline_version": "v1.0.0",
                "log_path": "logs/2.log",
                "overlay_path": None,
            },
        ]

        export_to_jsonl(readings, self.test_file)

        # ファイルを読み込み、行数とJSONデコード結果を検証
        with open(self.test_file, "r", encoding="utf-8") as f:
            lines = f.readlines()

        self.assertEqual(len(lines), len(readings))

        for idx, line in enumerate(lines):
            record = json.loads(line)
            # 各フィールドが元のレコードと一致することを確認
            self.assertEqual(list(record.keys()), schema_fields)
            for field in schema_fields:
                self.assertEqual(record[field], readings[idx][field])

        # ensure_ascii=False で日本語がそのまま含まれていることを確認
        full_content = "".join(lines)
        self.assertIn("meter_圧力計1号", full_content)
        self.assertIn("針が検出できませんでした", full_content)


if __name__ == "__main__":
    unittest.main()
