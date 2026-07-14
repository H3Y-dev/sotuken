"""
メーター検出結果のログ保存

検出が完了するたびに、検出に使用した画像（PNG）と検出結果（JSON）を
logs/ ディレクトリにタイムスタンプ付きのペアで保存する。
"""
import os
import json
import datetime
import cv2

LOG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")


def save_detection_log(image, result, source_path=None, log_dir=LOG_DIR):
    """
    image: 検出に使用した画像（BGR, np.ndarray）
    result: 検出結果を表すdict（JSONシリアライズ可能な値のみ）
    source_path: 元画像ファイルのパス（わかれば記録する。任意）
    戻り値: (image_path, json_path)
    """
    os.makedirs(log_dir, exist_ok=True)
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]

    image_path = os.path.join(log_dir, f"{timestamp}.png")
    json_path = os.path.join(log_dir, f"{timestamp}.json")

    # 日本語パスでも保存できるよう imencode + tofile を使う（cv2.imwrite は非対応）
    ok, buf = cv2.imencode(".png", image)
    if ok:
        buf.tofile(image_path)

    record = {
        "timestamp": timestamp,
        "source_image": source_path,
        "scanned_image": os.path.basename(image_path),
        **result,
    }
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(record, f, ensure_ascii=False, indent=2)

    return image_path, json_path
