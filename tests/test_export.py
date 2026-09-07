import os
import tempfile
import unittest
from manager.export import export_to_csv, filter_readings, group_by_device, readings_to_series


class DummyReading:
    def __init__(self, reading_id, captured_at, device_name, value, status="ok", image_path="", stage="test"):
        self.reading_id = reading_id
        self.captured_at = captured_at
        self.device_name = device_name
        self.value = value
        self.status = status
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
            DummyReading(1, "2026-08-20 10:00:00", "meter1", 10.5, "ok", "a.jpg"),
            DummyReading(2, "2026-08-20 11:00:00", "meter2", 20.0, "ok", "b.jpg"),
        ]
        export_to_csv(readings, self.test_file)

        with open(self.test_file, "r", encoding="utf-8-sig") as f:
            lines = [line.strip() for line in f.readlines()]

        self.assertEqual(len(lines), 3)
        self.assertEqual(lines[0], "reading_id,captured_at,device_name,value,stage,image_path")
        self.assertEqual(lines[1], "1,2026-08-20 10:00:00,meter1,10.5,test,a.jpg")
        self.assertEqual(lines[2], "2,2026-08-20 11:00:00,meter2,20.0,test,b.jpg")

    def test_empty_list_writes_header_only(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "out.csv")
            export_to_csv([], path)
            with open(path, "r", encoding="utf-8-sig") as f:
                lines = [line.strip() for line in f.readlines()]
            self.assertEqual(len(lines), 1)
            self.assertEqual(lines[0], "reading_id,captured_at,device_name,value,stage,image_path")

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
        result = filter_readings(readings, start_date="2026-08-21 00:00:00", end_date="2026-08-21 23:59:59")
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


if __name__ == "__main__":
    unittest.main()