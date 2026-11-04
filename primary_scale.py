"""数字を半径帯に分ける。値の推定と格子整合の検証は既存処理に任せる。"""

import math
from statistics import median

# 実測: 合成の一重inside列0.69〜0.70、実写9枚の主列0.745以上、副列のみの例0.60。
INNER_COLUMN_RADIUS_RATIO = .65


def split_number_bands(numbers, center, tick_radius):
    if not numbers or tick_radius <= 0:
        return []
    radial = sorted((math.hypot(n['x'] - center[0], n['y'] - center[1]), i, n)
                    for i, n in enumerate(numbers))
    groups = []
    for item in radial:
        if not groups or item[0] - median(p[0] for p in groups[-1]) > tick_radius * .08:
            groups.append([])
        groups[-1].append(item)
    bands = []
    for group in groups:
        column = [p[2] for p in sorted(group, key=lambda p: p[1])]
        angles = sorted(math.atan2(n['y'] - center[1], n['x'] - center[0]) % (2 * math.pi)
                        for n in column)
        gaps = [b - a for a, b in zip(angles, angles[1:])]
        gaps.append(angles[0] + 2 * math.pi - angles[-1])
        span = 2 * math.pi - max(gaps) if len(angles) > 1 else 0
        bands.append(dict(numbers=column, radius=median(p[0] for p in group),
                          supported=len({n['value'] for n in column}) >= 3 and span >= math.pi / 2))
    return bands


def needs_primary_recheck(bands, tick_radius):
    columns = [b for b in bands if len({n['value'] for n in b['numbers']}) >= 2]
    return bool(columns and (len(columns) > 1 or
                             max(b['radius'] for b in columns) < tick_radius * INNER_COLUMN_RADIUS_RATIO))
