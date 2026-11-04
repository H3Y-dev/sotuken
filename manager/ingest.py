"""取り込み層：フォルダ監視で検出した画像の処理結果をDBへ保存する。

SR-05までで「監視→パイプライン実行」までは繋がっていたが、結果は画面に表示される
だけでDBに残らず、撮影から集約までの通しが切れていた。その最後の1段をここで埋める。
"""
import os
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from manager.sidecar import SidecarMetadata
from manager.storage import Storage
from manager.record import judge_failure, judge_input_method, judge_status
from manager.batch import calculate_file_hash
from manager.image_store import store_image
from manager.overlay import imread_ja, save_overlay
from manager.devices import register_device, validate_device_id
from manager.qr_decode import read_device_qr, issue_for

UNKNOWN_DEVICE = "unknown"


def device_name_from_sidecar(sidecar: Optional[SidecarMetadata]) -> str:
    """サイドカーJSONの機器名を使う。無ければ unknown で落とさず取り込む。"""
    name = getattr(sidecar, "device_name", None)
    if not name:
        return UNKNOWN_DEVICE
    return str(name)


def _sidecar_identity(sidecar):
    device_id = getattr(sidecar, "device_id", None)
    issue = getattr(sidecar, "device_id_issue", None)
    if isinstance(device_id, str) and device_id.lower() == UNKNOWN_DEVICE:
        device_id = None
    if device_id is not None and not validate_device_id(device_id):
        device_id, issue = None, "id_invalid"
    source = {"qr": "sidecar_qr", "manual": "sidecar_manual"}.get(
        getattr(sidecar, "device_id_source", None), "sidecar") if device_id else None
    return device_id, source, issue


def _register_device(storage, device_id, device_name, source):
    if device_id:
        registered = register_device(storage, device_id, device_name=device_name, source=source)
        for warning in registered.warnings:
            print(f"[機器登録] {device_id}: {warning}")


def _pipeline_version(result):
    if result.get("pipeline_version"):
        return result["pipeline_version"]
    try:
        return subprocess.check_output(
            ["git", "describe", "--tags", "--always"],
            cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            text=True, stderr=subprocess.DEVNULL, timeout=5,
        ).strip() or None
    except (OSError, subprocess.SubprocessError):
        return None


_TRUTH_FIELDS = ("operator_value", "operator_note", "scale_min", "scale_max")


def apply_sidecar(storage: Storage, image_sha256: str, sidecar: Optional[SidecarMetadata]) -> None:
    """取り込み済み画像に、後から届いたサイドカーの機器名・真値を反映する。

    画像が先に届くと sidecar=None のまま記録され、後着JSONは捨てられていた。
    読み取り結果（値・status・版・reading_id）は変えず、新しい記録も作らない。
    JSONで省略された項目は既存値を消さず、異なる有効IDは上書きしない。
    """
    if sidecar is None:
        return
    old = next((t for t in storage.get_all_image_truths() if t.image_sha256 == image_sha256), None)
    truth = {f: getattr(sidecar, f) if getattr(sidecar, f) is not None else getattr(old, f, None)
             for f in _TRUTH_FIELDS}
    if any(v is not None for v in truth.values()) and (
            old is None or any(truth[f] != getattr(old, f) for f in _TRUTH_FIELDS)):
        storage.save_image_truth(image_sha256=image_sha256, **truth)

    incoming_id, incoming_source, _ = _sidecar_identity(sidecar)
    register = False
    with storage.connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        rows = conn.execute(
            "SELECT id, device_id, device_id_source, device_id_issue, device_name, value "
            "FROM meter_readings WHERE image_sha256 = ?", (image_sha256,),
        ).fetchall()
        for row_id, device_id, source, issue, name, value in rows:
            if device_id == UNKNOWN_DEVICE:
                device_id = None
            conflict = incoming_id and device_id and incoming_id != device_id
            if conflict:
                issue = "id_conflict"
            elif incoming_id:
                if not device_id:
                    device_id, source, issue = incoming_id, incoming_source, None
                register = True
            if name == UNKNOWN_DEVICE:
                name = None
            if not name and not conflict:
                name = device_name_from_sidecar(sidecar)
            conn.execute(
                "UPDATE meter_readings SET device_id = ?, device_id_source = ?, "
                "device_id_issue = ?, device_name = ?, input_method = ?, "
                "captured_at = COALESCE(?, captured_at) WHERE id = ?",
                (device_id, source, issue, name or UNKNOWN_DEVICE, judge_input_method(value, truth["operator_value"]),
                 sidecar.captured_at, row_id),
            )
    if register:
        _register_device(storage, incoming_id, sidecar.device_name, incoming_source)


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
    try:
        received_at = datetime.fromtimestamp(os.path.getmtime(image_path), timezone.utc).isoformat(
            timespec="seconds").replace("+00:00", "Z")
    except OSError:
        received_at = None
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

    device_id, device_id_source, device_id_issue = _sidecar_identity(sidecar)
    device_name = device_name_from_sidecar(sidecar)
    registration_name = getattr(sidecar, "device_name", None)
    if not device_id:
        qr = read_device_qr(stored_image_path)
        device_id_issue = device_id_issue or issue_for(qr)
        if qr.status == "found" and qr.device_id.lower() != UNKNOWN_DEVICE:
            device_id, device_id_source = qr.device_id, "pc_qr"
            registration_name = qr.device_name
            device_name = qr.device_name if qr.device_name != UNKNOWN_DEVICE else None
    _register_device(storage, device_id, registration_name, device_id_source)

    save_data = {k: v for k, v in result.items() if k != "ticks"}
    save_data["pipeline_version"] = _pipeline_version(result)
    operator_value = getattr(sidecar, "operator_value", None) if sidecar is not None else None
    save_data["status"] = judge_status(result)
    save_data["input_method"] = judge_input_method(result.get("value"), operator_value)
    failure_stage, failure_code, failure_detail = judge_failure(result)
    save_data["failure_stage"] = failure_stage
    save_data["failure_code"] = failure_code
    save_data["failure_detail"] = failure_detail
    reading_id = str(uuid.uuid4())
    save_data["reading_id"] = reading_id
    save_data["log_path"] = None
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
    row_id = storage.save_reading(
        # shortcut: device_name は既存DBのNOT NULL制約に合わせ、B6の移行まで unknown を残す。
        device_name=device_name or UNKNOWN_DEVICE,
        image_path=stored_image_path,
        read_result=save_data,
        image_sha256=image_sha256,
    )
    image_rel = os.path.relpath(
        stored_image_path, os.path.dirname(os.path.abspath(images_dir))).replace(os.sep, "/")
    with storage.connection() as conn:
        conn.execute(
            "UPDATE meter_readings SET device_id = ?, device_id_source = ?, device_id_issue = ?, "
            "captured_at = ?, received_at = ?, image_rel = ? WHERE id = ?",
            (device_id, device_id_source, device_id_issue, getattr(sidecar, "captured_at", None),
             received_at, image_rel, row_id),
        )
    return row_id
