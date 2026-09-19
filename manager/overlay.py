"""メーター読み取り結果を目視確認用の画像へ描画する。"""
import os

import cv2
import numpy as np

import meter_reader
import tick_detect


def imread_ja(path):
    """全角パス対応の画像読み込み"""
    return cv2.imdecode(np.fromfile(path, dtype=np.uint8), cv2.IMREAD_COLOR)


def draw_detection_overlay(image, result):
    """meter_pipeline.read_meterの結果を画像に描き込んだコピーを返す。"""
    center = result.get("center")
    if center is None:
        return image.copy()

    # 座標はクロップ・向き補正後の画像を基準にしている。
    processed_image = result.get("processed_img")
    if processed_image is not None:
        image = processed_image
    out = image.copy()
    ticks = result.get("ticks")
    if not ticks:
        try:
            ticks = tick_detect.detect_scale_ticks(
                tick_detect.apply_clahe(image, clip_limit=2.0), center)
        except Exception:
            ticks = []
    for tick in ticks:
        point = (int(tick["centroid"][0]), int(tick["centroid"][1]))
        color = (255, 0, 255) if tick.get("is_major") else (0, 255, 0)
        cv2.circle(out, point, 7, color, 2 if tick.get("synthetic") else -1)

    cv2.drawMarker(out, tuple(center), (0, 255, 255), cv2.MARKER_CROSS, 46, 4)
    try:
        needle = meter_reader.detect_needle(image, center)
    except Exception:
        needle = None
    if needle is not None:
        x1, y1, x2, y2 = needle["line"]
        cv2.line(out, (x1, y1), (x2, y2), (0, 0, 255), 4)

    if result.get("zero_pt") is not None:
        cv2.circle(out, tuple(result["zero_pt"]), 20, (0, 200, 255), 4)
    if result.get("full_pt") is not None:
        cv2.circle(out, tuple(result["full_pt"]), 20, (255, 0, 255), 4)
    return out


def save_overlay(image, result, output_dir, reading_id):
    """検出オーバーレイを保存し、作業ディレクトリからの相対パスを返す。"""
    if result.get("center") is None:
        return None
    try:
        os.makedirs(output_dir, exist_ok=True)
        output_path = os.path.join(output_dir, f"{reading_id}.jpg")
        ok, buffer = cv2.imencode(".jpg", draw_detection_overlay(image, result))
        if not ok:
            return None
        buffer.tofile(output_path)
        return os.path.relpath(output_path).replace(os.sep, "/")
    except Exception:
        return None
