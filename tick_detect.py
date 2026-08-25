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


def _angular_dark_response(gray_polar):
    """円周方向に細い暗線だけを強調し、連続した暗いリングを打ち消す。"""
    angle_count = gray_polar.shape[1]
    tiled = np.concatenate((gray_polar, gray_polar, gray_polar), axis=1)
    narrow = cv2.GaussianBlur(
        tiled, (0, 0), sigmaX=0.8, sigmaY=0.01)
    broad_sigma = max(3.0, angle_count * 1.25 / 360.0)
    broad = cv2.GaussianBlur(
        tiled, (0, 0), sigmaX=broad_sigma, sigmaY=0.01)
    response = np.maximum(broad - narrow, 0.0)
    return response[:, angle_count:angle_count * 2].astype(np.float32)


def _periodic_radius(response, min_radius, max_radius):
    """自己相関ピークが半径方向にも続く位置を、目盛り帯として選ぶ。"""
    angle_count = response.shape[1]
    detail = response - np.mean(response, axis=1, keepdims=True)
    spectrum = np.fft.rfft(detail, axis=1)
    autocorrelation = np.fft.irfft(
        np.abs(spectrum) ** 2, n=angle_count, axis=1)
    autocorrelation /= np.maximum(autocorrelation[:, :1], 1e-6)

    min_period = max(4, int(round(angle_count * 2.0 / 360.0)))
    max_period = int(round(angle_count * 18.0 / 360.0))
    periods = np.arange(min_period, max_period + 1)
    sharp_offset = max(1, int(round(angle_count * 0.75 / 360.0)))
    score_columns = []
    for period in periods:
        score = np.zeros(response.shape[0], dtype=np.float64)
        for multiple, weight in ((1, 1.0), (2, 0.65),
                                 (3, 0.40), (4, 0.25)):
            lag = period * multiple
            if lag + sharp_offset >= angle_count // 2:
                continue
            peak = autocorrelation[:, lag]
            shoulder = 0.5 * (
                autocorrelation[:, lag - sharp_offset] +
                autocorrelation[:, lag + sharp_offset])
            score += weight * (peak - shoulder)
        score_columns.append(score)

    scores = np.stack(score_columns, axis=1)
    contrast = np.percentile(response, 95, axis=1)
    scores *= np.sqrt(np.maximum(contrast, 0.0))[:, None]
    scores = cv2.GaussianBlur(
        scores, (0, 0), sigmaX=0.01, sigmaY=3.0)
    scores[:max(0, min_radius), :] = -np.inf
    scores[min(response.shape[0], max_radius + 1):, :] = -np.inf
    flat_index = int(np.argmax(scores))
    radius, period_index = np.unravel_index(flat_index, scores.shape)
    strength = float(scores[radius, period_index])
    if not np.isfinite(strength) or strength <= 0.0:
        return None
    return int(radius), float(periods[period_index]), strength


def _normalize_profile(profile):
    median = float(np.median(profile))
    scale = float(np.percentile(profile, 95)) - median
    if scale <= 1e-3:
        return None
    return np.clip((profile - median) / scale, 0.0, 4.0)


def _circular_interpolate(profile, positions):
    count = len(profile)
    xp = np.arange(count + 1, dtype=np.float64)
    fp = np.concatenate((profile, profile[:1]))
    return np.interp(np.mod(positions, count), xp, fp)


def _longest_circular_run(mask):
    count = len(mask)
    doubled = np.concatenate((mask, mask))
    best_length = 0
    best_start = 0
    start = None
    for index, value in enumerate(doubled):
        if value and start is None:
            start = index
        if start is not None and (not value or index == len(doubled) - 1):
            end = index if value and index == len(doubled) - 1 else index - 1
            length = min(end - start + 1, count)
            if start < count and length > best_length:
                best_length = length
                best_start = start
            start = None
    return best_start % count, best_length


def _low_density_gap(profile, period):
    """周期応答が長く途切れる角度区間を、スケール外の空白として返す。"""
    normalized = _normalize_profile(profile)
    if normalized is None:
        return None
    count = len(normalized)
    tiled = np.tile(normalized, 3).reshape(1, -1)
    density = cv2.GaussianBlur(
        tiled, (0, 0), sigmaX=max(2.0, period * 1.15),
        sigmaY=0.01).ravel()[count:count * 2]
    low = float(np.percentile(density, 15))
    high = float(np.percentile(density, 80))
    contrast = (high - low) / max(abs(high), 1e-6)
    if contrast < 0.25:
        return None
    threshold = low + 0.40 * (high - low)
    start, length = _longest_circular_run(density < threshold)
    # 一部の目盛り欠損が作る短い谷と、スケール外の角度区間を分ける。
    # 円形計器の空白は少なくとも35度あり、単発欠損より十分に長い。
    min_length = max(period * 3.0, count * 35.0 / 360.0)
    if length < min_length or length > count * 0.55:
        return None
    return float(start), float(length)


def _inside_gap(positions, gap, angle_count):
    if gap is None:
        return np.zeros(len(positions), dtype=bool)
    return np.mod(positions - gap[0], angle_count) < gap[1]


def _fit_comb_model(profile, gap=None, reference_period=None):
    """等間隔の櫛を直接相関し、周期と位相を同時に決める。"""
    normalized = _normalize_profile(profile)
    if normalized is None:
        return None
    angle_count = len(normalized)
    min_period = max(4.0, angle_count * 2.0 / 360.0)
    max_period = angle_count * 18.0 / 360.0
    models = []

    def phase_score(local_profile, period, phase):
        positions = np.arange(phase, angle_count, period)
        usable = ~_inside_gap(positions, gap, angle_count)
        positions = positions[usable]
        if len(positions) < 8:
            return None
        tooth = _circular_interpolate(local_profile, positions)
        midpoint = _circular_interpolate(
            local_profile, positions + period * 0.5)
        difference = tooth - midpoint
        ordered = np.sort(difference)
        trim = int(len(ordered) * 0.15)
        if trim:
            ordered = ordered[trim:]
        coverage = float(np.mean((tooth > 0.45) & (difference > 0.15)))
        quality = float(np.mean(np.clip(ordered, -1.0, 4.0)))
        quality *= min(1.0, coverage / 0.70)
        return quality, coverage

    for period in np.arange(min_period, max_period + 0.01, 0.25):
        tolerance = max(1, min(3, int(round(period * 0.16))))
        local_profile = np.maximum.reduce([
            np.roll(normalized, offset)
            for offset in range(-tolerance, tolerance + 1)
        ])
        best_phase = None
        for phase in np.arange(0.0, period, 1.0):
            scored = phase_score(local_profile, period, phase)
            if scored is None:
                continue
            candidate = (scored[0], phase, scored[1])
            if best_phase is None or candidate[0] > best_phase[0]:
                best_phase = candidate
        if best_phase is None:
            continue
        refined = best_phase
        for phase in np.arange(best_phase[1] - 1.0,
                               best_phase[1] + 1.01, 0.25):
            phase %= period
            scored = phase_score(local_profile, period, phase)
            if scored is not None and scored[0] > refined[0]:
                refined = (scored[0], phase, scored[1])
        models.append((refined[0], period, refined[1], refined[2]))

    if not models:
        return None
    models.sort(key=lambda model: model[0], reverse=True)
    strongest = models[0]
    selected = strongest
    if reference_period is not None:
        harmonic_family = []
        for divisor in range(1, 7):
            target = reference_period / divisor
            nearby = [model for model in models
                      if abs(model[1] - target) <= 0.75]
            if nearby:
                harmonic_family.append(
                    max(nearby, key=lambda model: model[0]))
        if harmonic_family:
            selected = max(harmonic_family, key=lambda model: model[0])
    else:
        divisor_candidates = []
        for divisor in range(2, 7):
            target = strongest[1] / divisor
            nearby = [model for model in models
                      if abs(model[1] - target) <= 0.5]
            if not nearby:
                continue
            candidate = max(nearby, key=lambda model: model[0])
            if (candidate[0] >= strongest[0] * 0.58 and
                    candidate[3] >= strongest[3] * 0.75):
                divisor_candidates.append(candidate)
        if divisor_candidates:
            selected = min(divisor_candidates, key=lambda model: model[1])
    if selected[0] < 0.12 or selected[3] < 0.25:
        return None
    return selected


def _comb_positions(profile, model, gap):
    """空白区間内の単発ノイズを無視し、欠けた櫛歯を含む全位置を返す。"""
    quality, period, phase, coverage = model
    del quality, coverage
    angle_count = len(profile)
    if gap is None:
        tooth_count = max(8, int(round(angle_count / period)))
        circular_period = float(angle_count) / tooth_count
        return np.mod(
            phase + np.arange(tooth_count) * circular_period,
            angle_count)
    positions = np.arange(phase, angle_count, period)
    if len(positions) < 8:
        return positions

    normalized = _normalize_profile(profile)
    tolerance = max(1, min(3, int(round(period * 0.16))))
    local_profile = np.maximum.reduce([
        np.roll(normalized, offset)
        for offset in range(-tolerance, tolerance + 1)
    ])
    tooth = _circular_interpolate(local_profile, positions)
    midpoint = _circular_interpolate(
        local_profile, positions + period * 0.5)
    support = (tooth > 0.45) & ((tooth - midpoint) > 0.15)

    gap_center = (gap[0] + gap[1] * 0.5) % angle_count
    distances = np.abs(
        (positions - gap_center + angle_count * 0.5) % angle_count -
        angle_count * 0.5)
    center_cell = int(np.argmin(distances))
    cell_count = len(positions)
    max_search = int(math.ceil(cell_count * 0.55))
    left_active = None
    right_active = None
    for step in range(1, max_search + 1):
        index = (center_cell - step) % cell_count
        if support[index] and support[(index - 1) % cell_count]:
            left_active = index
            break
    for step in range(1, max_search + 1):
        index = (center_cell + step) % cell_count
        if support[index] and support[(index + 1) % cell_count]:
            right_active = index
            break

    if left_active is not None and right_active is not None:
        gap_cells = (right_active - left_active - 1) % cell_count
        if 1 <= gap_cells <= cell_count * 0.55:
            active = []
            index = right_active
            while True:
                active.append(index)
                if index == left_active:
                    break
                index = (index + 1) % cell_count
            return positions[np.asarray(active, dtype=np.int32)]

    return positions[~_inside_gap(positions, gap, angle_count)]


def _radial_length(polar, radius, angle_index, angle_half_width,
                   min_radius=0, max_radius=None):
    """極座標画像で、指定角度の暗線が半径方向に続く長さを測る。"""
    count = polar.shape[1]
    if max_radius is None:
        max_radius = polar.shape[0] - 1
    min_radius = max(0, int(min_radius))
    max_radius = min(polar.shape[0] - 1, int(max_radius))
    columns = [(angle_index + offset) % count
               for offset in range(-angle_half_width, angle_half_width + 1)]
    signal = np.max(polar[:, columns], axis=1) > 127
    # アンチエイリアスや圧縮ノイズで1pxだけ切れた目盛りをつなぐ。
    signal = cv2.morphologyEx(signal.astype(np.uint8).reshape(-1, 1),
                              cv2.MORPH_CLOSE,
                              np.ones((3, 1), dtype=np.uint8)).ravel().astype(bool)
    search_start = max(min_radius, radius - 4)
    search_end = min(max_radius + 1, radius + 5)
    nearby = np.where(signal[search_start:search_end])[0]
    if len(nearby) == 0:
        return 0, float(radius)
    radius = search_start + int(nearby[np.argmin(
        np.abs(search_start + nearby - radius))])

    start = radius
    while start > min_radius and signal[start - 1]:
        start -= 1
    end = radius
    while end < max_radius and signal[end + 1]:
        end += 1
    return end - start + 1, (start + end) / 2.0


def _major_tick_flags(lengths, observed):
    """半径方向の長さと、その周期的な並びから主目盛りを判定する。"""
    count = len(lengths)
    reliable = [lengths[index] for index in range(count) if observed[index]]
    if not reliable:
        return [False] * count
    median_length = float(np.median(reliable))
    long_flags = [
        bool(observed[index] and lengths[index] > median_length * 1.30)
        for index in range(count)
    ]

    if sum(long_flags) < _MIN_MAJOR_TICKS:
        observed_indices = [index for index in range(count) if observed[index]]
        n_major = min(
            len(observed_indices),
            max(_MIN_MAJOR_TICKS,
                int(round(count * _MAJOR_TICK_FALLBACK_RATIO))))
        longest = sorted(
            observed_indices, key=lambda index: lengths[index], reverse=True)
        long_flags = [False] * count
        for index in longest[:n_major]:
            long_flags[index] = True

    long_count = sum(long_flags)
    best_pattern = None
    if long_count >= 2:
        for cadence in range(2, min(10, count // 2) + 1):
            for phase in range(cadence):
                predicted = [index % cadence == phase
                             for index in range(count)]
                predicted_observed = [
                    predicted[index] and observed[index]
                    for index in range(count)
                ]
                predicted_count = sum(predicted_observed)
                if predicted_count < 2:
                    continue
                hits = sum(predicted[index] and long_flags[index]
                           for index in range(count))
                precision = float(hits) / predicted_count
                recall = float(hits) / long_count
                if precision + recall == 0.0:
                    continue
                f1 = 2.0 * precision * recall / (precision + recall)
                group = [lengths[index] for index in range(count)
                         if predicted_observed[index]]
                others = [lengths[index] for index in range(count)
                          if observed[index] and not predicted[index]]
                if not others:
                    continue
                ratio = float(np.median(group)) / max(
                    float(np.median(others)), 1e-6)
                score = f1 + min(ratio, 2.0) * 0.10
                candidate = (score, f1, ratio, predicted)
                if best_pattern is None or candidate[0] > best_pattern[0]:
                    best_pattern = candidate
    if (best_pattern is not None and best_pattern[1] >= 0.65 and
            best_pattern[2] >= 1.12):
        return best_pattern[3]
    return long_flags


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
            # 半径を形で決め打ちせず、盤面全体を広く周期探索する。
            min_radius = int(round(dial_radius * 0.30))
            max_radius = int(round(dial_radius * 0.98))
        else:
            # 円検出が失敗しても、中心付近と画像外だけを除いた広い範囲を使う。
            min_radius = int(round(short * 0.12))
            max_radius = int(round(short * 0.55))
        max_radius = min(max_radius, int(edge_radius))
        if max_radius - min_radius < 8:
            return []

        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        angle_samples = 1440
        # warpPolarの出力は (角度, 半径)。転置して (半径, 角度) として扱う。
        gray_polar = cv2.warpPolar(
            gray, (max_radius + 1, angle_samples), (cx, cy), max_radius,
            cv2.WARP_POLAR_LINEAR | cv2.WARP_FILL_OUTLIERS,
        ).T.astype(np.float32)
        response = _angular_dark_response(gray_polar)
        radius_model = _periodic_radius(response, min_radius, max_radius)
        if radius_model is None:
            return []
        peak_radius, approximate_period, periodic_strength = radius_model
        del periodic_strength

        band_half_width = max(3, int(round(short * 0.01)))
        band_start = max(min_radius, peak_radius - band_half_width)
        band_end = min(max_radius + 1, peak_radius + band_half_width + 1)
        profile = np.mean(response[band_start:band_end], axis=0)

        preliminary_model = _fit_comb_model(
            profile, reference_period=approximate_period)
        if preliminary_model is None:
            return []
        gap = _low_density_gap(profile, preliminary_model[1])
        model = _fit_comb_model(
            profile, gap, reference_period=approximate_period)
        if model is None:
            model = preliminary_model
            gap = _low_density_gap(profile, model[1])
        positions = _comb_positions(profile, model, gap)
        if len(positions) < 8:
            return []

        binary = cv2.adaptiveThreshold(
            gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY_INV, 25, 5
        )
        binary_polar = cv2.warpPolar(
            binary, (max_radius + 1, angle_samples), (cx, cy), max_radius,
            cv2.WARP_POLAR_LINEAR | cv2.WARP_FILL_OUTLIERS,
        ).T

        reference_radius = dial_radius if dial_radius is not None else max_radius
        radial_min = max(
            min_radius, int(round(peak_radius - reference_radius * 0.25)))
        radial_max = min(
            max_radius, int(round(peak_radius + reference_radius * 0.04)))
        angle_half_width = max(
            1, int(round(angle_samples * 0.50 / 360.0)))
        min_line_length = max(3, int(round(short * 0.003)))
        raw = []
        observed = []
        lengths = []
        for position in positions:
            index = int(round(position)) % angle_samples
            length, centroid_radius = _radial_length(
                binary_polar, peak_radius, index, angle_half_width,
                radial_min, radial_max)
            is_observed = length >= min_line_length
            if not is_observed:
                length = 0
                centroid_radius = float(peak_radius)
            angle = 2.0 * math.pi * float(position) / angle_samples
            raw.append({
                'angle': angle,
                'centroid': (
                    cx + centroid_radius * math.cos(angle),
                    cy + centroid_radius * math.sin(angle),
                ),
                'line_angle': angle,
                'length': float(length),
            })
            observed.append(is_observed)
            lengths.append(float(length))

        if sum(observed) < max(4, int(round(len(raw) * 0.20))):
            return []
        reliable_lengths = [lengths[index] for index in range(len(lengths))
                            if observed[index]]
        default_length = float(np.median(reliable_lengths))
        for index in range(len(lengths)):
            if not observed[index]:
                lengths[index] = default_length
                raw[index]['length'] = default_length
        major_flags = _major_tick_flags(lengths, observed)
        for tick, is_major in zip(raw, major_flags):
            tick['is_major'] = bool(is_major)
        raw.sort(key=lambda tick: tick['angle'])
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
