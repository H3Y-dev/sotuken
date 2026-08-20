"""
針の検出と、角度から測定値への変換を行うモジュール。

もともとこの処理は main_sotuken.py のGUIクラス（MeterAngleDetector._detect_and_show）の
中に、描画処理と混ざった状態で書かれていた。そのままではGUIを起動しないと
読み取りを実行できず、精度を自動評価することができなかったため、
「画像から値を出す」部分だけをGUIから切り離してここに置いている。

GUIも評価スクリプト（evaluate.py）も同じこの関数を使うので、
評価結果と実際のGUIの挙動が食い違うことはない。
"""
import math

import cv2
import numpy as np


def arc_ratio(theta_needle, theta_zero, theta_full):
    """
    ゼロ点・フルスケール点・針の角度（いずれもatan2のラジアン）から、
    針がスケール上のどの位置にあるかを0.0〜1.0の比率で返す。

    メーターが時計回りか反時計回りかは事前には分からないため、両方向で
    比率を計算し、0〜1に収まる方を採用する。両方に収まってしまう場合
    （ゼロとフルが同じ直線上に並ぶ場合など）は、弧が長い側＝実際に目盛りが
    振られている側とみなす。どちらにも収まらない場合は、針がスケールの外を
    指しているので0〜1にクランプする。
    """
    two_pi = 2 * math.pi

    def _ratio(cw):
        if cw:
            span = (theta_full - theta_zero) % two_pi
            offset = (theta_needle - theta_zero) % two_pi
        else:
            span = (theta_zero - theta_full) % two_pi
            offset = (theta_zero - theta_needle) % two_pi
        return (offset / span) if span > 1e-6 else None

    r_cw = _ratio(cw=True)
    r_ccw = _ratio(cw=False)
    ok_cw = r_cw is not None and 0.0 <= r_cw <= 1.0
    ok_ccw = r_ccw is not None and 0.0 <= r_ccw <= 1.0

    if ok_cw and not ok_ccw:
        return r_cw
    if ok_ccw and not ok_cw:
        return r_ccw
    if ok_cw and ok_ccw:
        span_cw = (theta_full - theta_zero) % two_pi
        span_ccw = (theta_zero - theta_full) % two_pi
        return r_cw if span_cw >= span_ccw else r_ccw
    return max(0.0, min(1.0, r_cw if r_cw is not None else 0.0))


def ratio_to_value(ratio, val_min, val_max):
    """
    スケール上の位置比率を実際の測定値に変換する。

    注意: これは目盛りが角度に対して等間隔（線形スケール）であることを
    前提にしている。可動鉄片形の電流計のように低い側が圧縮された
    非線形スケールの計器では、中間域に系統誤差が乗る。
    """
    return val_min + ratio * (val_max - val_min)


def detect_needle(img, center):
    """
    中心を通る直線のうち最も長いものを針とみなして検出する。

    戻り値: {'line': (x1,y1,x2,y2), 'direction': (dx,dy), 'tip': (x,y)}
            検出できなければ None
    """
    cx, cy = center
    h, w = img.shape[:2]

    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)
    edges = cv2.Canny(blurred, 50, 150)

    lines = cv2.HoughLinesP(
        edges,
        rho=1,
        theta=np.pi / 180,
        threshold=40,
        minLineLength=30,
        maxLineGap=15
    )

    needle_line = None
    best_score = -1
    center_pass_thresh = min(h, w) * 0.03

    if lines is not None:
        for line in lines:
            x1, y1, x2, y2 = line[0]
            dx, dy = x2 - x1, y2 - y1
            line_len = math.hypot(dx, dy)
            if line_len == 0:
                continue
            dist_to_center = abs(dy * cx - dx * cy + x2 * y1 - y2 * x1) / line_len
            if dist_to_center > center_pass_thresh:
                continue
            if line_len > best_score:
                best_score = line_len
                needle_line = line[0]

    if needle_line is None:
        return None

    x1, y1, x2, y2 = needle_line
    d1 = math.hypot(x1 - cx, y1 - cy)
    d2 = math.hypot(x2 - cx, y2 - cy)

    # 中心から遠い側を針の向きとする（中心を挟んで反対を向かないように）
    ndx, ndy = float(x2 - x1), float(y2 - y1)
    far_x, far_y = (x1, y1) if d1 > d2 else (x2, y2)
    if (far_x - cx) * ndx + (far_y - cy) * ndy < 0:
        ndx, ndy = -ndx, -ndy
    n_len = math.hypot(ndx, ndy)
    ndx, ndy = ndx / n_len, ndy / n_len

    # 針の向きに沿ってエッジを辿り、実際の先端位置を求める
    # （Hough線分は針の一部しか捉えていないことがあるため）
    gap_thresh = max(8, int(min(h, w) * 0.025))
    max_scan = int(min(h, w) * 0.60)
    tip_x, tip_y = far_x, far_y
    consecutive_empty = 0
    for r in range(3, max_scan):
        px = int(cx + ndx * r + 0.5)
        py = int(cy + ndy * r + 0.5)
        if not (0 <= px < w and 0 <= py < h):
            break
        if edges[py, px] > 0:
            tip_x, tip_y = px, py
            consecutive_empty = 0
        else:
            consecutive_empty += 1
            if consecutive_empty > gap_thresh:
                break

    return {
        'line': (int(x1), int(y1), int(x2), int(y2)),
        'direction': (ndx, ndy),
        'tip': (int(tip_x), int(tip_y)),
    }


def compute_reading(img, center, zero_pt, fullscale_pt, val_min, val_max):
    """
    画像・中心点・ゼロ点・フルスケール点・目盛りの最小/最大値から測定値を求める。

    戻り値: {'value', 'ratio', 'angle_deg', 'needle_line', 'needle_tip'}
            針を検出できなければ None
    """
    cx, cy = center
    zx, zy = zero_pt
    fsx, fsy = fullscale_pt

    needle = detect_needle(img, center)
    if needle is None:
        return None

    ndx, ndy = needle['direction']

    # ゼロ点方向と針の間の角度（表示用）
    zero_vec = np.array([zx - cx, zy - cy], dtype=float)
    cos_a = np.dot([ndx, ndy], zero_vec) / (np.linalg.norm(zero_vec) + 1e-9)
    abs_angle = math.degrees(math.acos(np.clip(cos_a, -1.0, 1.0)))

    ratio = arc_ratio(
        math.atan2(ndy, ndx),
        math.atan2(zy - cy, zx - cx),
        math.atan2(fsy - cy, fsx - cx),
    )
    value = ratio_to_value(ratio, val_min, val_max)

    return {
        'value': value,
        'ratio': ratio,
        'angle_deg': abs_angle,
        'needle_line': needle['line'],
        'needle_tip': needle['tip'],
    }
