import cv2
import numpy as np
import sys

from detect_meter_center_v2 import detect_meter_center_from_raw, preprocess
from circle_fit import fit_circle_to_ticks


def detect_tick_centroids_simple(img, center, radius):
    """
    簡易的な目盛り検出(本番のtick_detect.pyの代わりに、
    円フィッティング関数を実写真で試すためだけの簡易版)。

    Hough円検出で分かった中心・半径から、目盛りがありそうな
    リング状の範囲だけを切り出してエッジ検出し、
    小さい輪郭(目盛り線)の重心を集める。
    """
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    edges = cv2.Canny(gray, 50, 150)

    # 目盛りがありそうなリング範囲だけをマスク
    # (外周ベゼルのすぐ内側、盤面の目盛り帯を狙う)
    mask = np.zeros_like(gray)
    cx, cy = center
    cv2.circle(mask, (cx, cy), int(radius * 0.98), 255, -1)
    cv2.circle(mask, (cx, cy), int(radius * 0.80), 0, -1)
    edges_masked = cv2.bitwise_and(edges, edges, mask=mask)

    contours, _ = cv2.findContours(edges_masked, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)

    centroids = []
    for c in contours:
        area = cv2.contourArea(c)
        # 目盛り線らしい小さめの輪郭だけを採用(数値の文字や大きな模様を除外)
        if 3 <= area <= 200:
            M = cv2.moments(c)
            if M["m00"] == 0:
                continue
            tx = M["m10"] / M["m00"]
            ty = M["m01"] / M["m00"]
            centroids.append({"centroid": (tx, ty)})

    return centroids


def main(img_path):
    img = cv2.imdecode(np.fromfile(img_path, dtype=np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        print(f"画像を読み込めませんでした: {img_path}")
        sys.exit(1)

    # 1. Hough円検出で中心座標を求める(比較の基準)
    hough_result = detect_meter_center_from_raw(img)
    if hough_result is None:
        print("Hough円検出に失敗しました。")
        sys.exit(1)

    hcx, hcy = hough_result["center"]
    hr = hough_result["radius"]
    print(f"[Hough円検出]   中心=({hcx}, {hcy}), 半径={hr}px")

    # 2. 簡易目盛り検出 → 円フィッティング
    ticks = detect_tick_centroids_simple(img, (hcx, hcy), hr)
    print(f"検出した目盛り候補の点数: {len(ticks)}")

    if len(ticks) < 3:
        print("目盛り候補が少なすぎて円フィッティングできません。")
        sys.exit(1)

    fit_result = fit_circle_to_ticks(ticks, method="taubin")
    fcx, fcy = fit_result["center"]
    fr = fit_result["radius"]
    print(f"[円フィッティング] 中心=({fcx:.1f}, {fcy:.1f}), 半径={fr:.1f}px")

    # 3. 2つの結果を比較(一致度の目安)
    diff = np.hypot(fcx - hcx, fcy - hcy)
    print(f"2つの中心座標の差: {diff:.1f}px")

    # 4. 可視化
    out = img.copy()
    cv2.circle(out, (int(hcx), int(hcy)), 10, (0, 0, 255), -1)   # Hough: 赤
    cv2.circle(out, (int(fcx), int(fcy)), 10, (255, 0, 255), -1)  # フィッティング: マゼンタ
    cv2.circle(out, (int(hcx), int(hcy)), int(hr), (0, 255, 0), 2)
    for t in ticks:
        tx, ty = t["centroid"]
        cv2.circle(out, (int(tx), int(ty)), 3, (255, 255, 0), -1)

    text_lines = [
        f"Hough: ({hcx}, {hcy})  r={hr}",
        f"Fit:   ({fcx:.0f}, {fcy:.0f})  r={fr:.0f}",
        f"diff:  {diff:.1f}px",
    ]
    for i, line in enumerate(text_lines):
        cv2.putText(out, line, (20, 40 + i * 40), cv2.FONT_HERSHEY_SIMPLEX,
                    1.0, (0, 0, 0), 5, cv2.LINE_AA)
        cv2.putText(out, line, (20, 40 + i * 40), cv2.FONT_HERSHEY_SIMPLEX,
                    1.0, (255, 255, 255), 2, cv2.LINE_AA)

    out_path = "気密試験_昇圧前圧力計_result.jpg"
    ext = "." + out_path.split(".")[-1]
    success, buf = cv2.imencode(ext, out)
    if success:
        buf.tofile(out_path)
        print(f"検出結果画像を出力しました: {out_path}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "気密試験_昇圧前圧力計.jpg")
