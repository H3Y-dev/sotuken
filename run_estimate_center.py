import sys

import cv2
import numpy as np

from tick_detect import detect_scale_ticks
from center_estimate import estimate_center
from detect_meter_center_v2 import detect_meter_center_from_raw


def main(img_path):
    # 全角パス対応(imreadではなくimdecodeを使用)
    img = cv2.imdecode(np.fromfile(img_path, dtype=np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        print("画像を読み込めませんでした: {0}".format(img_path))
        sys.exit(1)

    h, w = img.shape[:2]

    # 画像全体を対象に目盛り探索すると、盤面が画像の一部しか
    # 占めていない実写真では背景まで探索範囲に入って誤検出する
    # (前回の実写真テストで発生した問題)。
    # detect_meter_center_v2が内部で使っているcrop_to_meter_faceの
    # クロップ範囲(crop_box)をそのまま流用し、盤面だけにクロップ
    # してから目盛り探索することで、min_dist/max_distの基準となる
    # 「画像短辺」を実際の盤面サイズに近づける。
    hough_result = detect_meter_center_from_raw(img)
    if hough_result is None:
        print("Hough円検出に失敗しました。中心を推定できません。")
        sys.exit(1)

    hx0, hy0, hx1, hy1 = hough_result["crop_box"]
    crop = img[hy0:hy1, hx0:hx1]
    print("盤面クロップ範囲: ({0}, {1}) - ({2}, {3})  {4}x{5}px".format(
        hx0, hy0, hx1, hy1, crop.shape[1], crop.shape[0]))

    # Hough中心をクロップ画像内のローカル座標に変換して起点にする
    gcx, gcy = hough_result["center"]
    seed = (gcx - hx0, gcy - hy0)
    print("クロップ画像内での起点: ({0:.1f}, {1:.1f})".format(seed[0], seed[1]))

    ticks = detect_scale_ticks(crop, seed)
    print("検出した目盛り本数: {0}".format(len(ticks)))

    result = estimate_center(crop, ticks=ticks if ticks else None)
    if result is None:
        print("estimate_centerで中心を推定できませんでした。")
        sys.exit(1)

    # クロップ画像内のローカル座標 → 元の写真上のグローバル座標に変換
    lcx, lcy = result
    cx, cy = lcx + hx0, lcy + hy0
    print("[estimate_center] 中心=({0:.1f}, {1:.1f})  (元画像上の座標)".format(cx, cy))

    # 可視化: 目盛り(黄、クロップ座標→元画像座標に変換)と
    # 推定中心(マゼンタ)、クロップ範囲(青枠)を元画像に描画
    out = img.copy()
    cv2.rectangle(out, (hx0, hy0), (hx1, hy1), (255, 128, 0), 2)
    for t in ticks:
        tx, ty = t["centroid"]
        cv2.circle(out, (int(tx) + hx0, int(ty) + hy0), 4, (255, 255, 0), -1)
    cv2.drawMarker(out, (int(cx), int(cy)), (255, 0, 255),
                    markerType=cv2.MARKER_CROSS, markerSize=40, thickness=2)

    text_lines = [
        "estimate_center: ({0:.0f}, {1:.0f})".format(cx, cy),
        "ticks: {0}".format(len(ticks)),
    ]
    for i, line in enumerate(text_lines):
        cv2.putText(out, line, (20, 40 + i * 40), cv2.FONT_HERSHEY_SIMPLEX,
                    1.0, (0, 0, 0), 5, cv2.LINE_AA)
        cv2.putText(out, line, (20, 40 + i * 40), cv2.FONT_HERSHEY_SIMPLEX,
                    1.0, (255, 255, 255), 2, cv2.LINE_AA)

    out_path = img_path.rsplit(".", 1)[0] + "_estimate_center_result.jpg"
    success, buf = cv2.imencode(".jpg", out)
    if success:
        buf.tofile(out_path)
        print("検出結果画像を出力しました: {0}".format(out_path))


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("使い方: python run_estimate_center.py 画像パス")
        sys.exit(1)
    main(sys.argv[1])

