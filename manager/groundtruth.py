"""保存済みImageTruthからevaluate.py互換のgroundtruth.jsonを書き出すコマンド。"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from manager.storage import Storage


def build_groundtruth_entries(readings, truths):
    """meter_readingsとimage_truthsを結合し、evaluate.py互換の配列を作る。

    readingsはStorage.get_all_readings()、truthsはStorage.get_all_image_truths()
    の戻り値。戻り値は(entries, excluded_count)で、真値・フルスケール・
    対応するreadingが欠けた画像ハッシュをexcluded_countに含める。
    """
    truths_by_hash = {truth.image_sha256: truth for truth in truths}
    readings_by_hash = {}
    for reading in readings:
        readings_by_hash.setdefault(reading.image_sha256, []).append(reading)

    image_hashes = list(truths_by_hash)
    image_hashes.extend(
        image_sha256 for image_sha256 in readings_by_hash
        if image_sha256 not in truths_by_hash
    )

    entries = []
    excluded_count = 0
    for image_sha256 in image_hashes:
        truth = truths_by_hash.get(image_sha256)
        image_readings = readings_by_hash.get(image_sha256, [])
        if (
            truth is None
            or truth.operator_value is None
            or truth.scale_min is None
            or truth.scale_max is None
            or not image_readings
        ):
            excluded_count += 1
            continue

        if all(isinstance(reading.timestamp, str) for reading in image_readings):
            latest_reading = max(
                image_readings,
                key=lambda reading: (
                    reading.timestamp,
                    reading.id if reading.id is not None else -1,
                ),
            )
        else:
            latest_reading = max(
                image_readings,
                key=lambda reading: reading.id if reading.id is not None else -1,
            )
        entries.append({
            "image": latest_reading.image_path,
            "true_value": truth.operator_value,
            "min_value": truth.scale_min,
            "max_value": truth.scale_max,
            "scope": "round",
        })

    return entries, excluded_count


def export_groundtruth(entries, output_path):
    """entries（配列）をJSONでoutput_pathへ書き出す。"""
    with open(output_path, "w", encoding="utf-8") as output_file:
        json.dump(entries, output_file, ensure_ascii=False, indent=2)


def main() -> int:
    parser = argparse.ArgumentParser(description="evaluate.py互換のgroundtruth.jsonを書き出す")
    parser.add_argument("--db", default="manager.db", help="SQLite DBのパス")
    parser.add_argument("--output", default="groundtruth.json", help="出力JSONのパス")
    args = parser.parse_args()

    storage = Storage(args.db)
    entries, excluded_count = build_groundtruth_entries(
        storage.get_all_readings(), storage.get_all_image_truths()
    )
    export_groundtruth(entries, args.output)
    print(
        f"{len(entries)}件を{args.output}へ書き出しました"
        f"（{excluded_count}件を真値/フルスケール欠損または対応データなしで除外）"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
