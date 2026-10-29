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

from record import judge_failure, judge_input_method, judge_status
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
        image_sha256: Optional[str] = None,
        overlays_dir: Optional[str] = None,
        images_dir: Optional[str] = None,
    ) -> Dict[str, Any]:
        """認識処理を実行し、閾値判定を付与した結果を返却

        overlays_dir を渡すと、検出結果のオーバーレイ画像をそこへ保存し、
        記録の overlay_path に残す（フォルダ取り込みの ingest と同じ保存先・形式）。
        images_dir を渡すと、原画像を内容ハッシュ名でそこへ複製し、記録はその複製を指す
        （app.py は temp 画像を読み取り後に消すため、渡さないと記録が消えたファイルを指す）。
        複製に失敗したら例外を投げ、記録は作らない。
        """
        if images_dir is not None:
            from manager.batch import calculate_file_hash
            from manager.image_store import store_image
            image_path = store_image(image_path, images_dir)
            image_sha256 = calculate_file_hash(image_path)

        try:
            read_result: Dict[str, Any] = reader_func(image_path, use_vlm=use_vlm)
        except TypeError:
            read_result: Dict[str, Any] = reader_func(image_path)

        overlay_path = None
        if overlays_dir is not None:
            # 描画にパイプライン側のモジュールを使うので、必要なときだけ読み込む
            import uuid
            from overlay import imread_ja, save_overlay
            try:
                overlay_path = save_overlay(
                    imread_ja(image_path), read_result, overlays_dir, str(uuid.uuid4()))
            except Exception:
                overlay_path = None

        save_data = {k: v for k, v in read_result.items() if k != "ticks"}
        if overlay_path is not None:
            save_data["overlay_path"] = overlay_path
        # ingest / reprocess と同じ判定を残す。読み取り側が既に持つ値は上書きしない
        if "status" not in save_data:
            save_data["status"] = judge_status(read_result)
        if "input_method" not in save_data:
            save_data["input_method"] = judge_input_method(read_result.get("value"), None)
        if "failure_stage" not in save_data:
            (save_data["failure_stage"], save_data["failure_code"],
             save_data["failure_detail"]) = judge_failure(read_result)

        row_id = self.storage.save_reading(
            device_name=device_name,
            image_path=image_path,
            read_result=save_data,
            image_sha256=image_sha256,
        )

        readings = self.storage.get_all_readings(include_raw=False)
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
            "overlay_path": overlay_path,
        }

    def get_history(self, include_raw: bool = True) -> List[MeterReading]:
        return self.storage.get_all_readings(include_raw=include_raw)

    def format_history_for_cli(self) -> str:
        readings = self.get_history(include_raw=False)
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

    def format_history_for_ui(
        self, readings: Optional[List[MeterReading]] = None,
    ) -> List[Dict[str, Any]]:
        if readings is None:
            readings = self.get_history(include_raw=False)
        return [
            {
                "id": r.id,
                "timestamp": r.timestamp,
                "device_name": r.device_name,
                "stage": r.stage,
                "value": r.value,
                "pipeline_version": r.pipeline_version,
                "image_path": r.image_path,
                "overlay_path": r.overlay_path,
                "status": (
                    {"ok": "SUCCESS", "low_confidence": "LOW_CONFIDENCE", "failed": "FAILED"}.get(
                        r.status, r.status
                    )
                    if r.status is not None
                    else ("SUCCESS" if r.stage == "ok" else "FAILED")
                ),
                "failure_stage": r.failure_stage,
                "failure_code": r.failure_code,
                "failure_detail": r.failure_detail,
            }
            for r in readings
        ]

