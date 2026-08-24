"""目盛り線の幾何からメーターの回転中心を推定する。"""

import math

import numpy as np


def _line_from_tick(tick):
    """tickを正規化した直線 ``normal @ point = offset`` に変換する。"""
    try:
        px, py = tick['centroid']
        theta = float(tick['line_angle'])
        values = np.asarray([px, py, theta], dtype=float)
    except (KeyError, TypeError, ValueError):
        return None

    if not np.all(np.isfinite(values)):
        return None

    direction = np.asarray([math.cos(theta), math.sin(theta)], dtype=float)
    normal = np.asarray([-direction[1], direction[0]], dtype=float)
    point = values[:2]
    return normal, float(normal @ point)


def _intersection(line_a, line_b):
    normals = np.vstack([line_a[0], line_b[0]])
    determinant = float(np.linalg.det(normals))
    if abs(determinant) < 1e-6:
        return None
    return np.linalg.solve(normals, np.asarray([line_a[1], line_b[1]]))


def _fit_least_squares(lines):
    normals = np.vstack([line[0] for line in lines])
    offsets = np.asarray([line[1] for line in lines])

    # 同じ向きの線ばかりでは、線に沿う方向の中心位置を決められない。
    if np.linalg.matrix_rank(normals) < 2:
        return None
    if np.linalg.cond(normals) > 1e6:
        return None

    center, _, _, _ = np.linalg.lstsq(normals, offsets, rcond=None)
    if not np.all(np.isfinite(center)):
        return None
    return center


def _distance_threshold(img):
    if img is None or not hasattr(img, 'shape') or len(img.shape) < 2:
        return 2.0
    height, width = img.shape[:2]
    # 既存の目盛り検出は主軸と放射方向の差を18度まで許容する。
    # 実画像の輪郭分断による主軸誤差も支持線に残せる幅を確保する。
    return max(2.0, math.hypot(float(width), float(height)) * 0.027)


def estimate_center(img, ticks=None):
    """目盛り線の交点から回転中心を推定する。

    Args:
        img: 対象画像。外れ値判定の距離しきい値と、ticks未指定時の
            目盛り検出に使用する。
        ticks: ``centroid`` と ``line_angle`` を持つ目盛り辞書の列。
            Noneなら画像中央を起点に既存の目盛り検出を実行する。

    Returns:
        ``(x, y)`` のfloatタプル。推定不能ならNone。中心が画像外でも
        座標をそのまま返す。
    """
    if ticks is None:
        if img is None or not hasattr(img, 'shape') or len(img.shape) < 2:
            return None
        from tick_detect import detect_scale_ticks

        height, width = img.shape[:2]
        ticks = detect_scale_ticks(img, (width / 2.0, height / 2.0))

    lines = []
    for tick in ticks:
        line = _line_from_tick(tick)
        if line is not None:
            lines.append(line)

    if len(lines) < 3:
        return None

    threshold = _distance_threshold(img)
    minimum_inliers = max(3, int(math.ceil(len(lines) * 0.5)))
    best_inlier_indices = None
    best_residuals = None
    best_score = None

    # 2本を標本とするRANSAC。目盛り本数は小さいためランダム抽出せず、
    # 全組合せを調べて実行ごとの差をなくす。
    for first in range(len(lines) - 1):
        for second in range(first + 1, len(lines)):
            candidate = _intersection(lines[first], lines[second])
            if candidate is None:
                continue

            residuals = np.asarray([
                abs(float(normal @ candidate) - offset)
                for normal, offset in lines
            ])
            inlier_indices = np.flatnonzero(residuals <= threshold)
            if len(inlier_indices) < minimum_inliers:
                continue

            # 支持線が多い候補を優先し、同数なら残差の小さい候補を選ぶ。
            score = (
                len(inlier_indices),
                -float(np.median(residuals[inlier_indices])),
            )
            if best_score is None or score > best_score:
                best_score = score
                best_inlier_indices = inlier_indices
                best_residuals = residuals

    if best_inlier_indices is None:
        return None

    # 広い支持判定の端に紛れた外れ値が最小二乗を引っ張らないよう、
    # 支持線の残差中央値から求めた内側の集合でフィットする。
    median_residual = float(np.median(best_residuals[best_inlier_indices]))
    fit_threshold = max(2.0, min(threshold, median_residual * 2.5))
    fit_indices = np.flatnonzero(best_residuals <= fit_threshold)
    if len(fit_indices) < minimum_inliers:
        fit_indices = best_inlier_indices

    inlier_lines = [lines[index] for index in fit_indices]
    center = _fit_least_squares(inlier_lines)
    if center is None:
        return None

    return float(center[0]), float(center[1])
