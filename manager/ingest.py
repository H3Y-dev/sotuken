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
from manager.overlay import imread_ja, save_overlay

UNKNOWN_DEVICE = "unknown"


def device_name_from_sidecar(sidecar: Optional[SidecarMetadata]) -> str:
    """サイドカーJSONの機器名を使う。無ければ unknown で落とさず取り込む。"""
    if sidecar is None:
        return UNKNOWN_DEVICE
    name = getattr(sidecar, "device_name", None)
    if not name:
        return UNKNOWN_DEVICE
    return str(name)


_TRUTH_FIELDS = ("operator_value", "operator_note", "scale_min", "scale_max")


def apply_sidecar(storage: Storage, image_sha256: str, sidecar: Optional[SidecarMetadata]) -> None:
    """取り込み済み画像に、後から届いたサイドカーの機器名・真値を反映する。

    画像が先に届くと sidecar=None のまま記録され、後着JSONは捨てられていた。
    読み取り結果（値・status・版・reading_id）は変えず、新しい記録も作らない。
    JSONで省略された項目は既存の真値を消さない。機器名は unknown の記録だけ埋める。
    """
    if sidecar is None:
        return
    old = next((t for t in storage.get_all_image_truths() if t.image_sha256 == image_sha256), None)
    truth = {f: getattr(sidecar, f) if getattr(sidecar, f) is not None else getattr(old, f, None)
             for f in _TRUTH_FIELDS}
    if any(v is not None for v in truth.values()) and (
            old is None or any(truth[f] != getattr(old, f) for f in _TRUTH_FIELDS)):
        storage.save_image_truth(image_sha256=image_sha256, **truth)

    for reading in storage.get_all_readings(include_raw=False):
        if reading.image_sha256 != image_sha256:
            continue
        device_name = reading.device_name
        if device_name == UNKNOWN_DEVICE and sidecar.device_name:
            device_name = sidecar.device_name
        input_method = judge_input_method(reading.value, truth["operator_value"])
        if (device_name, input_method) != (reading.device_name, reading.input_method):
            storage.update_reading_metadata(reading.id, device_name, input_method)


def ingest_result(
    storage: Storage,
    image_path: str,
    sidecar: Optional[SidecarMetadata],
    result: Dict[str, Any],
    images_dir: str = "images",
    overlays_dir: str = "overlays",
) -> Optional[int]:
    """パイプライン結果を保存し、重複画像なら None を返す。

    失敗した結果（stage が ok 以外）も捨てずに保存する。どの画像がどの段で落ちたかが
    分からなくなると、撮り直しの判断も失敗率の集計もできなくなるため。
    """
    image_sha256 = None
    stored_image_path = image_path
    duplicate = False
    try:
        image_sha256 = calculate_file_hash(image_path)
        duplicate = image_sha256 in storage.get_processed_hashes()
        if not duplicate:
            stored_image_path = store_image(image_path, images_dir)
    except Exception as exc:
        print(f"[画像保存] ハッシュ計算または恒久保存に失敗: {exc}")
        image_sha256 = None

    if duplicate:
        # 記録は増やさないが、今回のサイドカーの機器名・真値は既存記録へ反映する。
        # 反映の失敗を上の SHA=None フォールバックに入れると、重複記録が作られてしまう
        try:
            apply_sidecar(storage, image_sha256, sidecar)
        except Exception as exc:
            print(f"[サイドカー反映] 失敗（記録は追加しません）: {exc}")
        return None

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
    save_data["overlay_path"] = None
    if save_data["status"] != "failed":
        try:
            image = imread_ja(stored_image_path)
            save_data["overlay_path"] = save_overlay(image, result, overlays_dir, reading_id)
        except Exception:
            pass
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
