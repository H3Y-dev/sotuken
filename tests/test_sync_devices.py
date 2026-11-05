import csv
import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from manager.devices import get_device, register_device
from manager.storage import Storage
from tools.sync_devices import main, sync_devices


class TestSyncDevices(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.db = Path(self.temp.name) / "manager.db"
        self.storage = Storage(str(self.db))
        self.csv = Path(self.temp.name) / "devices.csv"

    def write_csv(self, rows):
        with self.csv.open("w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=(
                "device_id", "device_name", "unit", "min_value", "max_value"))
            writer.writeheader()
            writer.writerows(rows)

    def test_dry_run_reports_new_without_writing(self):
        self.write_csv([{"device_id": "A", "device_name": "Meter"}])
        before = self.db.read_bytes()
        result = sync_devices(self.csv, self.db)
        self.assertEqual(result["new"], ["A"])
        self.assertEqual(result["csv_only"], ["A"])
        self.assertEqual(self.db.read_bytes(), before)

    def test_apply_registers_and_reports_unchanged_and_db_only(self):
        register_device(self.storage, "B", "Existing")
        self.write_csv([{"device_id": "A", "device_name": "Meter", "unit": "MPa"}])
        result = sync_devices(self.csv, self.db, apply=True)
        self.assertEqual(result["db_only"], ["B"])
        self.assertEqual(get_device(self.storage, "A")["unit"], "MPa")
        self.assertEqual(sync_devices(self.csv, self.db)["unchanged"], ["A"])

    def test_only_fills_empty_fields_and_preserves_null_unit(self):
        register_device(self.storage, "A", "Original", min_value=0)
        self.write_csv([{"device_id": "A", "device_name": "Replacement",
                         "min_value": "9", "max_value": "100"}])
        result = sync_devices(self.csv, self.db, apply=True)
        row = get_device(self.storage, "A")
        self.assertEqual((row["device_name"], row["min_value"], row["max_value"], row["unit"]),
                         ("Original", 0, 100, None))
        self.assertEqual(result["changed"]["A"], {"max_value": {"old": None, "new": 100.0}})
        self.assertTrue(result["warnings"])
        self.write_csv([{"device_id": "A", "device_name": "Original", "unit": "MPa"}])
        sync_devices(self.csv, self.db, apply=True)
        self.write_csv([{"device_id": "A", "device_name": "Original"}])
        sync_devices(self.csv, self.db, apply=True)
        self.assertEqual(get_device(self.storage, "A")["unit"], "MPa")

    def test_invalid_id_blocks_entire_apply(self):
        self.write_csv([{"device_id": "A", "device_name": "Valid"},
                        {"device_id": "bad id", "device_name": "Invalid"}])
        result = sync_devices(self.csv, self.db, apply=True)
        self.assertTrue(result["errors"])
        self.assertFalse(result["applied"])
        self.assertIsNone(get_device(self.storage, "A"))

    def test_unknown_is_not_registered(self):
        self.write_csv([{"device_id": "unknown", "device_name": "unknown"},
                        {"device_id": "A", "device_name": "unknown"}])
        sync_devices(self.csv, self.db, apply=True)
        self.assertIsNone(get_device(self.storage, "unknown"))
        self.assertIsNone(get_device(self.storage, "A"))

    def test_case_warning_reuses_registry_rules(self):
        register_device(self.storage, "A", "Upper")
        self.write_csv([{"device_id": "a", "device_name": "Lower"}])
        result = sync_devices(self.csv, self.db)
        self.assertIn("id_case_conflict", result["warnings"][0]["warnings"])

    def test_missing_db_is_not_created_by_dry_run(self):
        self.write_csv([{"device_id": "A", "device_name": "Meter"}])
        missing = self.db.with_name("missing.db")
        self.assertEqual(sync_devices(self.csv, missing)["new"], ["A"])
        self.assertFalse(missing.exists())

    def test_duplicate_or_invalid_number_blocks_apply(self):
        for rows in (
            [{"device_id": "A", "device_name": "One"},
             {"device_id": "A", "device_name": "Two"}],
            [{"device_id": "A", "device_name": "One", "min_value": "nan"}],
        ):
            with self.subTest(rows=rows):
                self.write_csv(rows)
                self.assertTrue(sync_devices(self.csv, self.db, apply=True)["errors"])
                self.assertIsNone(get_device(self.storage, "A"))

    def test_missing_header_is_rejected_without_creating_db(self):
        self.csv.write_text("device_id,scale_min\nA,1\n", encoding="utf-8")
        missing = self.db.with_name("missing.db")
        with self.assertRaisesRegex(ValueError, "device_name"):
            sync_devices(self.csv, missing, apply=True)
        self.assertFalse(missing.exists())

    def test_cli_default_and_explicit_dry_run_then_apply(self):
        self.write_csv([{"device_id": "A", "device_name": "Meter"}])
        for flag in ([], ["--dry-run"], ["--apply"]):
            with self.subTest(flag=flag), contextlib.redirect_stdout(io.StringIO()) as output:
                self.assertEqual(main([str(self.csv), "--db", str(self.db)] + flag), 0)
                self.assertEqual(json.loads(output.getvalue())["applied"], flag == ["--apply"])
                self.assertEqual(get_device(self.storage, "A") is not None, flag == ["--apply"])

    def test_cli_errors_have_nonzero_exit(self):
        self.write_csv([{"device_id": "bad id", "device_name": "Invalid"}])
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(main([str(self.csv), "--db", str(self.db), "--apply"]), 1)


if __name__ == "__main__":
    unittest.main()
