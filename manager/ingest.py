"""取り込み層：フォルダ監視で検出した画像の処理結果をDBへ保存する。

SR-05までで「監視→パイプライン実行」までは繋がっていたが、結果は画面に表示される
だけでDBに残らず、撮影から集約までの通しが切れていた。その最後の1段をここで埋める。
"""
import os
import sys
import json
import uuid
from typing import Any, Dict, Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from manager.sidecar import SidecarMetadata
from manager.storage import Storage, _json_safe
from manager.record import judge_failure, judge_input_method, judge_status
from manager.batch import calculate_file_hash
from manager.image_store import store_image

UNKNOWN_DEVICE = "unknown"


def device_name_from_sidecar(sidecar: Optional[SidecarMetadata]) -> str:
    """サイドカーJSONの機器名を使う。無ければ unknown で落とさず取り込む。"""
    if sidecar is None:
        return UNKNOWN_DEVICE
    name = getattr(sidecar, "device_name", None)
    if not name:
        return UNKNOWN_DEVICE
    return str(name)


def ingest_result(
    storage: Storage,
    image_path: str,
    sidecar: Optional[SidecarMetadata],
    result: Dict[str, Any],
    images_dir: str = "images",
) -> Optional[int]:
    """パイプライン結果を保存し、重複画像なら None を返す。

    失敗した結果（stage が ok 以外）も捨てずに保存する。どの画像がどの段で落ちたかが
    分からなくなると、撮り直しの判断も失敗率の集計もできなくなるため。
    """
    image_sha256 = None
    stored_image_path = image_path
    try:
        image_sha256 = calculate_file_hash(image_path)
        if image_sha256 in storage.get_processed_hashes():
            return None
        stored_image_path = store_image(image_path, images_dir)
    except Exception as exc:
        print(f"[画像保存] ハッシュ計算または恒久保存に失敗: {exc}")
        image_sha256 = None

    save_data = {k: v for k, v in result.items() if k != "ticks"}
    operator_value = getattr(sidecar, "operator_value", None) if sidecar is not None else None
    save_data["status"] = judge_status(result)
    save_data["input_method"] = judge_input_method(result.get("value"), operator_value)
    failure_stage, failure_code, failure_detail = judge_failure(result)
    save_data["failure_stage"] = failure_stage
    save_data["failure_code"] = failure_code
    save_data["failure_detail"] = failure_detail
    reading_id = str(uuid.uuid4())
    save_data["reading_id"] = reading_id
    log_path = None
    try:
        os.makedirs("logs", exist_ok=True)
        log_path = f"logs/{reading_id}.log"
        with open(log_path, "w", encoding="utf-8") as log_file:
            json.dump(result, log_file, ensure_ascii=False, default=_json_safe, indent=2)
    except Exception:
        log_path = None
    save_data["log_path"] = log_path
    # オーバーレイ生成は未実装。YM-06の残作業。
    save_data["overlay_path"] = None
    if operator_value is not None:
        save_data["operator_value"] = operator_value
    operator_note = getattr(sidecar, "operator_note", None) if sidecar is not None else None
    scale_min = getattr(sidecar, "scale_min", None) if sidecar is not None else None
    scale_max = getattr(sidecar, "scale_max", None) if sidecar is not None else None
    if image_sha256 is not None and any(
        value is not None for value in (operator_value, operator_note, scale_min, scale_max)
    ):
        storage.save_image_truth(
            image_sha256=image_sha256,
            operator_value=operator_value,
            operator_note=operator_note,
            scale_min=scale_min,
            scale_max=scale_max,
        )
    return storage.save_reading(
        device_name=device_name_from_sidecar(sidecar),
        image_path=stored_image_path,
        read_result=save_data,
        image_sha256=image_sha256,
    )
