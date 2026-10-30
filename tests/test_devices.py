import csv
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from manager.devices import (
    get_device, import_devices_csv, list_devices, register_device,
    rename_device, validate_device_id,
)
from manager.storage import Storage


CSV_PATH = Path(__file__).resolve().parents[1] / "eval" / "devices.csv"


class TestDevices(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.db_path = Path(self.temp.name) / "manager.db"
        self.storage = Storage(str(self.db_path))

    def write_csv(self, rows):
        path = Path(self.temp.name) / "devices.csv"
        with path.open("w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=[
                "device_id", "device_name", "kind", "unit", "min_value",
                "max_value", "provisional", "note",
            ])
            writer.writeheader()
            writer.writerows(rows)
        return path

    def test_register_new_device(self):
        result = register_device(self.storage, "A-1", "Pressure", unit="MPa",
                                 min_value=0, max_value=10, kind="general")
        self.assertTrue(result.created)
        self.assertFalse(result.skipped)
        self.assertEqual(result.warnings, [])
        row = get_device(self.storage, "A-1")
        self.assertEqual(row["device_name"], "Pressure")
        self.assertEqual(row["min_value"], 0)
        self.assertEqual(datetime.fromisoformat(row["created_at"]).utcoffset().total_seconds(), 0)
        self.assertEqual(row["created_at"], row["updated_at"])
        self.assertIsNone(get_device(self.storage, "missing"))

    def test_fill_only_null_and_empty_fields(self):
        register_device(self.storage, "A", "Original", min_value=0)
        with self.storage.connection() as conn:
            conn.execute("UPDATE devices SET unit = '', note = '' WHERE device_id = 'A'")
        result = register_device(self.storage, "A", "Changed", unit="bar",
                                 min_value=1, max_value=10, note="note", kind="general")
        self.assertEqual(set(result.updated_fields), {"unit", "max_value", "note", "kind"})
        row = get_device(self.storage, "A")
        self.assertEqual(row["device_name"], "Original")
        self.assertEqual(row["min_value"], 0)
        self.assertEqual(row["unit"], "bar")
        unchanged = register_device(self.storage, "A", "Original", unit="bar")
        self.assertEqual(unchanged.updated_fields, [])
        self.assertEqual(get_device(self.storage, "A")["updated_at"], row["updated_at"])

    def test_conflicts_preserve_existing_values(self):
        register_device(self.storage, "A", "Original", unit="bar", min_value=0, max_value=10)
        result = register_device(self.storage, "A", "Other", unit="MPa", min_value=1, max_value=20)
        self.assertEqual(set(result.warnings), {"name_conflict", "unit_conflict", "range_conflict"})
        self.assertEqual(result.updated_fields, [])
        self.assertEqual(get_device(self.storage, "A")["max_value"], 10)

    def test_invalid_ids(self):
        for value in ("", " ", "日本語", "a" * 33, "a/b", "a\n", None, 12):
            with self.subTest(value=value):
                self.assertFalse(validate_device_id(value))
                with self.assertRaises(ValueError):
                    register_device(self.storage, value, "Name")
        self.assertTrue(validate_device_id("aZ09._-"))
        self.assertTrue(validate_device_id("a" * 32))
        self.assertEqual(list_devices(self.storage), [])

    def test_case_conflict_keeps_separate_devices(self):
        register_device(self.storage, "A-1", "Upper")
        result = register_device(self.storage, "a-1", "Lower")
        self.assertIn("id_case_conflict", result.warnings)
        self.assertEqual(len(list_devices(self.storage)), 2)
        self.assertEqual(get_device(self.storage, "a-1")["device_name"], "Lower")

    def test_unknown_and_explicit_empty_names_are_skipped(self):
        for name in ("unknown", " unknown ", "", "   "):
            with self.subTest(name=name):
                result = register_device(self.storage, "A", name)
                self.assertTrue(result.skipped)
                self.assertFalse(result.created)
                self.assertIsNone(get_device(self.storage, "A"))
        register_device(self.storage, "A", "Original")
        self.assertTrue(register_device(self.storage, "A", "unknown", unit="bar").skipped)
        self.assertIsNone(get_device(self.storage, "A")["unit"])

    def test_id_only_registration_uses_id_and_does_not_conflict_with_existing_name(self):
        self.assertTrue(register_device(self.storage, "A").created)
        self.assertEqual(get_device(self.storage, "A")["device_name"], "A")
        register_device(self.storage, "B", "Named")
        result = register_device(self.storage, "B", unit="bar")
        self.assertEqual(result.warnings, [])
        self.assertEqual(get_device(self.storage, "B")["device_name"], "Named")

    def test_csv_missing_and_unknown_names_are_skipped(self):
        path = self.write_csv([{"device_id": "A"}, {"device_id": "B", "device_name": "unknown"}])
        for overwrite in (False, True):
            with self.subTest(overwrite=overwrite):
                result = import_devices_csv(self.storage, path, overwrite=overwrite)
                self.assertEqual(result["skipped"], 2)
                self.assertEqual(list_devices(self.storage), [])

    def test_rename_does_not_change_readings(self):
        register_device(self.storage, "A", "Old")
        self.storage.save_reading("Old", "image.jpg", {"stage": "ok", "value": 1})
        with self.storage.connection() as conn:
            before = conn.execute("SELECT * FROM meter_readings").fetchall()
            conn.execute("UPDATE devices SET updated_at = '2000-01-01T00:00:00+00:00'")
        rename_device(self.storage, "A", "New")
        self.assertEqual(get_device(self.storage, "A")["device_name"], "New")
        self.assertNotEqual(get_device(self.storage, "A")["updated_at"], "2000-01-01T00:00:00+00:00")
        with self.storage.connection() as conn:
            self.assertEqual(conn.execute("SELECT * FROM meter_readings").fetchall(), before)

    def test_real_csv_is_idempotent(self):
        result = import_devices_csv(self.storage, CSV_PATH)
        self.assertEqual(result["created"], 37)
        self.assertEqual(result["updated"], 0)
        self.assertEqual(len(list_devices(self.storage)), 37)
        again = import_devices_csv(self.storage, CSV_PATH)
        self.assertEqual(again["created"], 0)
        self.assertEqual(again["updated"], 0)
        self.assertEqual(again["skipped"], 37)
        self.assertEqual(len(list_devices(self.storage)), 37)

    def test_csv_overwrite_reports_exact_differences(self):
        register_device(self.storage, "A", "Old", unit="bar", min_value=0, max_value=10)
        path = self.write_csv([{"device_id": "A", "device_name": "New", "unit": "MPa",
                                "min_value": "0", "max_value": "20", "provisional": "1"}])
        preserved = import_devices_csv(self.storage, path)
        self.assertEqual(preserved["updated"], 0)
        self.assertEqual(get_device(self.storage, "A")["device_name"], "Old")
        result = import_devices_csv(self.storage, path, overwrite=True)
        self.assertEqual(result["updated"], 1)
        changes = {d["field"]: (d["old_value"], d["new_value"]) for d in result["differences"]}
        self.assertEqual(changes, {"device_name": ("Old", "New"), "unit": ("bar", "MPa"),
                                   "max_value": (10, 20), "provisional": (0, 1)})
        self.assertTrue(all(d["device_id"] == "A" for d in result["differences"]))

    def test_csv_invalid_duplicate_and_bad_number_rows_are_skipped(self):
        path = self.write_csv([
            {"device_id": "A", "device_name": "First"},
            {"device_id": "A", "device_name": "Duplicate"},
            {"device_id": "bad/id", "device_name": "Bad"},
            {"device_id": "B", "device_name": "Bad number", "min_value": "oops"},
            {"device_id": "C", "device_name": "Last"},
        ])
        result = import_devices_csv(self.storage, path, overwrite=True)
        self.assertEqual(result["created"], 2)
        self.assertEqual(result["skipped"], 3)
        self.assertEqual([e["line"] for e in result["errors"]], [3, 4, 5])
        self.assertEqual(get_device(self.storage, "A")["device_name"], "First")

    def test_csv_overwrite_can_clear_optional_values(self):
        register_device(self.storage, "A", "Name", unit="bar", min_value=0,
                        max_value=10, provisional=True, note="old")
        path = self.write_csv([{"device_id": "A", "device_name": "Name"}])
        result = import_devices_csv(self.storage, path, overwrite=True)
        self.assertEqual(result["updated"], 1)
        row = get_device(self.storage, "A")
        self.assertIsNone(row["unit"])
        self.assertIsNone(row["min_value"])
        self.assertIsNone(row["max_value"])
        self.assertIsNone(row["note"])
        self.assertEqual(row["provisional"], 0)

    def test_memory_connection_survives_registry_operations_and_rollback(self):
        storage = Storage(":memory:")
        self.addCleanup(storage._conn.close)
        register_device(storage, "A", "Name")
        with self.assertRaises(RuntimeError):
            with storage.connection() as conn:
                conn.execute("UPDATE devices SET device_name = 'Lost'")
                raise RuntimeError("rollback")
        self.assertEqual(get_device(storage, "A")["device_name"], "Name")
        self.assertEqual(len(list_devices(storage)), 1)

    def test_invalid_rename_does_not_change_registry(self):
        register_device(self.storage, "A", "Original")
        for name in ("", " ", "unknown", None):
            with self.subTest(name=name), self.assertRaises(ValueError):
                rename_device(self.storage, "A", name)
        with self.assertRaises(ValueError):
            rename_device(self.storage, "missing", "New")
        self.assertEqual(get_device(self.storage, "A")["device_name"], "Original")


if __name__ == "__main__":
    unittest.main()
