import os
import sys
from typing import Any, Dict, List, Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from storage import MeterReading, Storage


class MeterManager:
    """管理層：画像認識とDB保存の連携・表示用整形を制御するメインクラス"""

    def __init__(self, db_path: str = "manager.db") -> None:
        self.storage = Storage(db_path)

    def process_image(
        self,
        image_path: str,
        device_name: str,
        reader_func: Any,
    ) -> MeterReading:
        """1枚のメーター画像を読み取り、結果を保存して返却する"""
        read_result: Dict[str, Any] = reader_func(image_path)

        row_id = self.storage.save_reading(
            device_name=device_name,
            image_path=image_path,
            read_result=read_result,
        )

        readings = self.storage.get_all_readings()
        for r in readings:
            if r.id == row_id:
                return r

        return MeterReading(
            id=row_id,
            device_name=device_name,
            value=read_result.get("value"),
            stage=read_result.get("stage", "unknown"),
            image_path=image_path,
            raw_data=read_result,
        )

    def get_history(self) -> List[MeterReading]:
        """全読み取り履歴を取得する"""
        return self.storage.get_all_readings()

    def format_history_for_cli(self) -> str:
        """CLI出力用に履歴をテキストテーブル形式で整形する"""
        readings = self.get_history()
        if not readings:
            return "履歴データがありません。"

        lines = [
            f"{'ID':<5} | {'Timestamp':<19} | {'Device':<15} | {'Stage':<8} | {'Value':<8}",
            "-" * 65,
        ]
        for r in readings:
            val_str = f"{r.value:.2f}" if r.value is not None else "N/A"
            lines.append(
                f"{r.id:<5} | {r.timestamp or '':<19} | {r.device_name:<15} | {r.stage:<8} | {val_str:<8}"
            )
        return "\n".join(lines)

    def format_history_for_ui(self) -> List[Dict[str, Any]]:
        """GUI/Web UI用に履歴を辞書型のリストとして整形する"""
        readings = self.get_history()
        return [
            {
                "id": r.id,
                "timestamp": r.timestamp,
                "device_name": r.device_name,
                "stage": r.stage,
                "value": r.value,
                "image_path": r.image_path,
                "status": "SUCCESS" if r.stage == "ok" else "FAILED",
            }
            for r in readings
        ]