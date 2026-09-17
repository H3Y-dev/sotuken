"""保存済み原画像を指定したパイプライン版で再処理するSR-07コマンド。"""
import argparse
import os
import sys
from typing import List, Optional, Tuple

import cv2
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import meter_pipeline
from manager.batch import calculate_file_hash
from manager.ingest import UNKNOWN_DEVICE, judge_failure, judge_input_method, judge_status
from manager.storage import Storage

VALID_IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png")


def reprocess_image(
    storage: Storage,
    image_path: str,
    pipeline_version: str,
    use_vlm: bool = False,
) -> int:
    """原画像を再処理し、既存レコードを変更せず新しい結果を保存する。"""
    image_path = str(image_path)
    image = cv2.imdecode(np.fromfile(image_path, dtype=np.uint8), cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError(f"画像を読み込めません: {image_path}")

    result = meter_pipeline.read_meter(image, use_vlm=use_vlm)
    save_data = {key: value for key, value in result.items() if key != "ticks"}
    save_data["status"] = judge_status(result)
    save_data["input_method"] = judge_input_method(result.get("value"), None)
    failure_stage, failure_code, failure_detail = judge_failure(result)
    save_data["failure_stage"] = failure_stage
    save_data["failure_code"] = failure_code
    save_data["failure_detail"] = failure_detail
    save_data["pipeline_version"] = pipeline_version

    return storage.save_reading(
        device_name=UNKNOWN_DEVICE,
        image_path=image_path,
        read_result=save_data,
        image_sha256=calculate_file_hash(image_path),
    )


def reprocess_all(
    storage: Storage,
    images_dir: str = "images",
    pipeline_version: Optional[str] = None,
    use_vlm: bool = False,
) -> Tuple[int, List[str]]:
    """指定フォルダの全画像を再処理し、成功件数と失敗パスを返す。"""
    succeeded = 0
    failed_paths = []
    if not os.path.isdir(images_dir):
        return succeeded, failed_paths

    for filename in sorted(os.listdir(images_dir)):
        image_path = os.path.join(images_dir, filename)
        if not os.path.isfile(image_path) or not filename.lower().endswith(VALID_IMAGE_EXTENSIONS):
            continue
        try:
            reprocess_image(storage, image_path, pipeline_version, use_vlm)
            succeeded += 1
        except Exception:
            failed_paths.append(image_path)
    return succeeded, failed_paths


def main() -> int:
    parser = argparse.ArgumentParser(description="保存済み原画像を再処理して新しい版の結果を保存します")
    parser.add_argument("--images-dir", default="images", help="再処理する原画像フォルダ")
    parser.add_argument("--db", default="manager.db", help="保存先SQLite DBのパス")
    parser.add_argument("--pipeline-version", required=True, help="保存するパイプライン版")
    parser.add_argument("--use-vlm", action="store_true", help="VLM（Ollama）を使用する")
    args = parser.parse_args()

    succeeded, failed_paths = reprocess_all(
        Storage(args.db), args.images_dir, args.pipeline_version, args.use_vlm,
    )
    print(f"再処理成功: {succeeded} 件")
    if failed_paths:
        print("再処理失敗:")
        for path in failed_paths:
            print(f"  {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
