"""tests/test_slim_db.py - tools/slim_db.py のユニットテスト"""

import json
import os
import shutil
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from tools.slim_db import slim_db, main


def _create_test_db(db_path: str):
    """テスト用SQLite DBを作成し、(a)〜(d)のデータを挿入する。"""
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute(
        """
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
    )

    # (a) processed_img（大きな3段配列）の後ろにほかのキーが続く行
    raw_a = {
        "stage": "ok",
        "value": 12.34,
        "ratio": 0.5,
        "processed_img": [[[10, 20, 30], [40, 50, 60]], [[70, 80, 90], [100, 110, 120]]],
        "error": None,
        "reading_id": "test-id-001",
        "log_path": "logs/test1.log",
        "overlay_path": "overlays/test1.png",
    }
    # (b) processed_img が無い行
    raw_b = {
        "stage": "ok",
        "value": 56.78,
        "error": None,
        "reading_id": "test-id-002",
    }
    # (c) raw_data_json が NULL の行
    # (d) JSON でない文字列の行
    raw_d = "THIS_IS_NOT_VALID_JSON_{{[{"

    cur.execute(
        "INSERT INTO meter_readings (timestamp, device_name, stage, image_path, raw_data_json) VALUES (?, ?, ?, ?, ?)",
        ("2026-10-30 10:00:00", "dev1", "ok", "img1.png", json.dumps(raw_a, ensure_ascii=False)),
    )
    cur.execute(
        "INSERT INTO meter_readings (timestamp, device_name, stage, image_path, raw_data_json) VALUES (?, ?, ?, ?, ?)",
        ("2026-10-30 10:01:00", "dev1", "ok", "img2.png", json.dumps(raw_b, ensure_ascii=False)),
    )
    cur.execute(
        "INSERT INTO meter_readings (timestamp, device_name, stage, image_path, raw_data_json) VALUES (?, ?, ?, ?, ?)",
        ("2026-10-30 10:02:00", "dev1", "ok", "img3.png", None),
    )
    cur.execute(
        "INSERT INTO meter_readings (timestamp, device_name, stage, image_path, raw_data_json) VALUES (?, ?, ?, ?, ?)",
        ("2026-10-30 10:03:00", "dev1", "ok", "img4.png", raw_d),
    )

    conn.commit()
    conn.close()


class TestSlimDb(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.temp_dir, "test_manager.db")
        _create_test_db(self.db_path)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_dry_run_does_not_modify_db(self):
        """--dry-run ではDBが書き換わらず、バックアップも作成されないことを確認。"""
        # 実行前の全行を取得
        conn_pre = sqlite3.connect(self.db_path)
        cur_pre = conn_pre.cursor()
        cur_pre.execute("SELECT id, raw_data_json FROM meter_readings ORDER BY id ASC")
        rows_before = cur_pre.fetchall()
        conn_pre.close()

        # dry-run 実行
        result = slim_db(self.db_path, dry_run=True, no_backup=False)

        self.assertEqual(result["processed_count"], 1)
        self.assertEqual(result["skipped_count"], 3)
        self.assertIsNone(result["backup_path"])

        # バックアップファイルが生成されていないことを確認
        files = os.listdir(self.temp_dir)
        self.assertEqual(files, ["test_manager.db"])

        # 実行後の全行を取得して比較
        conn_post = sqlite3.connect(self.db_path)
        cur_post = conn_post.cursor()
        cur_post.execute("SELECT id, raw_data_json FROM meter_readings ORDER BY id ASC")
        rows_after = cur_post.fetchall()
        conn_post.close()

        self.assertEqual(rows_before, rows_after)

    def test_slim_db_modifications_and_backup(self):
        """通常実行で (a) processed_img が消え他のキーは保持、(b)(c)(d) は不変、バックアップが作成されることを確認。"""
        result = slim_db(self.db_path, dry_run=False, no_backup=False)

        self.assertEqual(result["processed_count"], 1)
        self.assertEqual(result["skipped_count"], 3)
        self.assertIsNotNone(result["backup_path"])
        self.assertTrue(os.path.isfile(result["backup_path"]))

        # バックアップ元のデータを確認: 行(a)に processed_img が存在していること
        bak_conn = sqlite3.connect(result["backup_path"])
        bak_cur = bak_conn.cursor()
        bak_cur.execute("SELECT raw_data_json FROM meter_readings WHERE id = 1")
        bak_raw_a = json.loads(bak_cur.fetchone()[0])
        self.assertIn("processed_img", bak_raw_a)
        bak_conn.close()

        # 実行後DBのデータを確認
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()

        # (a) 行1: processed_img が消え、後ろのキーも含め他のキーが維持されている
        cur.execute("SELECT raw_data_json FROM meter_readings WHERE id = 1")
        after_a = json.loads(cur.fetchone()[0])
        self.assertNotIn("processed_img", after_a)
        self.assertEqual(after_a["stage"], "ok")
        self.assertEqual(after_a["value"], 12.34)
        self.assertEqual(after_a["ratio"], 0.5)
        self.assertIsNone(after_a["error"])
        self.assertEqual(after_a["reading_id"], "test-id-001")
        self.assertEqual(after_a["log_path"], "logs/test1.log")
        self.assertEqual(after_a["overlay_path"], "overlays/test1.png")

        # (b) 行2: processed_img が元々無いため変更されない
        cur.execute("SELECT raw_data_json FROM meter_readings WHERE id = 2")
        after_b = json.loads(cur.fetchone()[0])
        self.assertEqual(
            after_b,
            {"stage": "ok", "value": 56.78, "error": None, "reading_id": "test-id-002"},
        )

        # (c) 行3: NULL のまま
        cur.execute("SELECT raw_data_json FROM meter_readings WHERE id = 3")
        after_c = cur.fetchone()[0]
        self.assertIsNone(after_c)

        # (d) 行4: JSONでない文字列のまま
        cur.execute("SELECT raw_data_json FROM meter_readings WHERE id = 4")
        after_d = cur.fetchone()[0]
        self.assertEqual(after_d, "THIS_IS_NOT_VALID_JSON_{{[{" )

        conn.close()

    def test_no_backup_option(self):
        """--no-backup オプションではバックアップファイルが作られないことを確認。"""
        result = slim_db(self.db_path, dry_run=False, no_backup=True)
        self.assertIsNone(result["backup_path"])

        files = os.listdir(self.temp_dir)
        self.assertEqual(files, ["test_manager.db"])

    def test_insufficient_disk_space(self):
        """ディスク空き容量が不足している場合、RuntimeError で中断されDBが書き換わらないこと。"""
        # free を 0 bytes とするモック
        with patch("shutil.disk_usage", return_value=(1000000, 1000000, 0)):
            with self.assertRaises(RuntimeError) as ctx:
                slim_db(self.db_path, dry_run=False, no_backup=False)
            self.assertIn("ディスクの空き容量が不足しています", str(ctx.exception))

    def test_database_locked(self):
        """DBがロック中の場合、sqlite3.OperationalError が適切に発生すること。"""
        lock_conn = sqlite3.connect(self.db_path, timeout=0.1)
        lock_conn.execute("BEGIN EXCLUSIVE TRANSACTION")
        try:
            with self.assertRaises(sqlite3.OperationalError) as ctx:
                slim_db(self.db_path, dry_run=False, no_backup=True)
            self.assertIn("他のプロセス（watch_inbox等）で使用中", str(ctx.exception))
        finally:
            lock_conn.rollback()
            lock_conn.close()

    def test_main_cli_dry_run(self):
        """main() CLI経由で --dry-run が正常終了（コード0）することを確認。"""
        with patch("sys.argv", ["slim_db.py", self.db_path, "--dry-run"]):
            ret = main()
            self.assertEqual(ret, 0)


if __name__ == "__main__":
    unittest.main()
