import json
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional, Set


def _json_safe(obj):
    """json.dumps が扱えない値を、保存できる形へ落とす。

    meter_pipeline の戻り値には numpy の配列やスカラーが混ざる（中心座標・
    目盛りの配列など）。素の json.dumps は ndarray で TypeError を投げるため、
    フォルダ監視からの取り込みが1枚目で必ず落ちていた。
    テストは dict のモックを渡していたので numpy が入らず、素通りしていた。
    """
    if hasattr(obj, "tolist"):  # numpy の ndarray・スカラーはこれで素の型になる
        return obj.tolist()
    return str(obj)


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
    image_sha256: Optional[str] = None
    reading_id: Optional[str] = None
    status: Optional[str] = None
    input_method: Optional[str] = None
    confidence: Optional[float] = None
    failure_stage: Optional[str] = None
    failure_code: Optional[str] = None
    failure_detail: Optional[str] = None
    pipeline_version: Optional[str] = None
    log_path: Optional[str] = None
    overlay_path: Optional[str] = None


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
        columns = {row[1] for row in cursor.execute("PRAGMA table_info(meter_readings)")}
        for column, definition in (
            ("image_sha256", "TEXT"),
            ("reading_id", "TEXT"),
            ("status", "TEXT"),
            ("input_method", "TEXT"),
            ("confidence", "REAL"),
            ("failure_stage", "TEXT"),
            ("failure_code", "TEXT"),
            ("failure_detail", "TEXT"),
            ("pipeline_version", "TEXT"),
            ("log_path", "TEXT"),
            ("overlay_path", "TEXT"),
        ):
            if column not in columns:
                cursor.execute(f"ALTER TABLE meter_readings ADD COLUMN {column} {definition}")
        conn.commit()

    def _init_db(self) -> None:
        """テーブルが存在しない場合は作成する"""
        with self._get_connection() as conn:
            self._init_db_with_conn(conn)

    def save_reading(
        self,
        device_name: str,
        image_path: str,
        read_result: Dict[str, Any],
        image_sha256: Optional[str] = None,
        reading_id: Optional[str] = None,
    ) -> int:
        """read_meterが返すdictをそのまま受け取って保存する"""
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        value = read_result.get("value")
        stage = read_result.get("stage", "unknown")
        reading_id = reading_id or read_result.get("reading_id") or str(uuid.uuid4())
        raw_data_json = json.dumps(read_result, ensure_ascii=False, default=_json_safe)

        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO meter_readings 
            (timestamp, device_name, value, stage, image_path, raw_data_json, image_sha256,
             reading_id, status, input_method, confidence, failure_stage, failure_code,
             failure_detail, pipeline_version, log_path, overlay_path)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                now_str, device_name, value, stage, image_path, raw_data_json, image_sha256,
                reading_id, read_result.get("status"), read_result.get("input_method"),
                read_result.get("confidence"), read_result.get("failure_stage"),
                read_result.get("failure_code"), read_result.get("failure_detail"),
                read_result.get("pipeline_version"), read_result.get("log_path"),
                read_result.get("overlay_path"),
            ),
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
            SELECT id, timestamp, device_name, value, stage, image_path, raw_data_json, image_sha256,
                   reading_id, status, input_method, confidence, failure_stage, failure_code,
                   failure_detail, pipeline_version, log_path, overlay_path
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
                    image_sha256=row[7],
                    reading_id=row[8],
                    status=row[9],
                    input_method=row[10],
                    confidence=row[11],
                    failure_stage=row[12],
                    failure_code=row[13],
                    failure_detail=row[14],
                    pipeline_version=row[15],
                    log_path=row[16],
                    overlay_path=row[17],
                )
            )
        return results

    def get_processed_hashes(self) -> Set[str]:
        """保存済み画像のSHA-256ハッシュ一覧を取得する"""
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT image_sha256 FROM meter_readings WHERE image_sha256 IS NOT NULL"
        )
        hashes = {row[0] for row in cursor.fetchall()}
        if not self._conn:
            conn.close()
        return hashes
