import math
import sqlite3
import tempfile
import unittest
from pathlib import Path

from manager.devices import (
    DeviceConflict,
    create_device,
    get_device,
    list_devices,
    register_device,
    update_device,
    validate_device_fields,
)
from manager.storage import Storage


def _base_fields(**overrides):
    data = {
        "device_name": "Pressure Gauge",
        "unit": "MPa",
        "min_value": 0.0,
        "max_value": 100.0,
        "tolerance_min": 10.0,
        "tolerance_max": 80.0,
    }
    data.update(overrides)
    return data


class TestDeviceAdmin(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.db_path = Path(self.temp.name) / "manager.db"
        self.storage = Storage(str(self.db_path))

    def test_legacy_db_migration_and_reopen_preserves_existing_devices(self):
        legacy_path = Path(self.temp.name) / "legacy.db"
        conn = sqlite3.connect(legacy_path)
        try:
            conn.executescript(
                """
                CREATE TABLE meter_readings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    device_name TEXT NOT NULL,
                    value REAL,
                    stage TEXT NOT NULL,
                    image_path TEXT NOT NULL,
                    raw_data_json TEXT
                );
                CREATE TABLE devices (
                    device_id TEXT PRIMARY KEY,
                    device_name TEXT NOT NULL,
                    unit TEXT,
                    min_value REAL,
                    max_value REAL,
                    kind TEXT,
                    provisional INTEGER DEFAULT 0,
                    note TEXT,
                    created_at TEXT,
                    updated_at TEXT
                );
                CREATE TABLE image_truths (
                    image_sha256 TEXT PRIMARY KEY,
                    operator_value REAL,
                    operator_note TEXT,
                    scale_min REAL,
                    scale_max REAL,
                    entered_at TEXT NOT NULL
                );
                INSERT INTO devices (device_id, device_name, unit, min_value, max_value, kind, provisional, note)
                VALUES ('DEV-1', 'Existing 1', 'MPa', 0, 10, 'general', 0, 'keep'),
                       ('DEV-2', 'Existing 2', NULL, NULL, NULL, NULL, 1, NULL);
                """
            )
            conn.commit()
        finally:
            conn.close()

        first = Storage(str(legacy_path))
        second = Storage(str(legacy_path))

        devices = list_devices(second)
        self.assertEqual([d["device_id"] for d in devices], ["DEV-1", "DEV-2"])
        self.assertEqual(devices[0]["device_name"], "Existing 1")
        self.assertEqual(devices[0]["note"], "keep")
        self.assertIsNone(devices[0]["tolerance_min"])
        self.assertIsNone(devices[0]["tolerance_max"])
        self.assertEqual(devices[1]["provisional"], 1)
        self.assertIsNotNone(first)

    def test_create_and_list_devices_binary_order_and_limit(self):
        created_lower = create_device(self.storage, "a-1", _base_fields(device_name="  Lower  ", unit=" bar "))
        created_upper = create_device(self.storage, "B-1", _base_fields(device_name="Upper"))

        self.assertEqual(created_lower["device_name"], "Lower")
        self.assertEqual(created_lower["unit"], "bar")
        self.assertEqual(created_lower["provisional"], 0)
        self.assertEqual(created_upper["tolerance_min"], 10.0)
        self.assertEqual(created_upper["tolerance_max"], 80.0)

        items = list_devices(self.storage)
        self.assertEqual([d["device_id"] for d in items], ["B-1", "a-1"])
        self.assertEqual(len(list_devices(self.storage, limit=1)), 1)

    def test_create_device_rejects_exact_and_case_conflict(self):
        create_device(self.storage, "Pump-01", _base_fields(device_name="Original"))

        for conflict_id in ("Pump-01", "pump-01", "PUMP-01"):
            with self.subTest(conflict_id=conflict_id):
                with self.assertRaises(DeviceConflict):
                    create_device(self.storage, conflict_id, _base_fields(device_name="New Name"))

        self.assertEqual(len(list_devices(self.storage)), 1)
        self.assertEqual(get_device(self.storage, "Pump-01")["device_name"], "Original")

    def test_update_device_replaces_clears_null_and_preserves_extra_columns(self):
        register_device(
            self.storage,
            "DEV-1",
            "Old Name",
            unit="kPa",
            min_value=0,
            max_value=50,
            kind="analog",
            provisional=1,
            note="keep-note",
        )
        before = get_device(self.storage, "DEV-1")

        updated = update_device(
            self.storage,
            "DEV-1",
            _base_fields(
                device_name="New Name",
                unit=None,
                min_value=None,
                max_value=None,
                tolerance_min=None,
                tolerance_max=None,
            ),
        )
        self.assertEqual(updated["device_name"], "New Name")
        self.assertIsNone(updated["unit"])
        self.assertIsNone(updated["min_value"])
        self.assertIsNone(updated["max_value"])
        self.assertIsNone(updated["tolerance_min"])
        self.assertIsNone(updated["tolerance_max"])
        self.assertEqual(updated["provisional"], 0)
        self.assertEqual(updated["kind"], "analog")
        self.assertEqual(updated["note"], "keep-note")
        self.assertEqual(updated["created_at"], before["created_at"])

        with self.assertRaises(KeyError):
            update_device(self.storage, "missing-id", _base_fields())

    def test_update_device_edits_exact_case_match_only(self):
        register_device(self.storage, "A-1", "Upper")
        register_device(self.storage, "a-1", "Lower")

        update_device(self.storage, "a-1", _base_fields(device_name="Lower Edited"))
        self.assertEqual(get_device(self.storage, "A-1")["device_name"], "Upper")
        self.assertEqual(get_device(self.storage, "a-1")["device_name"], "Lower Edited")

    def test_validate_device_fields_ranges_and_boundaries(self):
        # 許容範囲の両端一致・目盛り端点一致は許可
        equal_tol = validate_device_fields(
            _base_fields(min_value=0, max_value=10, tolerance_min=5, tolerance_max=5)
        )
        self.assertEqual(equal_tol["tolerance_min"], 5.0)
        self.assertEqual(equal_tol["tolerance_max"], 5.0)

        edge_tol = validate_device_fields(
            _base_fields(min_value=0, max_value=10, tolerance_min=0, tolerance_max=10)
        )
        self.assertEqual(edge_tol["tolerance_min"], 0.0)
        self.assertEqual(edge_tol["tolerance_max"], 10.0)

        # 目盛り範囲が未設定でも許容範囲を保存できる
        no_scale = create_device(
            self.storage,
            "NO-SCALE",
            _base_fields(min_value=None, max_value=None, tolerance_min=1, tolerance_max=2),
        )
        self.assertIsNone(no_scale["min_value"])
        self.assertEqual(no_scale["tolerance_min"], 1.0)
        self.assertEqual(no_scale["tolerance_max"], 2.0)

        invalid_cases = [
            _base_fields(tolerance_min=20, tolerance_max=10),  # 下限 > 上限
            _base_fields(min_value=10, max_value=10),          # 目盛り min == max
            _base_fields(min_value=20, max_value=10),          # 目盛り min > max
            _base_fields(min_value=0, max_value=None, tolerance_min=None, tolerance_max=None),
            _base_fields(tolerance_min=10, tolerance_max=None),
            _base_fields(min_value=0, max_value=100, tolerance_min=-1, tolerance_max=50),
            _base_fields(min_value=0, max_value=100, tolerance_min=50, tolerance_max=101),
            _base_fields(min_value=True),
            _base_fields(max_value="100"),
            _base_fields(tolerance_min=math.nan),
            _base_fields(tolerance_max=math.inf),
            _base_fields(device_name="unknown"),
            _base_fields(device_name=" unknown "),
            _base_fields(device_name="a" * 65),
            _base_fields(unit=""),
            _base_fields(unit="   "),
            _base_fields(unit="u" * 17),
            _base_fields(unit="M\nPa"),
            {**_base_fields(), "extra": 1},
            {k: v for k, v in _base_fields().items() if k != "unit"},
        ]
        for case in invalid_cases:
            with self.subTest(case=case):
                with self.assertRaises(ValueError):
                    validate_device_fields(case)

    def test_register_device_keeps_fill_only_behavior(self):
        create_device(
            self.storage,
            "DEV-FILL",
            _base_fields(
                device_name="Manual Name",
                unit=None,
                min_value=None,
                max_value=None,
                tolerance_min=10.0,
                tolerance_max=80.0,
            ),
        )
        res = register_device(
            self.storage,
            "DEV-FILL",
            device_name="Ingested Name",
            unit="bar",
            min_value=5,
            max_value=50,
        )
        self.assertEqual(set(res.updated_fields), {"unit", "min_value", "max_value"})
        self.assertEqual(res.warnings, ["name_conflict"])
        row = get_device(self.storage, "DEV-FILL")
        self.assertEqual(row["device_name"], "Manual Name")
        self.assertEqual(row["unit"], "bar")
        self.assertEqual(row["min_value"], 5.0)
        self.assertEqual(row["max_value"], 50.0)
        self.assertEqual(row["tolerance_min"], 10.0)
        self.assertEqual(row["tolerance_max"], 80.0)
