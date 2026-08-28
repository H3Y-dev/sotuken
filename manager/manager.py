import csv
import os
import sys
from typing import Any, Dict, List, Optional

# このファイル自身のフォルダを検索パスに追加してから storage を読み込む。
# こう書くと、次のどちらの呼ばれ方でも動く:
#   - テスト側: sys.path に manager/ を追加して `from manager import MeterManager`
#     （manager.py 自体がトップレベルのモジュールとして読み込まれる）
#   - アプリ側: `from manager.manager import MeterManager`（パッケージ経由）
# `from manager.storage import ...` と書くと前者で
# 「'manager' is not a package」になり、テストが壊れる。
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from storage import MeterReading, Storage


class MeterManager:
    """管理層：画像認識とDB保存の連携・表示・CSV出力・閾値判定を制御するメインクラス"""

    def __init__(self, db_path: str = "manager.db") -> None:
        self.storage = Storage(db_path)

    def process_image(
        self,
        image_path: str,
        device_name: str,
        reader_func: Any,
        threshold_max: Optional[float] = None,
        threshold_min: Optional[float] = None,
        use_vlm: bool = False,
    ) -> Dict[str, Any]:
        """認識処理を実行し、閾値判定を付与した結果を返却"""
        try:
            read_result: Dict[str, Any] = reader_func(image_path, use_vlm=use_vlm)
        except TypeError:
            read_result: Dict[str, Any] = reader_func(image_path)

        save_data = {k: v for k, v in read_result.items() if k != "ticks"}

        row_id = self.storage.save_reading(
            device_name=device_name,
            image_path=image_path,
            read_result=save_data,
        )

        readings = self.storage.get_all_readings()
        reading_obj = None
        for r in readings:
            if r.id == row_id:
                reading_obj = r
                break

        val = read_result.get("value")
        is_alert = False
        alert_message = ""

        # 閾値チェック判定
        if val is not None:
            if threshold_max is not None and val > threshold_max:
                is_alert = True
                alert_message = f"上限閾値 ({threshold_max}) を超過しています！"
            elif threshold_min is not None and val < threshold_min:
                is_alert = True
                alert_message = f"下限閾値 ({threshold_min}) を下回っています！"

        return {
            "reading": reading_obj,
            "val": val,
            "stage": read_result.get("stage", "unknown"),
            "is_alert": is_alert,
            "alert_message": alert_message,
        }

    def get_history(self) -> List[MeterReading]:
        return self.storage.get_all_readings()

    def format_history_for_cli(self) -> str:
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

    def export_to_csv(self, output_path: str = "readings_export.csv") -> str:
        """保存されている全履歴を CSV ファイルに出力する"""
        readings = self.get_history()
        fieldnames = [
            "id",
            "timestamp",
            "device_name",
            "stage",
            "value",
            "image_path",
        ]

        with open(output_path, mode="w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for r in readings:
                writer.writerow(
                    {
                        "id": r.id,
                        "timestamp": r.timestamp,
                        "device_name": r.device_name,
                        "stage": r.stage,
                        "value": r.value if r.value is not None else "",
                        "image_path": r.image_path,
                    }
                )
        return os.path.abspath(output_path)