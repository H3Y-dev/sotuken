import json
import os
from dataclasses import asdict, dataclass
from typing import Any, Dict, Optional


@dataclass
class SidecarMetadata:
    """
    S1規約に基づくサイドカーJSONのメタデータモデル。
    未入力項目は None を許容する。
    """
    local_id: Optional[str] = None
    captured_at: Optional[str] = None
    device_name: Optional[str] = None
    operator_value: Optional[float] = None
    operator_note: Optional[str] = None
    scale_min: Optional[float] = None
    scale_max: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def get_sidecar_path(image_path: str) -> str:
    """画像パスに対応する同名サイドカーJSONのパスを返す"""
    base, _ = os.path.splitext(image_path)
    return f"{base}.json"


def load_sidecar(image_or_json_path: str) -> Optional[SidecarMetadata]:
    """
    画像ファイルまたはサイドカーJSONのパスを受け取り、対応するサイドカーJSONを読み込む。
    ファイルが存在しない場合や破損している場合は None を返す。
    """
    if image_or_json_path.lower().endswith(".json"):
        json_path = image_or_json_path
    else:
        json_path = get_sidecar_path(image_or_json_path)

    if not os.path.exists(json_path):
        return None

    try:
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return None

    if not isinstance(data, dict):
        return None

    local_id = data.get("local_id")
    if local_id is not None:
        local_id = str(local_id)

    captured_at = data.get("captured_at")
    if captured_at is not None:
        captured_at = str(captured_at)

    device_name = data.get("device_name")
    if device_name is not None:
        device_name = str(device_name)

    raw_val = data.get("operator_value")
    operator_value: Optional[float] = None
    if raw_val is not None:
        try:
            operator_value = float(raw_val)
        except (ValueError, TypeError):
            operator_value = None

    operator_note = data.get("operator_note")
    if operator_note is not None:
        operator_note = str(operator_note)

    raw_scale_min = data.get("scale_min")
    scale_min: Optional[float] = None
    if raw_scale_min is not None:
        try:
            scale_min = float(raw_scale_min)
        except (ValueError, TypeError):
            scale_min = None

    raw_scale_max = data.get("scale_max")
    scale_max: Optional[float] = None
    if raw_scale_max is not None:
        try:
            scale_max = float(raw_scale_max)
        except (ValueError, TypeError):
            scale_max = None

    return SidecarMetadata(
        local_id=local_id,
        captured_at=captured_at,
        device_name=device_name,
        operator_value=operator_value,
        operator_note=operator_note,
        scale_min=scale_min,
        scale_max=scale_max,
    )
