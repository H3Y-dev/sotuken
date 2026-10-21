"""数字付き目盛りの隣接2点で読む。画像処理や誤読修正はここでは行わない。"""
import math
import statistics


def read_local(points, needle_angle, *, calibration=None, tick_spacing=None):
    """survivorsを優先し、値・括弧・候補範囲を返す。不成立ならNone。"""
    by_value = {}
    for point in points:
        if not all(math.isfinite(point[key]) for key in ('value', 'angle')):
            continue
        candidate = {key: point.get(key, default) for key, default in
                     (('value', None), ('angle', None), ('score', 0.0), ('synthetic', False))}
        old = by_value.get(candidate['value'])
        if old is None or candidate['score'] > old['score']:
            by_value[candidate['value']] = candidate
    if calibration:
        survivors = []
        for angle, value in calibration:
            metadata = by_value.get(value, {})
            survivors.append(dict(value=value, angle=angle,
                                  score=metadata.get('score', 0.0),
                                  synthetic=metadata.get('synthetic', False)))
        return read_local(survivors, needle_angle, tick_spacing=tick_spacing)
    ordered = sorted(by_value.values(), key=lambda p: p['angle'] % math.tau)
    if len(ordered) < 2 or not math.isfinite(needle_angle):
        return None
    gaps = [(ordered[(i + 1) % len(ordered)]['angle'] - p['angle']) % math.tau
            for i, p in enumerate(ordered)]
    # 最大の空白を盤面の切れ目にする。同幅なら値の飛びが最大の境界を選ぶ。
    cut = max(range(len(gaps)), key=lambda i: (
        round(gaps[i], 10), abs(ordered[(i + 1) % len(ordered)]['value'] - ordered[i]['value'])))
    ordered = ordered[cut + 1:] + ordered[:cut + 1]
    votes = sum(1 if b['value'] > a['value'] else -1
                for a, b in zip(ordered, ordered[1:]))
    if votes == 0:
        return None
    cw = votes > 0
    if not cw:
        ordered.reverse()
    sign = 1 if cw else -1
    positions = [sign * (p['angle'] - ordered[0]['angle']) % math.tau for p in ordered]
    offset = sign * (needle_angle - ordered[0]['angle']) % math.tau
    if offset > positions[-1] + 1e-10:
        return None
    if tick_spacing is None:
        tick_spacing = statistics.median(b - a for a, b in zip(positions, positions[1:]))
    # 最後の数字には「次の数字」がないので全体方式へ戻す。
    if abs(offset - positions[-1]) < tick_spacing / 10:
        return None
    for i, (a, b) in enumerate(zip(ordered, ordered[1:])):
        on_number = abs(offset - positions[i]) < tick_spacing / 10
        if on_number or positions[i] <= offset <= positions[i + 1]:
            # 次の数字に近ければ、その数字から始まる括弧を優先する。
            if i + 2 < len(ordered) and abs(offset - positions[i + 1]) < tick_spacing / 10:
                continue
            span = positions[i + 1] - positions[i]
            if span <= 0 or b['value'] <= a['value']:
                return None
            ratio = 0.0 if on_number else (offset - positions[i]) / span
            return dict(value=a['value'] + (b['value'] - a['value']) * ratio,
                        bracket=dict(a=a, b=b), cw=cw,
                        min_value=min(by_value), max_value=max(by_value))
    return None


def cross_check_diff_fs(value_local, value_global, min_value, max_value):
    """全体方式との差（%FS）。幅ゼロの場合は比較不能。"""
    span = abs(max_value - min_value)
    return abs(value_local - value_global) / span * 100 if span else None
