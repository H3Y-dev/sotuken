import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional


@dataclass
class MeterReading:
    """1件のメーター読み取り結果を表すデータモデル"""

    device_name: str
    value: Optional[float]
    stage: str
    image_path: str
    id: Optional[int] = None
    timestamp: Optional[str] = None
    raw_data: Optional[Dict[str, Any]] = None


class Storage:
    """保存層：DB（SQLite）とのやり取りのみを担当するクラス"""

    def __init__(self, db_path: str = "manager.db") -> None:
        self.db_path = db_path
        # インメモリDB（:memory:）の場合は単一接続を維持する
        if self.db_path == ":memory:":
            self._conn = sqlite3.connect(":memory:")
            self._init_db_with_conn(self._conn)
        else:
            self._conn = None
            self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        if self._conn:
            return self._conn
        return sqlite3.connect(self.db_path)

    def _init_db_with_conn(self, conn: sqlite3.Connection) -> None:
        cursor = conn.cursor()
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS meter_readings (
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
        conn.commit()

    def _init_db(self) -> None:
        """テーブルが存在しない場合は作成する"""
        with self._get_connection() as conn:
            self._init_db_with_conn(conn)

    def save_reading(
        self, device_name: str, image_path: str, read_result: Dict[str, Any]
    ) -> int:
        """read_meterが返すdictをそのまま受け取って保存する"""
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        value = read_result.get("value")
        stage = read_result.get("stage", "unknown")
        raw_data_json = json.dumps(read_result, ensure_ascii=False)

        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO meter_readings 
            (timestamp, device_name, value, stage, image_path, raw_data_json)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (now_str, device_name, value, stage, image_path, raw_data_json),
        )
        conn.commit()
        last_id = cursor.lastrowid
        if not self._conn:
            conn.close()
        return last_id

    def get_all_readings(self) -> List[MeterReading]:
        """保存されているすべての記録を取得する"""
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT id, timestamp, device_name, value, stage, image_path, raw_data_json
            FROM meter_readings
            ORDER BY id DESC
            """
        )
        rows = cursor.fetchall()
        if not self._conn:
            conn.close()

        results = []
        for row in rows:
            raw_data = json.loads(row[6]) if row[6] else None
            results.append(
                MeterReading(
                    id=row[0],
                    timestamp=row[1],
                    device_name=row[2],
                    value=row[3],
                    stage=row[4],
                    image_path=row[5],
                    raw_data=raw_data,
                )
            )
        return results