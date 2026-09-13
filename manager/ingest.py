"""取り込み層：フォルダ監視で検出した画像の処理結果をDBへ保存する。

SR-05までで「監視→パイプライン実行」までは繋がっていたが、結果は画面に表示される
だけでDBに残らず、撮影から集約までの通しが切れていた。その最後の1段をここで埋める。
"""
import os
import sys
from typing import Any, Dict, Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from manager.sidecar import SidecarMetadata
from manager.storage import Storage
from manager.record import judge_failure, judge_input_method, judge_status

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
) -> int:
    """パイプラインの戻り値を1件の記録としてDBへ保存し、行IDを返す。

    失敗した結果（stage が ok 以外）も捨てずに保存する。どの画像がどの段で落ちたかが
    分からなくなると、撮り直しの判断も失敗率の集計もできなくなるため。
    """
    save_data = {k: v for k, v in result.items() if k != "ticks"}
    operator_value = getattr(sidecar, "operator_value", None) if sidecar is not None else None
    save_data["status"] = judge_status(result)
    save_data["input_method"] = judge_input_method(result.get("value"), operator_value)
    failure_stage, failure_code, failure_detail = judge_failure(result)
    save_data["failure_stage"] = failure_stage
    save_data["failure_code"] = failure_code
    save_data["failure_detail"] = failure_detail
    if operator_value is not None:
        save_data["operator_value"] = operator_value
    return storage.save_reading(
        device_name=device_name_from_sidecar(sidecar),
        image_path=image_path,
        read_result=save_data,
    )
