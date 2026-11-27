"""数字付き目盛りの隣接2点で読む。段階2(E)・段階3(B)の誤読チェックも行う。"""
import math

import scale_value_detect


def _order_points(points, *, calibration=None, tick_angles=None):
    """候補点を走査方向に並べ、(ordered, cw, by_value) を返す。"""
    if calibration:
        survivors = []
        for angle, value in calibration:
            matches = [p for p in points if p['value'] == value and
                       abs((p['angle'] - angle + math.pi) % math.tau - math.pi) < 1e-10]
            metadata = max(matches, key=lambda p: p.get('score', 0.0), default={})
            survivors.append(dict(value=value, angle=angle,
                                  score=metadata.get('score', 0.0),
                                  synthetic=metadata.get('synthetic', False)))
        points = survivors
    by_value = {}
    for point in points:
        if not all(math.isfinite(point[key]) for key in ('value', 'angle')):
            continue
        candidate = {key: point.get(key, default) for key, default in
                     (('value', None), ('angle', None), ('score', 0.0), ('synthetic', False))}
        old = by_value.get(candidate['value'])
        if old is None or candidate['score'] > old['score']:
            by_value[candidate['value']] = candidate
    ordered = sorted(by_value.values(), key=lambda p: p['angle'] % math.tau)
    if len(ordered) < 2:
        return None, None, by_value
    gaps = [(ordered[(i + 1) % len(ordered)]['angle'] - p['angle']) % math.tau
            for i, p in enumerate(ordered)]
    # 最大の空白を盤面の切れ目にする。同幅なら値の飛びが最大の境界を選ぶ。
    cut = max(range(len(gaps)), key=lambda i: (
        round(gaps[i], 10), abs(ordered[(i + 1) % len(ordered)]['value'] - ordered[i]['value'])))
    if calibration and len(ordered) > 2:
        # survivorsの両端間が未使用区間。数字の読み漏れによる大きな隙間で切らない。
        low = min(by_value)
        high = max(by_value)
        cut = next((i for i, p in enumerate(ordered)
                    if {p['value'], ordered[(i + 1) % len(ordered)]['value']} == {low, high}), cut)
    elif tick_angles and len(tick_angles) > 2:
        angles = sorted(set(a % math.tau for a in tick_angles))
        seam = max(range(len(angles)), key=lambda i: (angles[(i + 1) % len(angles)] - angles[i]) % math.tau)
        start = angles[(seam + 1) % len(angles)]
        ordered.sort(key=lambda p: (p['angle'] - start) % math.tau)
        cut = len(ordered) - 1
    ordered = ordered[cut + 1:] + ordered[:cut + 1]
    votes = sum(1 if b['value'] > a['value'] else -1
                for a, b in zip(ordered, ordered[1:]))
    if votes == 0:
        return None, None, by_value
    cw = votes > 0
    if not cw:
        ordered.reverse()
    return ordered, cw, by_value


def read_local(points, needle_angle, *, calibration=None, tick_spacing=None, tick_angles=None):
    """survivorsを優先し、値・括弧・候補範囲を返す。不成立ならNone。"""
    if not math.isfinite(needle_angle):
        return None
    ordered, cw, by_value = _order_points(
        points, calibration=calibration, tick_angles=tick_angles)
    if ordered is None:
        return None
    sign = 1 if cw else -1
    positions = [sign * (p['angle'] - ordered[0]['angle']) % math.tau for p in ordered]
    offset = sign * (needle_angle - ordered[0]['angle']) % math.tau
    if offset > positions[-1] + 1e-10:
        return None
    # 数字の間隔は小目盛りの間隔とは限らない。間隔不明なら一致だけを扱う。
    tolerance = tick_spacing / 10 if tick_spacing is not None and tick_spacing > 0 else 1e-10
    # 最後の数字には「次の数字」がないので全体方式へ戻す。
    if abs(offset - positions[-1]) < tolerance:
        return None
    for i, (a, b) in enumerate(zip(ordered, ordered[1:])):
        on_number = abs(offset - positions[i]) < tolerance
        if on_number or positions[i] <= offset <= positions[i + 1]:
            # 次の数字に近ければ、その数字から始まる括弧を優先する。
            if i + 2 < len(ordered) and abs(offset - positions[i + 1]) < tolerance:
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


def _estimate_major_step(ordered):
    """隣接値の正の差から主目盛りの刻み幅（最頻値）を推定する。"""
    diffs = []
    for a, b in zip(ordered, ordered[1:]):
        diff = b['value'] - a['value']
        if diff > 1e-9:
            diffs.append(round(diff, 6))
    if not diffs:
        return None
    counts = {}
    for d in diffs:
        counts[d] = counts.get(d, 0) + 1
    return max(counts, key=lambda d: (counts[d], -d))


def _is_step_multiple(value, step):
    if step is None or step <= 0:
        return True
    ratio = value / step
    return abs(ratio - round(ratio)) <= 1e-4


def _clean_number(value):
    rounded_int = round(value)
    if abs(value - rounded_int) <= 1e-4 * max(1.0, abs(value)):
        return int(rounded_int)
    return round(value, 6)


def _check_roundness_and_score(ordered, bracket, *, score_ratio_threshold=0.5):
    """段階2(E): 切りのよさ（刻み幅の倍数）とOCRスコアで疑わしい点を検出する。"""
    step = _estimate_major_step(ordered)
    scores = sorted(p.get('score', 0.0) for p in ordered if not p.get('synthetic', False) and p.get('score', 0.0) > 0)
    median_score = scores[len(scores) // 2] if scores else 0.0
    suspects = {}
    for role in ('a', 'b'):
        pt = bracket[role]
        reasons = []
        if step is not None and not _is_step_multiple(pt['value'], step):
            reasons.append('not_multiple')
        if median_score > 0 and not pt.get('synthetic', False):
            if pt.get('score', 0.0) < median_score * score_ratio_threshold:
                reasons.append('low_score')
        if reasons:
            suspects[role] = {'point': pt, 'reasons': reasons}
    return {'step': step, 'median_score': median_score, 'suspects': suspects}


def _angle_diff(a, b):
    return abs((a - b + math.pi) % math.tau - math.pi)


def _check_tick_counts(ordered, bracket, tick_angles, *, step=None, suspects=()):
    """段階3(B): 小目盛りの通し番号に基づく周期モデルで括弧点の整合性を検証する。"""
    if not tick_angles or len(tick_angles) < 3 or len(ordered) < 3:
        return {'available': False, 'inconsistent': {}, 'proposals': {}}
    unique_angles = sorted(set(a % math.tau for a in tick_angles))
    if len(unique_angles) < 3:
        return {'available': False, 'inconsistent': {}, 'proposals': {}}
    ticks = [{'angle': a} for a in unique_angles]
    order = scale_value_detect._arc_order(ticks)
    slots = scale_value_detect._tick_slots(ticks, order)
    if slots is None or slots[-1] <= 0:
        return {'available': False, 'inconsistent': {}, 'proposals': {}}

    tick_slot_pairs = [(ticks[idx]['angle'], slots[k]) for k, idx in enumerate(order)]
    point_slots = []
    for pt in ordered:
        nearest_angle, nearest_slot = min(tick_slot_pairs, key=lambda pair: _angle_diff(pt['angle'], pair[0]))
        point_slots.append((nearest_slot, pt))

    inconsistent = {}
    proposals = {}
    suspect_set = set(suspects)
    for role in ('a', 'b'):
        target_pt = bracket[role]
        target_idx = next((i for i, (_, p) in enumerate(point_slots)
                           if p['value'] == target_pt['value'] and _angle_diff(p['angle'], target_pt['angle']) < 1e-10), None)
        if target_idx is None:
            continue
        target_slot = point_slots[target_idx][0]
        others = [(s, p['value']) for i, (s, p) in enumerate(point_slots) if i != target_idx]
        if len(others) < 2:
            continue
        grid = scale_value_detect._fit_major_grid_line(others)
        if grid is not None and abs(grid['slope']) > 1e-9:
            slope = grid['slope']
            intercept = grid['intercept']
            cadence = grid['cadence']
        elif len(others) == 2:
            (s1, v1), (s2, v2) = others
            if s2 == s1 or v2 == v1:
                continue
            if step is not None and not _is_step_multiple(abs(v2 - v1), step):
                continue
            slope = (s2 - s1) / (v2 - v1)
            intercept = s1 - slope * v1
            cad_step = step if (step is not None and step > 0) else abs(v2 - v1)
            cad_float = abs(slope) * cad_step
            cadence = int(round(cad_float))
            if cadence < 2 or abs(cad_float - cadence) > 0.25:
                continue
        else:
            continue
        expected_slot = slope * target_pt['value'] + intercept
        slot_error = abs(expected_slot - target_slot)
        pred_val = (target_slot - intercept) / slope
        val_diff = abs(pred_val - target_pt['value'])
        if role in suspect_set:
            if val_diff > 1e-3 * max(1.0, abs(pred_val)):
                inconsistent[role] = {'point': target_pt, 'predicted': pred_val}
                if step is None or _is_step_multiple(pred_val, step):
                    proposals[role] = _clean_number(pred_val)
        else:
            # Eで疑わしくない点は、3点以上の明確な周期格子の大幅な食い違いのみ不合格にする
            slot_tol = max(1.5, 0.25 * cadence)
            if grid is not None and slot_error >= slot_tol and val_diff > 0.05 * max(1.0, abs(pred_val)):
                inconsistent[role] = {'point': target_pt, 'predicted': pred_val}
                if step is None or _is_step_multiple(pred_val, step):
                    proposals[role] = _clean_number(pred_val)
    return {'available': True, 'inconsistent': inconsistent, 'proposals': proposals}


def check_and_fix_local(points, needle_angle, local_result, *,
                        local_checks=(), calibration=None, tick_spacing=None, tick_angles=None):
    """段階2(E)・段階3(B)の誤読チェックを実行し、判定結果と必要に応じた再計算結果を返す。"""
    statuses = {c: 'off' for c in 'EBCD'}
    if not local_checks or local_result is None:
        return local_result, statuses

    ordered, _cw, _by_value = _order_points(
        points, calibration=calibration, tick_angles=tick_angles)
    if ordered is None:
        for c in local_checks:
            statuses[c] = 'fail'
        return None, statuses

    bracket = local_result['bracket']
    e_res = _check_roundness_and_score(ordered, bracket) if 'E' in local_checks else None
    step = e_res['step'] if e_res is not None else _estimate_major_step(ordered)
    e_suspects = e_res['suspects'] if e_res is not None else {}
    b_res = _check_tick_counts(
        ordered, bracket, tick_angles, step=step, suspects=e_suspects.keys()
    ) if 'B' in local_checks else None
    b_inconsistent = b_res['inconsistent'] if b_res is not None else {}
    b_proposals = b_res['proposals'] if b_res is not None else {}

    # 修正(fixed): EとBの両方が有効で、Eが疑わしいと判定した点をBが刻み倍数として別値に特定できた場合
    replacements = {}
    if 'E' in local_checks and 'B' in local_checks:
        for role in ('a', 'b'):
            if role in e_suspects and role in b_proposals:
                replacements[role] = b_proposals[role]

    if replacements and len(replacements) == len(e_suspects):
        updated_points = []
        for p in points:
            p_copy = dict(p)
            for role, new_val in replacements.items():
                orig = bracket[role]
                if p_copy.get('value') == orig['value'] and _angle_diff(p_copy.get('angle', 0.0), orig['angle']) < 1e-10:
                    p_copy['value'] = new_val
            updated_points.append(p_copy)
        updated_cal = None
        if calibration:
            updated_cal = []
            for ang, val in calibration:
                new_v = val
                for role, new_val in replacements.items():
                    orig = bracket[role]
                    if val == orig['value'] and _angle_diff(ang, orig['angle']) < 1e-10:
                        new_v = new_val
                updated_cal.append((ang, new_v))
        recalculated = read_local(
            updated_points, needle_angle,
            calibration=updated_cal, tick_spacing=tick_spacing, tick_angles=tick_angles)
        if recalculated is not None:
            statuses['E'] = 'fixed'
            statuses['B'] = 'fixed'
            return recalculated, statuses

    # 不合格(fail): 有効なチェックで不整合・疑わしい点があり、信頼できる修正ができなかった場合
    failed = False
    if 'E' in local_checks:
        if e_suspects:
            statuses['E'] = 'fail'
            failed = True
        else:
            statuses['E'] = 'pass'
    if 'B' in local_checks:
        if b_inconsistent:
            statuses['B'] = 'fail'
            failed = True
        else:
            statuses['B'] = 'pass'

    if failed:
        return None, statuses
    return local_result, statuses
