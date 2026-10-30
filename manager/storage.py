import json
import logging
import sqlite3
import uuid
from contextlib import closing, contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from manager.record import ImageTruth


_RAW_DATA_EXCLUDE_KEYS = {"processed_img"}


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
            try:
                self._init_db_with_conn(self._conn)
            except Exception:
                self._conn.close()
                raise
        else:
            self._conn = None
            self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        if self._conn:
            return self._conn
        return sqlite3.connect(self.db_path)

    @contextmanager
    def connection(self):
        """Commit or roll back a transaction, keeping in-memory databases open."""
        conn = self._get_connection()
        try:
            with conn:
                yield conn
        finally:
            if conn is not self._conn:
                conn.close()

    def _init_db_with_conn(self, conn: sqlite3.Connection) -> None:
        cursor = conn.cursor()
        additional_columns = (
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
            ("device_id", "TEXT"),
            ("device_id_source", "TEXT"),
            ("device_id_issue", "TEXT"),
            ("captured_at", "TEXT"),
            ("received_at", "TEXT"),
            ("image_rel", "TEXT"),
        )
        tables = {row[0] for row in cursor.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
        )}
        columns = {row[1] for row in cursor.execute("PRAGMA table_info(meter_readings)")}
        needs_migration = (
            not {"meter_readings", "image_truths", "devices"}.issubset(tables)
            or any(column not in columns for column, _ in additional_columns)
        )
        if self.db_path != ":memory:" and tables and needs_migration:
            self._backup_db(conn)

        # SQLiteのDDLも戻せるよう、最初のCREATEより前に明示的に開始する。
        cursor.execute("BEGIN IMMEDIATE")
        try:
            repaired_count = self._create_schema(cursor, additional_columns)
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        if repaired_count:
            logging.getLogger(__name__).info("Repaired %d legacy reading_id rows", repaired_count)

    def _backup_db(self, conn: sqlite3.Connection) -> None:
        db_path = Path(self.db_path)
        backup_dir = db_path.parent / "backups"
        backup_dir.mkdir(parents=True, exist_ok=True)
        schema_query = "SELECT type, name, sql FROM sqlite_master ORDER BY type, name"
        schema = conn.execute(schema_query).fetchall()
        for existing in backup_dir.iterdir():
            if existing.is_file() and existing.name.startswith(f"{db_path.name}.bak_"):
                with closing(sqlite3.connect(existing.resolve().as_uri() + "?mode=ro", uri=True)) as backup_conn:
                    if backup_conn.execute(schema_query).fetchall() == schema:
                        return
        backup_path = backup_dir / f"{db_path.name}.bak_{datetime.now():%Y%m%d_%H%M%S}"
        backup_path.touch(exist_ok=False)
        try:
            with closing(sqlite3.connect(backup_path)) as backup_conn:
                conn.backup(backup_conn)
        except Exception:
            backup_path.unlink()
            raise

    def _create_schema(self, cursor: sqlite3.Cursor, additional_columns) -> int:
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
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS devices (
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
            )
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS image_truths (
                image_sha256 TEXT PRIMARY KEY,
                operator_value REAL,
                operator_note TEXT,
                scale_min REAL,
                scale_max REAL,
                entered_at TEXT NOT NULL
            )
            """
        )
        columns = {row[1] for row in cursor.execute("PRAGMA table_info(meter_readings)")}
        for column, definition in additional_columns:
            if column not in columns:
                cursor.execute(f"ALTER TABLE meter_readings ADD COLUMN {column} {definition}")
        cursor.execute(
            """
            UPDATE meter_readings SET reading_id = 'legacy:' || id
            WHERE reading_id IS NULL OR reading_id = '' OR id NOT IN (
                SELECT MIN(id) FROM meter_readings GROUP BY reading_id
            )
            """
        )
        repaired_count = cursor.rowcount
        if cursor.execute(
            "SELECT reading_id FROM meter_readings GROUP BY reading_id HAVING COUNT(*) > 1 LIMIT 1"
        ).fetchone() is not None:
            raise sqlite3.IntegrityError("reading_id migration left duplicate IDs")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_meter_readings_device_id ON meter_readings(device_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_meter_readings_image_sha256 ON meter_readings(image_sha256)")
        cursor.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_meter_readings_reading_id "
            "ON meter_readings(reading_id) WHERE reading_id IS NOT NULL"
        )
        return repaired_count

    def _init_db(self) -> None:
        """テーブルが存在しない場合は作成する"""
        with closing(self._get_connection()) as conn:
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
        raw_data = {key: value for key, value in read_result.items()
                    if key not in _RAW_DATA_EXCLUDE_KEYS}
        raw_data_json = json.dumps(raw_data, ensure_ascii=False, default=_json_safe)

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

    def update_reading_metadata(self, row_id: int, device_name: str, input_method: str) -> None:
        """後着サイドカーで分かった機器名と値の出所だけを書き換える。読み取り結果には触れない。"""
        conn = self._get_connection()
        conn.execute(
            "UPDATE meter_readings SET device_name = ?, input_method = ? WHERE id = ?",
            (device_name, input_method, row_id),
        )
        conn.commit()
        if not self._conn:
            conn.close()

    def save_image_truth(
        self,
        image_sha256: str,
        operator_value: Optional[float] = None,
        operator_note: Optional[str] = None,
        scale_min: Optional[float] = None,
        scale_max: Optional[float] = None,
        entered_at: Optional[str] = None,
    ) -> None:
        """画像ハッシュに対応する教師データを保存する。"""
        if entered_at is None:
            entered_at = datetime.now().isoformat()
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT OR REPLACE INTO image_truths
            (image_sha256, operator_value, operator_note, scale_min, scale_max, entered_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (image_sha256, operator_value, operator_note, scale_min, scale_max, entered_at),
        )
        conn.commit()
        if not self._conn:
            conn.close()

    def get_all_readings(self, include_raw: bool = True) -> List[MeterReading]:
        """保存されているすべての記録を取得する"""
        conn = self._get_connection()
        cursor = conn.cursor()
        raw_column = "raw_data_json" if include_raw else "NULL"
        cursor.execute(
            f"""
            SELECT id, timestamp, device_name, value, stage, image_path, {raw_column}, image_sha256,
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

    def get_all_image_truths(self) -> List[ImageTruth]:
        """保存されているすべての画像教師データを取得する。"""
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT image_sha256, operator_value, operator_note, scale_min, scale_max, entered_at
            FROM image_truths
            """
        )
        rows = cursor.fetchall()
        if not self._conn:
            conn.close()

        return [
            ImageTruth(
                image_sha256=row[0],
                operator_value=row[1],
                operator_note=row[2],
                scale_min=row[3],
                scale_max=row[4],
                entered_at=row[5],
            )
            for row in rows
        ]

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
