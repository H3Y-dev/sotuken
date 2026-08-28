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

from needle_detect import select_indicator_candidate


def arc_ratio(theta_needle, theta_zero, theta_full, tick_angles=None):
    """
    ゼロ点・フルスケール点・針の角度（いずれもatan2のラジアン）から、
    針がスケール上のどの位置にあるかを0.0〜1.0の比率で返す。

    メーターが時計回りか反時計回りかは事前には分からないため、両方向で
    比率を計算し、0〜1に収まる方を採用する。両方に収まってしまう場合
    （ゼロとフルが同じ直線上に並ぶ場合など）は、弧が長い側＝実際に目盛りが
    振られている側とみなす。どちらにも収まらない場合は、針がスケールの外を
    指しているので0〜1にクランプする。

    `tick_angles` に検出済みの目盛り角度（ラジアンのリスト）を渡すと、
    **目盛りが実際に並んでいる側の弧**を走査方向として確定できる。

    これを渡さない場合、針がスケールの外側（ゼロ点より手前など）を指すと、
    「0〜1に収まる方を採用する」というルールが裏目に出て、**逆回りの弧に
    収まってしまい、大きく誤った値を返す**（2026-08-25に実測で確認）。

        ゼロ点135度・フル点45度（有効スパン270度）のメーターで、
        針がゼロ点の5度手前 -> 22.2（0-400スケール、正しくは0）
        針がゼロ点の67.5度手前 -> 300.0（ほぼフルスケール、正しくは0）

    実機写真（耐圧試験_昇圧前圧力計）で、ゼロ点を「100」の目盛りと
    誤検出したために針が範囲外になり、真値0.12に対し約184と読む
    原因になっていた。目盛り角度を渡せばこの取り違えは起きない。
    """
    two_pi = 2 * math.pi

    def _span(cw):
        if cw:
            return (theta_full - theta_zero) % two_pi
        return (theta_zero - theta_full) % two_pi

    def _ratio(cw):
        span = _span(cw)
        if cw:
            offset = (theta_needle - theta_zero) % two_pi
        else:
            offset = (theta_zero - theta_needle) % two_pi
        return (offset / span) if span > 1e-6 else None

    r_cw = _ratio(cw=True)
    r_ccw = _ratio(cw=False)

    def _clamped(cw, ratio):
        """
        弧の外を指す針を、近い方の端にクランプする。

        単純に0〜1へ丸めるだけでは足りない。針がゼロ点の手前にある場合、
        offsetは2πに近い値になり、比率は1を大きく超える。これをそのまま
        1へ丸めると**満尺側**に振り切れてしまう（正しくはゼロ側）。
        死角（スパンから2πまで）の真ん中を境に、どちらの端に近いかで
        丸め先を決める。
        """
        if ratio is None:
            return None
        if 0.0 <= ratio <= 1.0:
            return ratio
        span = _span(cw)
        if span <= 1e-6:
            return max(0.0, min(1.0, ratio))
        offset = ratio * span
        dead_zone_middle = (span + two_pi) / 2.0
        # 死角の後半（2π寄り）＝ゼロ点の手前 → 0側へ丸める
        return 0.0 if offset > dead_zone_middle else 1.0

    # 目盛りの位置が分かっているなら、走査方向を推測せず確定できる
    if tick_angles:
        span_cw = _span(cw=True)
        n_cw = 0
        for a in tick_angles:
            # ゼロ点から時計回り側の弧に入っている目盛りを数える
            if (a - theta_zero) % two_pi <= span_cw:
                n_cw += 1
        n_ccw = len(tick_angles) - n_cw
        if n_cw != n_ccw:
            cw = n_cw > n_ccw
            chosen = _clamped(cw, r_cw if cw else r_ccw)
            if chosen is not None:
                # 針が弧の外を指していても、近い端へクランプするだけ。
                # 逆回りの解釈に乗り換えない（それが上記の誤読の原因）
                return chosen

    ok_cw = r_cw is not None and 0.0 <= r_cw <= 1.0
    ok_ccw = r_ccw is not None and 0.0 <= r_ccw <= 1.0

    if ok_cw and not ok_ccw:
        return r_cw
    if ok_ccw and not ok_cw:
        return r_ccw
    if ok_cw and ok_ccw:
        return r_cw if _span(cw=True) >= _span(cw=False) else r_ccw
    return max(0.0, min(1.0, r_cw if r_cw is not None else 0.0))


def ratio_to_value(ratio, val_min, val_max, calibration=None):
    """
    スケール上の位置比率を実際の測定値に変換する。

    `calibration` を渡さない場合は、両端（val_min/val_max）だけを使った
    従来通りの2点線形補間になる。これは目盛りが角度に対して等間隔
    （線形スケール）であることを前提にしており、可動鉄片形の電流計の
    ように低い側が圧縮された非線形スケールの計器では中間域に系統誤差が乗る。

    `calibration` に `[(ratio, value), ...]`（OCRで数値が対応付いた
    中間の目盛り点、ratioは針と同じ0〜1の位置比率空間）を渡すと、
    両端だけでなくこれらの点も使った区分線形補間になり、非線形スケールにも
    追従できる。

    値が単調に増加しない較正点（OCR誤読等）が混ざっていても落ちない
    ように、`val_min`〜`val_max` の間にあり、かつ内部で単調増加する
    最長の部分列だけを使う。`val_min`/`val_max` 自体は常に両端点として
    使われる（较正点の外れ値フィルタで欠落することはない）。
    """
    if not calibration:
        return val_min + ratio * (val_max - val_min)

    interior = [
        (r, v) for r, v in calibration
        if 0.0 < r < 1.0 and val_min < v < val_max
    ]
    interior = _longest_monotonic_by_ratio(interior)
    interior = _filter_arithmetic_progression(interior)

    points = [(0.0, val_min)] + interior + [(1.0, val_max)]
    ratios = [p[0] for p in points]
    values = [p[1] for p in points]
    return float(np.interp(ratio, ratios, values))


def _longest_monotonic_by_ratio(points):
    """
    `[(ratio, value), ...]` をratio昇順に並べた上で、valueが単調増加する
    最長の部分列を返す（O(n^2)。较正点はせいぜい数十件程度なので十分速い）。
    """
    ordered = sorted(points, key=lambda p: p[0])
    n = len(ordered)
    if n == 0:
        return []

    lengths = [1] * n
    prev = [-1] * n
    for i in range(n):
        for j in range(i):
            if ordered[j][1] < ordered[i][1] and lengths[j] + 1 > lengths[i]:
                lengths[i] = lengths[j] + 1
                prev[i] = j

    end = max(range(n), key=lambda i: lengths[i])
    seq = []
    while end != -1:
        seq.append(ordered[end])
        end = prev[end]
    seq.reverse()
    return seq


def _filter_arithmetic_progression(points, rel_tol=0.15):
    """
    ratio昇順・value単調増加に並んだ較正点から、値が等差数列から外れる点を
    さらに除く（`_longest_monotonic_by_ratio` だけでは、単調ではあるが
    値そのものが誤っている較正点を検出できない）。

    実際のメーターに印字された目盛り数値は、非線形スケール（可動鉄片形等）
    でも角度の間隔が不均一なだけで、**印字されている値自体は0/10/20/...の
    ような等差数列**になっているのが普通（読み飛ばしで一部が欠けることは
    あっても、値の刻み自体が不規則になることはまず無い）。OCRが「30」を
    「38」のように誤読すると、単調増加という条件だけは満たしてしまう
    （20 < 38 < 40）ため、値の刻みが単位刻みの整数倍から外れているかで
    検出する。

    2点以下（等差数列の単位刻みを推定できない）ならそのまま返す。
    """
    if len(points) < 3:
        return points

    values = [v for _, v in points]
    deltas = sorted(
        values[i + 1] - values[i] for i in range(len(values) - 1)
        if values[i + 1] > values[i]
    )
    if not deltas:
        return points
    unit = deltas[len(deltas) // 2]  # 中央値（読み飛ばしに引きずられにくい）
    if unit <= 0:
        return points

    def _fits(delta):
        if delta <= 0:
            return False
        steps = delta / unit
        return abs(steps - round(steps)) <= rel_tol and round(steps) >= 1

    def _greedy_increasing(seq):
        kept = [seq[0]]
        for p in seq[1:]:
            if _fits(p[1] - kept[-1][1]):
                kept.append(p)
        return kept

    def _greedy_decreasing(seq):
        kept = [seq[0]]
        for p in seq[1:]:
            if _fits(kept[-1][1] - p[1]):
                kept.append(p)
        return kept

    # 先頭から順に見て単位刻みに合う点だけを残す（先頭自体が外れ値だと
    # そこから先すべて基準がずれるため、末尾から見た場合とで長い方を採用する）
    forward = _greedy_increasing(points)
    backward = list(reversed(_greedy_decreasing(list(reversed(points)))))
    return forward if len(forward) >= len(backward) else backward


def _resolve_cw(theta_zero, theta_full, tick_angles):
    """
    ゼロ点→フルスケール点への走査方向（時計回りかどうか）を、目盛り角度の
    分布から確定する。`arc_ratio` の目盛り角度による方向確定ロジック
    （docstring参照）と同じ考え方だが、較正点の角度をratio空間へ変換する
    ためだけに使う独立した実装（`arc_ratio` 本体には手を入れない）。

    確定できなければ None を返す（呼び出し側は較正点を使わず、
    両端の線形補間にフォールバックする）。
    """
    if not tick_angles:
        return None
    two_pi = 2 * math.pi
    span_cw = (theta_full - theta_zero) % two_pi
    n_cw = sum(1 for a in tick_angles if (a - theta_zero) % two_pi <= span_cw)
    n_ccw = len(tick_angles) - n_cw
    if n_cw == n_ccw:
        return None
    return n_cw > n_ccw


def _angle_to_ratio(theta, theta_zero, theta_full, cw):
    """`cw` で指定した走査方向での、theta_zero から theta までの弧の位置比率。"""
    two_pi = 2 * math.pi
    span = (theta_full - theta_zero) % two_pi if cw else (theta_zero - theta_full) % two_pi
    if span <= 1e-6:
        return None
    offset = (theta - theta_zero) % two_pi if cw else (theta_zero - theta) % two_pi
    return offset / span


def calibration_to_ratios(calibration_angles, theta_zero, theta_full, tick_angles=None):
    """
    `[(angle, value), ...]`（OCRで数値が対応付いた目盛りの角度と値）を、
    `ratio_to_value` が受け取れる `[(ratio, value), ...]` へ変換する。

    走査方向（時計回りかどうか）が目盛り角度の分布から確定できない場合は
    空リストを返す（呼び出し側は両端の線形補間にフォールバックする）。
    """
    if not calibration_angles:
        return []
    cw = _resolve_cw(theta_zero, theta_full, tick_angles)
    if cw is None:
        return []
    result = []
    for angle, value in calibration_angles:
        r = _angle_to_ratio(angle, theta_zero, theta_full, cw)
        if r is not None:
            result.append((r, value))
    return result


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

    candidates = []
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
            candidates.append((int(x1), int(y1), int(x2), int(y2)))

    needle_line = select_indicator_candidate(img, candidates)

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


def compute_reading(img, center, zero_pt, fullscale_pt, val_min, val_max,
                    tick_angles=None, calibration_angles=None):
    """
    画像・中心点・ゼロ点・フルスケール点・目盛りの最小/最大値から測定値を求める。

    `tick_angles` は検出済みの目盛り角度（ラジアンのリスト、省略可）。
    渡すとスケールの走査方向を推測せず確定できるため、針がスケール範囲の
    外を指している場合の誤読を防げる（詳細は arc_ratio のdocstring）。

    `calibration_angles` は `[(angle, value), ...]`（OCRで数値が対応付いた
    中間の目盛りの角度と値、省略可）。渡すと両端（val_min/val_max）だけの
    線形補間ではなく、これらの点も使った区分線形補間になり、可動鉄片形
    などの非線形スケールにも追従できる（詳細は ratio_to_value のdocstring）。

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

    theta_zero = math.atan2(zy - cy, zx - cx)
    theta_full = math.atan2(fsy - cy, fsx - cx)
    ratio = arc_ratio(
        math.atan2(ndy, ndx),
        theta_zero,
        theta_full,
        tick_angles=tick_angles,
    )
    calibration = calibration_to_ratios(
        calibration_angles, theta_zero, theta_full, tick_angles=tick_angles)
    value = ratio_to_value(ratio, val_min, val_max, calibration=calibration)

    return {
        'value': value,
        'ratio': ratio,
        'angle_deg': abs_angle,
        'needle_line': needle['line'],
        'needle_tip': needle['tip'],
    }
