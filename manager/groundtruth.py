"""保存済みImageTruthをgroundtruth.jsonとして書き出すコマンド。"""
import argparse
import json
import os
import sys
from typing import List

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from manager.record import ImageTruth
from manager.storage import Storage


def export_groundtruth(image_truths: List[ImageTruth], output_path: str) -> None:
    """画像ハッシュをキーとする教師データJSONを書き出す。"""
    data = {
        truth.image_sha256: {
            "operator_value": truth.operator_value,
            "operator_note": truth.operator_note,
            "scale_min": truth.scale_min,
            "scale_max": truth.scale_max,
            "entered_at": truth.entered_at,
        }
        for truth in image_truths
    }
    with open(output_path, "w", encoding="utf-8") as output_file:
        json.dump(data, output_file, ensure_ascii=False, indent=2)


def main() -> int:
    parser = argparse.ArgumentParser(description="ImageTruthをgroundtruth.jsonへ書き出す")
    parser.add_argument("--db", default="manager.db", help="SQLite DBのパス")
    parser.add_argument("--output", default="groundtruth.json", help="出力JSONのパス")
    args = parser.parse_args()

    image_truths = Storage(args.db).get_all_image_truths()
    export_groundtruth(image_truths, args.output)
    print(f"{len(image_truths)}件のImageTruthを{args.output}へ書き出しました")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
