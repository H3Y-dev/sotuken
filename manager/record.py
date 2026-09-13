from dataclasses import dataclass
from typing import Any, Mapping, Optional, Tuple


def judge_status(pipeline_result: Mapping[str, Any]) -> str:
    """自動読み取りの結果だけから記録状態を決める。"""
    if pipeline_result.get("stage") != "ok" or pipeline_result.get("value") is None:
        return "failed"
    if pipeline_result.get("scale_confident") is False:
        return "low_confidence"
    return "ok"


def judge_failure(
    pipeline_result: Mapping[str, Any],
) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """(failure_stage, failure_code, failure_detail) を返す。

    read_meter の失敗 stage は center -> center_not_found、
    scale -> scale_range_unresolved、needle -> needle_not_detected。
    それ以外の失敗は unknown -> unknown_failure として保存する。
    """
    if judge_status(pipeline_result) in ("ok", "low_confidence"):
        return None, None, None

    stage_and_code = {
        "center": ("center", "center_not_found"),
        "scale": ("scale", "scale_range_unresolved"),
        "needle": ("needle", "needle_not_detected"),
    }
    failure_stage, failure_code = stage_and_code.get(
        pipeline_result.get("stage"), ("unknown", "unknown_failure")
    )
    return failure_stage, failure_code, pipeline_result.get("error")


def judge_input_method(auto_value: Optional[float], operator_value: Optional[float]) -> str:
    """最終採用値の出所を、自動値と現場入力値の有無から決める。"""
    if auto_value is None:
        return "manual" if operator_value is not None else "auto"
    return "corrected" if operator_value is not None else "auto"


@dataclass
class Reading:
    reading_id: str  # UUID 主キー
    local_id: Optional[str]  # 端末由来。同じ画像の再処理レコード間で同じ値を持つ
    captured_at: str  # ISO 8601 撮影時刻
    received_at: str  # ISO 8601 PC取込時刻
    processed_at: str  # ISO 8601 読み取り実行時刻
    device_name: Optional[str]  # 機器名。未登録・未入力を許容
    value: Optional[float]  # 読み取り値。失敗時はnull
    unit: Optional[str]  # 単位
    status: str  # ok / low_confidence / failed: 自動読み取りの結果状態。人の入力では変化しない
    input_method: str  # auto / manual / corrected: 最終的に採用した値の出所
    confidence: Optional[float]  # 0.0〜1.0またはnull: 読み取りの信頼度
    image_path: str  # 相対パス: 保存済み原画像
    image_sha256: str  # SHA-256: 原画像のハッシュ。重複排除キー
    failure_stage: Optional[str]  # null / center / scale / needle / unknown: 失敗段階
    failure_code: Optional[str]  # 短い理由コード
    failure_detail: Optional[str]  # 人が読む失敗説明
    pipeline_version: str  # 使用したパイプラインの版。gitタグ名をそのまま入れる
    log_path: str  # 相対パス: 詳細ログ
    overlay_path: Optional[str]  # 相対パスまたはnull: 中間オーバーレイ画像


@dataclass
class ImageTruth:
    image_sha256: str  # SHA-256: キー
    operator_value: Optional[float]  # 現場で入力した真値
    operator_note: Optional[str]  # 現場の備考
    scale_min: Optional[float]  # 評価に使うフルスケール下限
    scale_max: Optional[float]  # 評価に使うフルスケール上限
    entered_at: str  # ISO 8601: 入力時刻
