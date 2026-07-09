"""
目盛り線（tick mark）のPCAベース検出ロジック。
GUI（main_sotuken.py）と、ラベリング/学習用のCLIスクリプトの両方から
共通で使えるように、tkinterに依存しない純粋な関数として切り出している。
"""

import math

import cv2
import numpy as np


def crop_with_margin(img, bbox, margin_ratio=0.1, min_size=20):
    """
    正規化座標(x0, y0, x1, y1)で指定された矩形に、余白(margin_ratio)を
    加えてクロップする。範囲は画像内に収まるようクランプする。
    クロップ結果が小さすぎる場合はNoneを返す。
    """
    x0, y0, x1, y1 = bbox
    bw, bh = x1 - x0, y1 - y0
    x0 -= bw * margin_ratio
    x1 += bw * margin_ratio
    y0 -= bh * margin_ratio
    y1 += bh * margin_ratio
    x0, y0 = max(0.0, x0), max(0.0, y0)
    x1, y1 = min(1.0, x1), min(1.0, y1)

    h, w = img.shape[:2]
    px0, py0 = int(x0 * w), int(y0 * h)
    px1, py1 = int(x1 * w), int(y1 * h)
    if px1 - px0 < min_size or py1 - py0 < min_size:
        return None
    return img[py0:py1, px0:px1].copy()


def apply_clahe(img, clip_limit=2.0, tile_grid_size=(8, 8)):
    """
    CLAHE（適応的ヒストグラム平坦化）でローカルコントラストを強調する。
    輝度(L)チャンネルのみに適用し、色情報(a, b)はそのまま保つ。
    反射・グレアや低コントラストな盤面で目盛り線・文字が検出されやすくなる。
    """
    lab = cv2.cvtColor(img, cv2.COLOR_BGR2LAB)
    l, a, b = cv2.split(lab)
    clahe = cv2.createCLAHE(clipLimit=clip_limit, tileGridSize=tile_grid_size)
    l2 = clahe.apply(l)
    return cv2.cvtColor(cv2.merge([l2, a, b]), cv2.COLOR_LAB2BGR)


def _hough_detect_center(gray):
    """グレースケール画像に対してHough円検出を1回試みる。"""
    blurred = cv2.GaussianBlur(gray, (9, 9), 2)

    h, w = gray.shape[:2]
    short = min(h, w)
    min_r = max(4, int(short * 0.008))
    max_r = max(25, int(short * 0.06))

    circles = cv2.HoughCircles(
        blurred, cv2.HOUGH_GRADIENT, dp=1, minDist=short * 0.04,
        param1=80, param2=28, minRadius=min_r, maxRadius=max_r
    )
    if circles is None:
        return None

    circles = np.round(circles[0, :]).astype(int)
    img_cx, img_cy = w // 2, h // 2
    best = min(circles, key=lambda c: math.hypot(c[0] - img_cx, c[1] - img_cy))
    return (int(best[0]), int(best[1]), int(best[2]))


def auto_detect_center(img):
    """
    Hough円検出で針の中心点候補を取得する。
    通常のグレースケールで見つからない場合は、CLAHE（適応的ヒストグラム平坦化）で
    コントラストを強調してから再試行する（暗い/低コントラストな盤面向けの救済策）。
    それでも見つからない場合はNone。
    """
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    result = _hough_detect_center(gray)
    if result is not None:
        return result

    clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))
    enhanced = clahe.apply(gray)
    return _hough_detect_center(enhanced)


def estimate_center_from_ticks(img, max_shift_ratio=0.4):
    """
    Hough円検出が失敗した場合のフォールバック。
    画像の幾何学的中心を仮の起点として目盛り線候補を探し、
    その交点として中心を再推定する。3本未満しか見つからない場合はNone。
    """
    h, w = img.shape[:2]
    seed = (w // 2, h // 2)
    ticks = detect_scale_ticks(img, seed)
    if len(ticks) < 3:
        return None
    return refine_center_from_ticks(ticks, seed, img.shape, max_shift_ratio=max_shift_ratio)


def detect_scale_ticks(img, center):
    """
    盤面上の目盛り線をPCAベースで検出する。
    各輪郭の点群にPCAをかけて主軸方向を求め、
    中心方向とほぼ一致する（＝放射状に伸びた）細長い輪郭だけを
    目盛り線として採用する。
    戻り値: [{'angle', 'centroid', 'line_angle', 'length', 'is_major'}, ...]
    """
    try:
        cx, cy = center
        h, w = img.shape[:2]
        short = min(h, w)

        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        thresh = cv2.adaptiveThreshold(
            gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY_INV, 25, 5
        )

        contours, _ = cv2.findContours(thresh, cv2.RETR_LIST, cv2.CHAIN_APPROX_NONE)

        min_len = short * 0.008
        max_len = short * 0.12
        min_dist = short * 0.12
        max_dist = short * 0.55

        raw = []
        for cnt in contours:
            if len(cnt) < 5:
                continue
            pts = cnt.reshape(-1, 2).astype(np.float32)

            mean, eigvecs, _ = cv2.PCACompute2(pts, mean=None)
            principal, secondary = eigvecs[0], eigvecs[1]
            m = mean[0]

            proj_p = (pts - m) @ principal
            proj_s = (pts - m) @ secondary
            length = float(proj_p.max() - proj_p.min())
            thickness = float(proj_s.max() - proj_s.min())

            if length < min_len or length > max_len:
                continue
            if thickness <= 0 or length / thickness < 2.0:
                continue  # 細長い形状でなければ目盛りではない

            mx, my = float(m[0]), float(m[1])
            dist = math.hypot(mx - cx, my - cy)
            if dist < min_dist or dist > max_dist:
                continue

            line_angle = math.atan2(principal[1], principal[0])
            theta_to_center = math.atan2(my - cy, mx - cx)

            diff = (line_angle - theta_to_center) % math.pi
            diff = min(diff, math.pi - diff)
            if diff > math.radians(18):
                continue  # 放射方向を向いていない輪郭は除外

            raw.append({
                'angle': theta_to_center,
                'centroid': (mx, my),
                'line_angle': line_angle,
                'length': length,
            })

        if not raw:
            return []

        # 角度が近い断片（同じ目盛りが分裂検出されたもの）を統合
        raw.sort(key=lambda t: t['angle'])
        merged = []
        angle_eps = math.radians(1.2)
        for t in raw:
            if merged and abs(((t['angle'] - merged[-1]['angle'] + math.pi)
                                % (2 * math.pi)) - math.pi) < angle_eps:
                if t['length'] > merged[-1]['length']:
                    merged[-1] = t
            else:
                merged.append(t)
        if len(merged) > 1:
            wrap_diff = abs(((merged[0]['angle'] - merged[-1]['angle'] + math.pi)
                              % (2 * math.pi)) - math.pi)
            if wrap_diff < angle_eps:
                if merged[0]['length'] >= merged[-1]['length']:
                    merged.pop()
                else:
                    merged.pop(0)

        lengths = sorted(t['length'] for t in merged)
        median_len = lengths[len(lengths) // 2]
        for t in merged:
            t['is_major'] = t['length'] > median_len * 1.3

        return merged

    except Exception:
        return []


def refine_center_from_ticks(ticks, fallback_center, img_shape, max_shift_ratio=0.15):
    """
    検出した目盛り線群の主軸を最小二乗法で交差させ、中心点を再推定する。
    max_shift_ratioは、fallback_centerからどれだけ離れた結果まで許容するか
    （画像の短辺に対する比率）。起点が正確なとき（Hough成功時）は小さめに、
    起点が単なる画像中心の当て推量のとき（estimate_center_from_ticks）は
    大きめに設定する。
    """
    try:
        A = np.zeros((2, 2))
        b = np.zeros(2)
        for t in ticks:
            theta = t['line_angle']
            d = np.array([math.cos(theta), math.sin(theta)])
            p = np.array(t['centroid'])
            proj = np.eye(2) - np.outer(d, d)
            A += proj
            b += proj @ p

        center = np.linalg.solve(A, b)
        cx, cy = float(center[0]), float(center[1])

        h, w = img_shape[:2]
        if not (0 <= cx < w and 0 <= cy < h):
            return None
        # 元の中心から大きく離れた場合は誤検出とみなし採用しない
        fx, fy = fallback_center
        if math.hypot(cx - fx, cy - fy) > min(w, h) * max_shift_ratio:
            return None
        return (int(round(cx)), int(round(cy)))
    except np.linalg.LinAlgError:
        return None


def snap_to_tick(click_pt, center, ticks, max_angle_deg=10.0):
    """クリック位置に最も近い角度の目盛り線があれば、その位置にスナップする。"""
    if not ticks or center is None:
        return click_pt
    cx, cy = center
    click_angle = math.atan2(click_pt[1] - cy, click_pt[0] - cx)

    best = None
    best_diff = math.radians(max_angle_deg)
    for t in ticks:
        diff = abs(((t['angle'] - click_angle + math.pi) % (2 * math.pi)) - math.pi)
        if diff < best_diff:
            best_diff = diff
            best = t

    if best is None:
        return click_pt
    return (int(round(best['centroid'][0])), int(round(best['centroid'][1])))


def extract_tick_crop(img, tick, out_size=64, crop_scale=3.0):
    """
    目盛り候補の周辺を切り出し、主軸(line_angle)が縦方向になるように回転補正した
    正方形クロップを返す。DINOv2などの分類器に入力する前処理として使う。
    戻り値: out_size x out_size x 3 のBGR画像（cv2形式）
    """
    cx, cy = tick['centroid']
    h, w = img.shape[:2]

    half = max(out_size, int(tick['length'] * crop_scale))
    x0, x1 = max(0, int(cx - half)), min(w, int(cx + half))
    y0, y1 = max(0, int(cy - half)), min(h, int(cy + half))
    sub = img[y0:y1, x0:x1]
    if sub.size == 0:
        return None

    sub_cx, sub_cy = cx - x0, cy - y0
    angle_deg = math.degrees(tick['line_angle']) - 90  # 長軸を縦方向に揃える
    M = cv2.getRotationMatrix2D((sub_cx, sub_cy), angle_deg, 1.0)
    rotated = cv2.warpAffine(sub, M, (sub.shape[1], sub.shape[0]),
                              borderMode=cv2.BORDER_REPLICATE)

    half_out = out_size / 2.0
    rx0, ry0 = int(round(sub_cx - half_out)), int(round(sub_cy - half_out))
    rx1, ry1 = rx0 + out_size, ry0 + out_size

    pad_left = max(0, -rx0)
    pad_top = max(0, -ry0)
    pad_right = max(0, rx1 - rotated.shape[1])
    pad_bottom = max(0, ry1 - rotated.shape[0])
    if pad_left or pad_top or pad_right or pad_bottom:
        rotated = cv2.copyMakeBorder(rotated, pad_top, pad_bottom, pad_left, pad_right,
                                      cv2.BORDER_REPLICATE)
        rx0 += pad_left
        ry0 += pad_top

    crop = rotated[ry0:ry0 + out_size, rx0:rx0 + out_size]
    if crop.shape[0] != out_size or crop.shape[1] != out_size:
        return None
    return crop
