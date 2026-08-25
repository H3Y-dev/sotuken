"""
目盛り線（tick mark）のPCAベース検出ロジック。
GUI（main_sotuken.py）と、ラベリング/学習用のCLIスクリプトの両方から
共通で使えるように、tkinterに依存しない純粋な関数として切り出している。
"""

import math

import cv2
import numpy as np

# 主目盛りがこの本数に満たない場合、長さの上位を主目盛りとみなすフォールバックを使う。
# 数字が振られる主目盛りは、どんな盤面でも最低数本はあるという前提。
_MIN_MAJOR_TICKS = 3
# フォールバック時に主目盛りとみなす割合。主目盛りの間には副目盛りが
# 4〜9本入るのが一般的なので、全体の2割程度を上限の目安にしている。
_MAJOR_TICK_FALLBACK_RATIO = 0.2


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


def _dial_radius(img, center):
    """Hough円検出が中心と整合するときだけ、盤面半径を返す。"""
    try:
        from detect_meter_center_v2 import detect_meter_center

        short = min(img.shape[:2])
        scale = min(1.0, 800.0 / short)
        if scale < 1.0:
            resized = cv2.resize(img, None, fx=scale, fy=scale,
                                 interpolation=cv2.INTER_AREA)
            result = detect_meter_center(resized)
            expected_center = (center[0] * scale, center[1] * scale)
        else:
            result = detect_meter_center(img)
            expected_center = center
        if result is None:
            return None
        detected_center = result['center']
        radius = float(result['radius'])
        if radius <= 0:
            return None
        if math.hypot(detected_center[0] - expected_center[0],
                      detected_center[1] - expected_center[1]) > radius * 0.2:
            return None
        return radius / scale
    except Exception:
        # 中心検出は補助情報なので、失敗時は従来の短辺基準に縮退する。
        return None


def _periodic_peaks(profile, min_separation):
    """1周分の1次元プロファイルから、等間隔性を満たすピークを抽出する。"""
    values = profile.astype(np.float32)
    detail = values - cv2.GaussianBlur(values.reshape(1, -1), (0, 0), 8).ravel()
    median = float(np.median(detail))
    deviation = float(np.median(np.abs(detail - median)))
    threshold = max(median + 12.0, median + 3.0 * deviation)

    local_maxima = np.where(
        (detail >= np.roll(detail, 1)) &
        (detail > np.roll(detail, -1)) &
        (detail >= threshold)
    )[0]
    if len(local_maxima) < 8:
        return None
    # 文字・反射が多い写真では局所最大が数千個になることがある。目盛り本数を
    # 十分に上回る強い候補だけで周期性を評価し、探索時間を一定に保つ。
    if len(local_maxima) > 180:
        strongest = np.argpartition(detail[local_maxima], -180)[-180:]
        local_maxima = local_maxima[strongest]

    # 目盛り1本の太さによる重複ピークを、強い方だけにする。
    selected = []
    for index in sorted(local_maxima, key=lambda i: detail[i], reverse=True):
        if all(min((index - other) % len(detail), (other - index) % len(detail))
               >= min_separation for other in selected):
            selected.append(int(index))
    selected.sort()
    if len(selected) < 8:
        return None

    gaps = np.diff(selected + [selected[0] + len(detail)]).astype(np.float32)
    median_gap = float(np.median(gaps))
    if median_gap <= 0:
        return None
    regular = (gaps >= median_gap * 0.55) & (gaps <= median_gap * 1.55)
    regular_ratio = float(np.mean(regular))
    if regular_ratio < 0.45:
        return None

    tick_count = int(round(len(detail) / median_gap))
    if tick_count < 8:
        return None
    spacing = float(len(detail)) / tick_count
    tolerance = spacing * 0.24

    # 周期格子に最もよく合う位相を選ぶ。文字や背景の単発ピークが混ざっても、
    # その1本に格子全体を引っ張らせないための処理である。
    best_grid = None
    for seed in selected:
        phase = seed % spacing
        # 各ピークを最寄りの格子セルへ一度だけ割り当てる。
        # 以前の「全セル×全ピーク」探索は、写真の文字でピークが増えると
        # 計算量が急増していた。
        matched_by_cell = {}
        for index in selected:
            cell = int(round((index - phase) / spacing)) % tick_count
            expected = (phase + cell * spacing) % len(detail)
            distance = abs(((index - expected + len(detail) / 2.0) % len(detail))
                           - len(detail) / 2.0)
            if distance <= tolerance:
                previous = matched_by_cell.get(cell)
                if previous is None or distance < previous[0]:
                    matched_by_cell[cell] = (distance, index)
        matched = [item[1] for item in matched_by_cell.values()]
        score = len(matched)
        if best_grid is None or score > best_grid[0]:
            best_grid = (score, matched)

    # 一部が文字や針で隠れる盤面では、全目盛りが暗線として現れない。
    # それでも周期格子へ3分の1以上が一致すれば、同一半径の目盛り帯と判断する。
    if best_grid is None or best_grid[0] < max(8, tick_count * 0.35):
        return None
    return sorted(set(best_grid[1])), best_grid[0] * regular_ratio


def _tick_band_from_arcs(polar, min_radius, max_radius, short):
    """角度方向へ広く続く2本の円弧から、その間の目盛り帯を求める。"""
    occupancy = np.mean(polar > 127, axis=1).astype(np.float32)
    smoothed = cv2.GaussianBlur(
        occupancy.reshape(-1, 1), (0, 0), 2).ravel()
    baseline = cv2.GaussianBlur(
        occupancy.reshape(-1, 1), (0, 0), 12).ravel()
    prominence = smoothed - baseline

    angle_count = polar.shape[1]
    sector_count = min(72, angle_count)
    sector_width = angle_count // sector_count
    usable_angles = sector_width * sector_count
    if sector_width == 0 or usable_angles == 0:
        return None

    boundaries = []
    start_radius = max(1, min_radius)
    end_radius = min(len(smoothed) - 1, max_radius)
    for radius in range(start_radius, end_radius):
        if not (smoothed[radius] >= smoothed[radius - 1] and
                smoothed[radius] > smoothed[radius + 1]):
            continue
        if prominence[radius] < 0.03:
            continue

        row_start = max(0, radius - 4)
        row_end = min(polar.shape[0], radius + 5)
        patch = (polar[row_start:row_end, :usable_angles] > 127).reshape(
            row_end - row_start, sector_count, sector_width)
        sector_density = np.mean(patch, axis=(0, 2))
        coverage = float(np.mean(sector_density >= 0.10))
        if coverage >= 0.60:
            boundaries.append(
                (radius, coverage, float(prominence[radius])))

    min_gap = short * 0.02
    max_gap = short * 0.12
    pairs = []
    for inner_index, inner in enumerate(boundaries):
        for outer in boundaries[inner_index + 1:]:
            gap = outer[0] - inner[0]
            if min_gap <= gap <= max_gap:
                pairs.append((
                    min(inner[1], outer[1]),
                    min(inner[2], outer[2]),
                    inner[0],
                    outer[0],
                ))
    if not pairs:
        return None

    best_pair = max(pairs, key=lambda pair: (pair[0], pair[1]))
    return best_pair[2], best_pair[3]


def _radial_length(polar, radius, angle_index, angle_half_width):
    """極座標画像で、指定角度の暗線が半径方向に続く長さを測る。"""
    count = polar.shape[1]
    columns = [(angle_index + offset) % count
               for offset in range(-angle_half_width, angle_half_width + 1)]
    signal = np.max(polar[:, columns], axis=1) > 127
    # アンチエイリアスや圧縮ノイズで1pxだけ切れた目盛りをつなぐ。
    signal = cv2.morphologyEx(signal.astype(np.uint8).reshape(-1, 1),
                              cv2.MORPH_CLOSE,
                              np.ones((3, 1), dtype=np.uint8)).ravel().astype(bool)
    search_start = max(0, radius - 4)
    search_end = min(len(signal), radius + 5)
    nearby = np.where(signal[search_start:search_end])[0]
    if len(nearby) == 0:
        return 0, float(radius)
    radius = search_start + int(nearby[np.argmin(
        np.abs(search_start + nearby - radius))])

    start = radius
    while start > 0 and signal[start - 1]:
        start -= 1
    end = radius
    while end + 1 < len(signal) and signal[end + 1]:
        end += 1
    return end - start + 1, (start + end) / 2.0


def detect_scale_ticks(img, center):
    """
    中心を基準に極座標変換し、同一半径上で周期的に現れる暗線を目盛りとして返す。
    輪郭の連結状態を使わないため、目盛りと円弧が融合していても検出できる。
    戻り値: [{'angle', 'centroid', 'line_angle', 'length', 'is_major'}, ...]
    """
    try:
        cx, cy = float(center[0]), float(center[1])
        h, w = img.shape[:2]
        short = min(h, w)
        edge_radius = min(cx, cy, w - 1 - cx, h - 1 - cy)
        if edge_radius < 8:
            return []

        dial_radius = _dial_radius(img, (cx, cy))
        if dial_radius is not None:
            min_radius = int(round(dial_radius * 0.55))
            max_radius = int(round(dial_radius * 0.98))
        else:
            # 盤面半径を得られない画像では、従来の短辺基準を保つ。
            min_radius = int(round(short * 0.12))
            max_radius = int(round(short * 0.55))
        max_radius = min(max_radius, int(edge_radius))
        if max_radius - min_radius < 8:
            return []

        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        binary = cv2.adaptiveThreshold(
            gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY_INV, 25, 5
        )
        angle_samples = max(360, int(round(2.0 * math.pi * max_radius)))
        # warpPolarの出力は (角度, 半径)。転置して (半径, 角度) として扱う。
        polar = cv2.warpPolar(
            binary, (max_radius + 1, angle_samples), (cx, cy), max_radius,
            cv2.WARP_POLAR_LINEAR | cv2.WARP_FILL_OUTLIERS,
        ).T

        band_half_width = max(2, int(round(short * 0.012)))
        step = max(1, band_half_width // 2)
        arc_band = _tick_band_from_arcs(
            polar, min_radius, max_radius, short)
        if arc_band is not None:
            arc_min = arc_band[0] + band_half_width
            arc_max = arc_band[1] - band_half_width
            if arc_min > arc_max:
                arc_band = None

        best = None
        fallback_best = None
        for radius in range(min_radius + band_half_width,
                            max_radius - band_half_width + 1, step):
            profile = np.mean(
                polar[radius - band_half_width:radius + band_half_width + 1], axis=0)
            peaks = _periodic_peaks(
                profile, max(3, int(round(angle_samples * math.radians(0.25))))
            )
            if peaks is None:
                continue
            indices, score = peaks
            candidate = (score, radius, indices)
            if fallback_best is None or score > fallback_best[0]:
                fallback_best = candidate
            if (arc_band is not None and arc_min <= radius <= arc_max and
                    (best is None or score > best[0])):
                best = candidate

        if (arc_band is not None and fallback_best is not None and
                arc_band[0] <= fallback_best[1] <= arc_band[1]):
            best = fallback_best
        if best is None:
            best = fallback_best
        if best is None:
            return []

        _, peak_radius, indices = best
        angle_half_width = max(1, int(round(angle_samples * math.radians(0.35))))
        raw = []
        for index in indices:
            length, centroid_radius = _radial_length(
                polar, peak_radius, index, angle_half_width)
            if length < max(3, short * 0.006):
                continue
            angle = 2.0 * math.pi * index / angle_samples
            raw.append({
                'angle': angle,
                'centroid': (
                    cx + centroid_radius * math.cos(angle),
                    cy + centroid_radius * math.sin(angle),
                ),
                'line_angle': angle,
                'length': float(length),
            })

        if not raw:
            return []
        lengths = sorted(tick['length'] for tick in raw)
        median_length = lengths[len(lengths) // 2]
        for tick in raw:
            tick['is_major'] = tick['length'] > median_length * 1.3

        # 固定倍率だけだと、主目盛りと副目盛りの長さの差が小さい盤面で
        # 主目盛りが1本も立たないことがある。実測では 20260817_134728.jpg の
        # 最長目盛りが中央値の1.29倍しかなく、閾値1.3をわずかに下回って
        # 主目盛り0本になっていた（同種の 134730 は1.38倍で8本立つ）。
        #
        # 主目盛りが無いと、OCR数字の対応付け（bind_numbers_to_ticks の
        # major_bonus）も、目盛りの実在確認による最小値の補完
        # （scale_value_detect の下方向への延長）も機能しなくなる。
        # そこで、規定数に満たない場合は長い順の上位を主目盛りとみなす。
        if sum(1 for t in raw if t['is_major']) < _MIN_MAJOR_TICKS:
            n_major = max(_MIN_MAJOR_TICKS,
                          int(len(raw) * _MAJOR_TICK_FALLBACK_RATIO))
            threshold = sorted(lengths, reverse=True)[min(n_major, len(lengths)) - 1]
            for tick in raw:
                tick['is_major'] = tick['length'] >= threshold
        return raw
    except Exception:
        return []


def refine_center_iterative(img, seed_center, iterations=2, max_shift_ratio=0.35):
    """
    目盛り線の交点による中心推定を、目盛り再検出を挟んで数回繰り返して収束させる。
    目盛り検出は探索半径(min_dist/max_dist)が中心点に依存するため、
    起点(seed_center)が大きくずれている（Hough円検出が別の丸い模様を
    誤検出した場合など）と1回の推定では十分に補正しきれないことがある。
    1回目は大きなズレも許容し、2回目以降は起点付近に絞って収束させる。
    戻り値: (center, ticks) のタプル。目盛りが3本未満で推定できない場合は (None, [])。
    """
    center = seed_center
    ticks = []
    shift_ratio = max_shift_ratio
    for i in range(max(1, iterations)):
        ticks = detect_scale_ticks(img, center)
        if len(ticks) < 3:
            return (None, [])
        refined = refine_center_from_ticks(ticks, center, img.shape, max_shift_ratio=shift_ratio)
        if refined is None:
            return (center, ticks) if i > 0 else (None, ticks)
        center = refined
        shift_ratio = max_shift_ratio * 0.4  # 2周目以降は収束優先で変動を絞る
    return (center, ticks)


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
