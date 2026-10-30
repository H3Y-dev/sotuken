import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from manager.manager import MeterManager
from manager.storage import Storage


OLD_SCHEMA = """
CREATE TABLE meter_readings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    device_name TEXT NOT NULL,
    value REAL,
    stage TEXT NOT NULL,
    image_path TEXT NOT NULL,
    raw_data_json TEXT,
    image_sha256 TEXT,
    reading_id TEXT,
    status TEXT,
    input_method TEXT,
    confidence REAL,
    failure_stage TEXT,
    failure_code TEXT,
    failure_detail TEXT,
    pipeline_version TEXT,
    log_path TEXT,
    overlay_path TEXT
)
"""
NEW_COLUMNS = (
    "device_id", "device_id_source", "device_id_issue",
    "captured_at", "received_at", "image_rel",
)


class TestStorageSchema(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.db_path = Path(self.temp_dir.name) / "manager.db"

    def make_old_db(self, reading_ids=("reading-original",)):
        with closing(sqlite3.connect(self.db_path)) as conn:
            conn.execute(OLD_SCHEMA)
            conn.executemany(
                """INSERT INTO meter_readings
                   (timestamp, device_name, value, stage, image_path,
                    raw_data_json, image_sha256, reading_id)
                   VALUES ('2026-10-29 12:00:00', 'Pressure', 1.25, 'ok',
                           'images/a.jpg', '{"value": 1.25}', 'same-hash', ?)""",
                [(reading_id,) for reading_id in reading_ids],
            )
            conn.commit()

    def snapshot(self):
        with closing(sqlite3.connect(self.db_path)) as conn:
            return (
                conn.execute("SELECT type, name, sql FROM sqlite_master ORDER BY name").fetchall(),
                conn.execute("SELECT * FROM meter_readings ORDER BY id").fetchall(),
            )

    def backups(self):
        return list(self.db_path.parent.glob("backups/manager.db.bak_*"))

    def test_old_schema_preserves_values_and_adds_nullable_columns_and_devices(self):
        self.make_old_db()
        old_rows = self.snapshot()[1]
        Storage(str(self.db_path))
        with closing(sqlite3.connect(self.db_path)) as conn:
            columns = {row[1]: row for row in conn.execute("PRAGMA table_info(meter_readings)")}
            for column in NEW_COLUMNS:
                self.assertEqual(columns[column][2:5], ("TEXT", 0, None))
            rows = conn.execute("SELECT * FROM meter_readings").fetchall()
            self.assertEqual([row[:18] for row in rows], old_rows)
            self.assertEqual(rows[0][18:], (None,) * 6)
            devices = {row[1]: row for row in conn.execute("PRAGMA table_info(devices)")}
            self.assertEqual(set(devices), {
                "device_id", "device_name", "unit", "min_value", "max_value",
                "kind", "provisional", "note", "created_at", "updated_at",
            })
            self.assertEqual(devices["device_id"][2], "TEXT")
            self.assertEqual(devices["device_id"][5], 1)
            self.assertEqual(devices["device_name"][3], 1)
            self.assertEqual(devices["provisional"][4], "0")
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM devices").fetchone()[0], 0)

    def test_repairs_missing_and_duplicate_ids_before_unique_index(self):
        self.make_old_db((None, "", "duplicate", "duplicate", "valid", "duplicate"))
        with self.assertLogs("manager.storage", level="INFO") as logs:
            Storage(str(self.db_path))
        self.assertTrue(any("4" in message for message in logs.output))
        with closing(sqlite3.connect(self.db_path)) as conn:
            ids = conn.execute("SELECT reading_id FROM meter_readings ORDER BY id").fetchall()
            self.assertEqual(ids, [(value,) for value in (
                "legacy:1", "legacy:2", "duplicate", "legacy:4", "valid", "legacy:6",
            )])
            duplicates = conn.execute(
                "SELECT reading_id FROM meter_readings GROUP BY reading_id HAVING COUNT(*) > 1"
            ).fetchall()
            self.assertEqual(duplicates, [])
            indexes = {}
            for row in conn.execute("PRAGMA index_list(meter_readings)").fetchall():
                fields = conn.execute(f'PRAGMA index_info("{row[1]}")').fetchall()
                indexes[fields[0][2]] = row
            self.assertEqual(indexes["device_id"][2], 0)
            self.assertEqual(indexes["image_sha256"][2], 0)
            self.assertEqual(indexes["reading_id"][2], 1)
            self.assertEqual(indexes["reading_id"][4], 1)
            sql = conn.execute(
                "SELECT sql FROM sqlite_master WHERE name = ?", (indexes["reading_id"][1],)
            ).fetchone()[0]
            self.assertIn("WHERE reading_id IS NOT NULL", sql)
            with self.assertRaises(sqlite3.IntegrityError):
                conn.execute("UPDATE meter_readings SET reading_id = 'duplicate' WHERE id = 4")

    def test_backup_contains_original_schema_and_rows_and_is_not_repeated(self):
        self.make_old_db((None, ""))
        original = self.snapshot()
        Storage(str(self.db_path))
        backups = self.backups()
        self.assertEqual(len(backups), 1)
        self.assertRegex(backups[0].name, r"^manager\.db\.bak_\d{8}_\d{6}$")
        with closing(sqlite3.connect(backups[0])) as conn:
            self.assertEqual(conn.execute(
                "SELECT type, name, sql FROM sqlite_master ORDER BY name"
            ).fetchall(), original[0])
            self.assertEqual(conn.execute("SELECT * FROM meter_readings ORDER BY id").fetchall(), original[1])
        Storage(str(self.db_path))
        self.assertEqual(self.backups(), backups)

    def test_memory_database_does_not_back_up(self):
        with patch("manager.storage.Path.mkdir") as mkdir:
            storage = Storage(":memory:")
        self.addCleanup(storage._conn.close)
        mkdir.assert_not_called()
        self.assertEqual(len(storage._conn.execute("PRAGMA table_info(meter_readings)").fetchall()), 24)

    def test_backup_from_different_schema_is_not_reused(self):
        self.make_old_db()
        backup_dir = self.db_path.parent / "backups"
        backup_dir.mkdir()
        previous = backup_dir / "manager.db.bak_20000101_000000"
        with closing(sqlite3.connect(previous)) as conn:
            conn.execute("CREATE TABLE older_schema (id INTEGER PRIMARY KEY)")
            conn.commit()
        original_backup = previous.read_bytes()
        Storage(str(self.db_path))
        self.assertEqual(len(self.backups()), 2)
        self.assertEqual(previous.read_bytes(), original_backup)

    def test_new_database_does_not_back_up(self):
        Storage(str(self.db_path))
        self.assertFalse(self.db_path.parent.joinpath("backups").exists())
        Storage(str(self.db_path))
        self.assertEqual(self.backups(), [])

    def test_index_failure_rolls_back_schema_and_ids_and_raises(self):
        self.make_old_db((None, "", "duplicate", "duplicate"))
        original = self.snapshot()

        class FailingCursor(sqlite3.Cursor):
            def execute(self, sql, parameters=()):
                if "CREATE UNIQUE INDEX" in sql:
                    raise sqlite3.OperationalError("injected index failure")
                return super().execute(sql, parameters)

        class FailingConnection(sqlite3.Connection):
            def cursor(self, *args, **kwargs):
                return super().cursor(factory=FailingCursor)

        real_connect = sqlite3.connect

        def connect(*args, **kwargs):
            return real_connect(*args, factory=FailingConnection, **kwargs)

        with patch("manager.storage.sqlite3.connect", side_effect=connect):
            with self.assertRaisesRegex(sqlite3.OperationalError, "injected index failure"):
                Storage(str(self.db_path))
        self.assertEqual(self.snapshot(), original)
        self.assertEqual(len(self.backups()), 1)
        backups = self.backups()
        Storage(str(self.db_path))
        self.assertEqual(self.backups(), backups)
        with closing(sqlite3.connect(self.db_path)) as conn:
            self.assertEqual(conn.execute(
                "SELECT COUNT(*) FROM meter_readings WHERE reading_id IS NULL OR reading_id = ''"
            ).fetchone()[0], 0)

    def test_save_reading_and_manager_history_remain_compatible(self):
        manager = MeterManager(str(self.db_path))
        storage = manager.storage
        result = {"value": 1.25, "stage": "ok", "status": "ok"}
        first = storage.save_reading("Pressure", "a.jpg", result, "same-hash", "first")
        second = storage.save_reading("Pressure", "a.jpg", result, "same-hash", "second")
        history = manager.get_history()
        self.assertEqual([row.id for row in history], [second, first])
        self.assertEqual(history[0].raw_data, result)
        self.assertEqual(history[0].reading_id, "second")
        self.assertEqual(history[0].value, 1.25)
        self.assertIsNone(manager.get_history(include_raw=False)[0].raw_data)
        self.assertEqual(storage.get_processed_hashes(), {"same-hash"})


if __name__ == "__main__":
    unittest.main()
