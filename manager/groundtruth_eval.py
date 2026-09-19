"""DBに保存されたImageTruthで自動読み取り精度を評価するコマンド。"""
import argparse
import json
import os
import sys
from typing import Any, Dict, List

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import meter_pipeline
from evaluate import (
    CATASTROPHIC_THRESHOLD_PERCENT,
    DEFAULT_TOLERANCE_PERCENT,
    is_within_tolerance,
    reference_error,
    summarize,
)
from manager.record import ImageTruth
from manager.storage import MeterReading, Storage


def build_rows(
    readings: List[MeterReading],
    truths: List[ImageTruth],
    tolerance_percent: float = DEFAULT_TOLERANCE_PERCENT,
) -> List[Dict[str, Any]]:
    """同じ画像ハッシュを持つ読み取り結果と完全な真値から評価行を作る。"""
    truths_by_hash = {truth.image_sha256: truth for truth in truths}
    rows = []
    for reading in readings:
        truth = truths_by_hash.get(reading.image_sha256)
        if truth is None or any(
            value is None for value in (
                truth.operator_value, truth.scale_min, truth.scale_max,
            )
        ):
            continue

        row = {
            "image_sha256": reading.image_sha256,
            "reading_id": reading.reading_id,
            "device_name": reading.device_name,
            "value": reading.value,
            "operator_value": truth.operator_value,
            "stage": (
                meter_pipeline.STAGE_OK
                if reading.status == meter_pipeline.STAGE_OK
                else reading.status or "failed"
            ),
            "reference_error": None,
            "within_tolerance": False,
        }
        if reading.value is not None:
            row["reference_error"] = reference_error(
                reading.value, truth.operator_value, truth.scale_min, truth.scale_max,
            )
            row["within_tolerance"] = is_within_tolerance(
                reading.value,
                truth.operator_value,
                truth.scale_min,
                truth.scale_max,
                tolerance_percent,
            )
        rows.append(row)
    return rows


def _format_percent(value: Any) -> str:
    return f"{value:.2f}%FS" if value is not None else "-"


def print_report(summary: Dict[str, Any]) -> None:
    """評価結果の最低限の集計を表示する。"""
    print(f"評価対象: {summary['total']} 件")
    print(f"読取成功数: {summary['read_ok']} 件")
    print(f"許容誤差内件数: {summary['within_tolerance']} 件")
    print(f"平均引用誤差: {_format_percent(summary['mean_reference_error'])}")
    print(f"中央値引用誤差: {_format_percent(summary['median_reference_error'])}")
    print(f"最大引用誤差: {_format_percent(summary['max_reference_error'])}")


def main() -> int:
    parser = argparse.ArgumentParser(description="保存済みImageTruthで読み取り精度を評価する")
    parser.add_argument("--db", default="manager.db", help="SQLite DBのパス")
    parser.add_argument(
        "--tolerance",
        type=float,
        default=DEFAULT_TOLERANCE_PERCENT,
        help="許容する引用誤差（%%FS）",
    )
    parser.add_argument("-o", "--output", help="評価結果JSONの出力先")
    args = parser.parse_args()

    storage = Storage(args.db)
    rows = build_rows(
        storage.get_all_readings(), storage.get_all_image_truths(), args.tolerance,
    )
    summary = summarize(rows)

    if args.output:
        with open(args.output, "w", encoding="utf-8") as output_file:
            json.dump({"rows": rows, "summary": summary}, output_file, ensure_ascii=False, indent=2)

    if not summary["total"]:
        print("評価対象のImageTruthがありません")
        return 0

    print_report(summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
