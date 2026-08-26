import sys

import cv2
import numpy as np

from tick_detect import detect_scale_ticks
from center_estimate import estimate_center
from circle_fit import fit_circle_to_ticks
from detect_meter_center_v2 import detect_meter_center_from_raw
from center_consensus import resolve_center_consensus


def main(img_path):
    # 全角パス対応(imreadではなくimdecodeを使用)
    img = cv2.imdecode(np.fromfile(img_path, dtype=np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        print("画像を読み込めませんでした: {0}".format(img_path))
        sys.exit(1)

    # ---- 候補1: Hough円検出 ----
    hough_result = detect_meter_center_from_raw(img)
    if hough_result is None:
        print("Hough円検出に失敗しました。以降の目盛り探索の起点が作れないため終了します。")
        sys.exit(1)

    hcx, hcy = hough_result["center"]
    hr = hough_result["radius"]
    print("[候補1: Hough円検出]      中心=({0}, {1})  半径={2}px".format(hcx, hcy, hr))

    # 目盛り探索は盤面だけにクロップした画像に対して行う
    hx0, hy0, hx1, hy1 = hough_result["crop_box"]
    crop = img[hy0:hy1, hx0:hx1]
    seed = (hcx - hx0, hcy - hy0)

    ticks = detect_scale_ticks(crop, seed)
    print("検出した目盛り本数: {0}".format(len(ticks)))

    if len(ticks) < 3:
        print("目盛りが少なすぎるため、候補2・候補3は計算できません。")
        sys.exit(1)

    # center_consensusに渡す一致度判定・ネジ誤検出対策は元画像の座標系で行うため、
    # crop座標系のticksを元画像座標系に変換しておく(Hough候補もticks候補も元画像座標系)
    ticks_global = [
        {"centroid": (t["centroid"][0] + hx0, t["centroid"][1] + hy0)} for t in ticks
    ]

    # ---- 候補2: estimate_center(目盛り線の交点) ----
    est_local = estimate_center(crop, ticks=ticks)
    if est_local is not None:
        ecx, ecy = est_local[0] + hx0, est_local[1] + hy0
        estimate_global = (ecx, ecy)
        print("[候補2: estimate_center]  中心=({0:.1f}, {1:.1f})".format(ecx, ecy))
    else:
        ecx, ecy = None, None
        estimate_global = None
        print("[候補2: estimate_center]  推定失敗(None)")

    # ---- 候補3: 円フィッティング(Taubin法) ----
    fit_result = fit_circle_to_ticks(ticks, method="taubin")
    fcx_local, fcy_local = fit_result["center"]
    fr = fit_result["radius"]
    fcx, fcy = fcx_local + hx0, fcy_local + hy0
    fit_result_global = {"center": (fcx, fcy), "radius": fr, "method": fit_result.get("method")}
    print("[候補3: 円フィッティング]  中心=({0:.1f}, {1:.1f})  半径={2:.1f}px".format(fcx, fcy, fr))

    # ---- 3候補の中心座標同士の差(参考値) ----
    if ecx is not None:
        print("中心座標の差: Hough-estimate={0:.1f}px  Hough-fit={1:.1f}px  estimate-fit={2:.1f}px".format(
            np.hypot(hcx - ecx, hcy - ecy),
            np.hypot(hcx - fcx, hcy - fcy),
            np.hypot(ecx - fcx, ecy - fcy),
        ))
    else:
        print("中心座標の差: Hough-fit={0:.1f}px".format(np.hypot(hcx - fcx, hcy - fcy)))

    # ---- 3候補の採用/棄却判定(center_consensus.py) ----
    # Hough候補はそのまま渡す(center_consensus内部で半径相互チェック・
    # 目盛り重心群距離チェックによるネジ誤検出対策が行われる)
    final_center, source = resolve_center_consensus(
        hough_result, estimate_global, fit_result_global, img.shape, ticks=ticks_global
    )

    if final_center is None:
        print("[採用判定] 3候補が一致せず棄却されました(center=None, source=None)")
    else:
        fx, fy = final_center
        print("[採用判定] 中心=({0:.1f}, {1:.1f})  source={2}".format(fx, fy, source))

    # ---- 可視化: 3候補 + 最終採用結果 ----
    out = img.copy()
    cv2.rectangle(out, (hx0, hy0), (hx1, hy1), (255, 128, 0), 2)  # クロップ範囲(青)
    for t in ticks:
        tx, ty = t["centroid"]
        cv2.circle(out, (int(tx) + hx0, int(ty) + hy0), 3, (255, 255, 0), -1)  # 目盛り(黄)

    cv2.drawMarker(out, (int(hcx), int(hcy)), (0, 0, 255),
                    markerType=cv2.MARKER_CROSS, markerSize=30, thickness=2)  # Hough(赤)
    if ecx is not None:
        cv2.drawMarker(out, (int(ecx), int(ecy)), (0, 255, 0),
                        markerType=cv2.MARKER_CROSS, markerSize=30, thickness=2)  # estimate(緑)
    cv2.drawMarker(out, (int(fcx), int(fcy)), (255, 0, 255),
                    markerType=cv2.MARKER_CROSS, markerSize=30, thickness=2)  # fit(マゼンタ)

    if final_center is not None:
        fx, fy = final_center
        cv2.circle(out, (int(fx), int(fy)), 16, (0, 255, 255), 3)  # 最終採用結果(黄丸の輪)

    text_lines = [
        "Hough(red):     ({0:.0f}, {1:.0f})".format(hcx, hcy),
        "estimate(green): ({0:.0f}, {1:.0f})".format(ecx, ecy) if ecx is not None else "estimate(green): failed",
        "fit(magenta):   ({0:.0f}, {1:.0f})".format(fcx, fcy),
        "ticks: {0}".format(len(ticks)),
        "ADOPTED: ({0:.0f}, {1:.0f}) [{2}]".format(final_center[0], final_center[1], source)
        if final_center is not None else "ADOPTED: REJECTED (no consensus)",
    ]
    for i, line in enumerate(text_lines):
        cv2.putText(out, line, (20, 40 + i * 40), cv2.FONT_HERSHEY_SIMPLEX,
                    0.9, (0, 0, 0), 5, cv2.LINE_AA)
        cv2.putText(out, line, (20, 40 + i * 40), cv2.FONT_HERSHEY_SIMPLEX,
                    0.9, (255, 255, 255), 2, cv2.LINE_AA)

    out_path = img_path.rsplit(".", 1)[0] + "_three_candidates_result.jpg"
    success, buf = cv2.imencode(".jpg", out)
    if success:
        buf.tofile(out_path)
        print("検出結果画像を出力しました: {0}".format(out_path))


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("使い方: python run_three_candidates.py 画像パス")
        sys.exit(1)
    main(sys.argv[1])
