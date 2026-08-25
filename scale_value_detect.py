"""
RapidOCR（PaddleOCRのPP-OCR系モデルをONNX Runtimeで実行するライブラリ）で
盤面上の数字を読み取り、既に検出済みの目盛り線（tick_detect.detect_scale_ticks）
と角度で対応付けることで、0目盛り・フルスケール目盛りの位置と値を自動決定する。

OCR＋目盛り対応付けだけでは対応付けできた数字が少なく信頼度が低い場合、
VLM（vlm_scale_value）に「min_value/max_valueが何か」だけを問い合わせ、
その値に一致するOCR数字の位置を探す形でフォールバックする。
VLMは値の意味理解は得意だが精密な位置推定は苦手なため、
位置はあくまでOCR＋目盛り検出側で特定する役割分担にしている。
"""

import math
import re
import threading

import cv2

import tick_detect
import vlm_scale_value

_engine = None
_load_lock = threading.Lock()


def _load_engine():
    global _engine
    if _engine is not None:
        return _engine
    with _load_lock:
        if _engine is None:  # ロック待ちの間に他スレッドが読み込み済みの場合
            from rapidocr import RapidOCR
            _engine = RapidOCR()
    return _engine


_NUMBER_RE = re.compile(r'-?\d+(\.\d+)?')

# OCRが数字と紛らわしい文字を誤認識するケースの補正用
# （例: "0"を"O"、"1"を"l"/"I"と読むなど）。
# 変換後に全体が数字パターンに一致する場合のみ採用するため、
# 数字と無関係な文字列（"PRESSURE"等）を誤って数値化する心配はない。
_CONFUSION_MAP = str.maketrans({
    'O': '0', 'o': '0', 'Q': '0', 'D': '0',
    'l': '1', 'I': '1', '|': '1',
    'Z': '2',
    'S': '5', 's': '5',
    'G': '6', 'b': '6',
    'B': '8',
    'g': '9', 'q': '9',
})


def _normalize_ocr_text(text):
    return text.translate(_CONFUSION_MAP)


def _split_merged_number_boxes(candidates):
    """隣接ラベルを一つに読んだ、幅が不自然に広い整数ボックスを分割する。"""
    character_widths = []
    for candidate in candidates:
        text = candidate['text']
        if text.isdigit():
            width = candidate['x_right'] - candidate['x_left']
            character_widths.append(width / len(text))
    if not character_widths:
        return candidates

    sorted_widths = sorted(character_widths)
    middle = len(sorted_widths) // 2
    if len(sorted_widths) % 2:
        typical_width = sorted_widths[middle]
    else:
        typical_width = (sorted_widths[middle - 1] + sorted_widths[middle]) / 2.0

    split_candidates = []
    for candidate in candidates:
        text = candidate['text']
        width = candidate['x_right'] - candidate['x_left']
        # 134730では融合ボックスが正常値の1.24倍に留まるため、実測に合わせて
        # 1.2倍とする。後続の等差列・先頭ゼロの検証で誤分割を抑止する。
        if (not text.isdigit() or len(text) % 2 or
                width / len(text) < typical_width * 1.2):
            split_candidates.append(candidate)
            continue

        half = len(text) // 2
        left_text = text[:half]
        right_text = text[half:]
        # ``2000 -> 20, 00`` のように、正当な4桁ラベルを壊さない。
        if ((len(left_text) > 1 and left_text.startswith('0')) or
                (len(right_text) > 1 and right_text.startswith('0'))):
            split_candidates.append(candidate)
            continue

        left_value = float(left_text)
        right_value = float(right_text)
        step = abs(right_value - left_value)
        other_values = [item['value'] for item in candidates if item is not candidate]
        if step == 0 or not other_values:
            split_candidates.append(candidate)
            continue

        # 分割した二値と既存値が同じ刻みの並びになることを確認する。
        # 近傍に1刻み差の既存値があり、全既存値も同じ格子上にある場合だけ採用する。
        has_neighbor = any(
            abs(value - left_value) == step or abs(value - right_value) == step
            for value in other_values
        )
        on_same_grid = all(
            abs((value - left_value) / step - round((value - left_value) / step)) < 1e-6
            for value in other_values
        )
        if not has_neighbor or not on_same_grid:
            split_candidates.append(candidate)
            continue

        midpoint = (candidate['x_left'] + candidate['x_right']) / 2.0
        left_candidate = candidate.copy()
        left_candidate.update({
            'text': left_text,
            'value': left_value,
            'x': (candidate['x_left'] + midpoint) / 2.0,
        })
        right_candidate = candidate.copy()
        right_candidate.update({
            'text': right_text,
            'value': right_value,
            'x': (midpoint + candidate['x_right']) / 2.0,
        })
        split_candidates.extend([left_candidate, right_candidate])

    return split_candidates


def read_scale_numbers(img):
    """
    盤面上の数字をOCRで検出する。
    戻り値: [{'value': float, 'x': float, 'y': float, 'score': float}, ...]
    """
    engine = _load_engine()
    result = engine(img)
    candidates = []
    if result is None or result.boxes is None:
        return candidates

    for box, text, score in zip(result.boxes, result.txts, result.scores):
        text = text.strip()
        normalized = _normalize_ocr_text(text)
        if not _NUMBER_RE.fullmatch(normalized):
            continue
        try:
            value = float(normalized)
        except ValueError:
            continue
        # シリアル番号・型番等、桁数の多い数字は目盛りの値ではないので除外
        if abs(value) >= 10000:
            continue

        xs = [p[0] for p in box]
        ys = [p[1] for p in box]
        candidates.append({
            'text': normalized,
            'value': value,
            'x_left': float(min(xs)),
            'x_right': float(max(xs)),
            'x': float(sum(xs) / len(xs)),
            'y': float(sum(ys) / len(ys)),
            'score': float(score),
        })

    numbers = []
    for candidate in _split_merged_number_boxes(candidates):
        numbers.append({
            'value': candidate['value'],
            'x': candidate.get(
                'x', (candidate['x_left'] + candidate['x_right']) / 2.0),
            'y': candidate['y'],
            'score': candidate['score'],
        })
    return numbers


def bind_numbers_to_ticks(numbers, ticks, center, max_angle_deg=12.0, major_bonus_deg=4.0):
    """
    各数字を、角度が最も近い目盛り線に対応付ける。
    1つの数字につき対応付ける目盛りは1つだけに絞る
    （そうしないと、1つの数字が近傍の複数の目盛り＝主目盛りと副目盛り数本の
    両方に同時に対応付いてしまい、後段のmin/max選定で「同じ値を持つ候補が
    複数ある」状態になる。この場合どれが選ばれるかは配列順序に依存して
    不定になり、たまたま副目盛りが選ばれて位置が目盛り1本分ずれる原因になる）。
    1つの目盛り線を複数の数字が取り合った場合はスコアが良い方を優先する。

    印字された数字は基本的に主目盛り（is_major）の位置にあるはずなので、
    主目盛りには角度スコアにボーナス（major_bonus_deg）を与えて優先する。

    戻り値: [{'value': float, 'tick': tick_dict, 'angle': float}, ...]
    """
    if not numbers or not ticks:
        return []

    cx, cy = center
    max_diff = math.radians(max_angle_deg)
    bonus = math.radians(major_bonus_deg)

    # 各数字ごとに最良の目盛り候補を1つだけ選ぶ
    number_candidates = []  # (score, number, tick_idx)
    for n in numbers:
        angle = math.atan2(n['y'] - cy, n['x'] - cx)
        best_score, best_idx = None, None
        for i, t in enumerate(ticks):
            diff = abs(((t['angle'] - angle + math.pi) % (2 * math.pi)) - math.pi)
            if diff >= max_diff:
                continue
            score = diff - bonus if t['is_major'] else diff
            if best_score is None or score < best_score:
                best_score, best_idx = score, i
        if best_idx is not None:
            number_candidates.append((best_score, n, best_idx))

    number_candidates.sort(key=lambda c: c[0])
    used_ticks = set()
    bound = []
    for score, n, idx in number_candidates:
        if idx in used_ticks:
            continue
        used_ticks.add(idx)
        bound.append({'value': n['value'], 'tick': ticks[idx], 'angle': ticks[idx]['angle']})

    return bound


def _longest_monotonic(values, increasing=True):
    """valuesの中で単調な(非減少/非増加)最長部分列のインデックス列を返す。"""
    n = len(values)
    if n == 0:
        return []
    dp = [1] * n
    parent = [-1] * n
    for i in range(n):
        for j in range(i):
            ok = values[j] <= values[i] if increasing else values[j] >= values[i]
            if ok and dp[j] + 1 > dp[i]:
                dp[i] = dp[j] + 1
                parent[i] = j
    end = max(range(n), key=lambda i: dp[i])
    path = []
    while end != -1:
        path.append(end)
        end = parent[end]
    return list(reversed(path))


def _predict_angle_for_value(bound, target_value):
    """
    対応付け済みの(value, tick)ペア群から値と角度の線形関係（1目盛りあたりの
    角度）を推定し、target_valueに対応するはずの角度を予測する。
    複数目盛り分離れたペア（例: 100→150）も、その間の目盛り数で割って
    単位角度に正規化してから平均する（正規化しないと、間隔の広いペアを
    「1目盛り分」として扱ってしまい、予測が大きく狂う）。
    ペアが2件未満、または値が全て同じ場合はNoneを返す。
    """
    by_value = {}
    for b in bound:
        by_value.setdefault(b['value'], b)
    unique_sorted = sorted(by_value.keys())
    if len(unique_sorted) < 2:
        return None

    diffs = [unique_sorted[i + 1] - unique_sorted[i] for i in range(len(unique_sorted) - 1)]
    positive_diffs = [d for d in diffs if d > 0]
    if not positive_diffs:
        return None
    step = min(positive_diffs)

    per_step_angles = []
    for i in range(len(unique_sorted) - 1):
        v1, v2 = unique_sorted[i], unique_sorted[i + 1]
        b1, b2 = by_value[v1], by_value[v2]
        raw_gap = ((b2['angle'] - b1['angle'] + math.pi) % (2 * math.pi)) - math.pi
        n_steps = round((v2 - v1) / step)
        if n_steps <= 0:
            continue
        per_step_angles.append(raw_gap / n_steps)
    if not per_step_angles:
        return None
    angle_per_step = sum(per_step_angles) / len(per_step_angles)

    nearest_value = min(unique_sorted, key=lambda v: abs(v - target_value))
    nearest = by_value[nearest_value]
    n_steps_to_target = round((target_value - nearest_value) / step)
    return nearest['angle'] + n_steps_to_target * angle_per_step


def locate_value_by_extrapolation(bound, ticks, target_value, max_angle_deg=8.0):
    """
    OCRがtarget_value自体を読み落とした場合の最終手段。
    対応付けに成功した他の数字群から目盛りの等間隔性を推定し、
    target_valueがあるはずの角度を予測して、その付近の主目盛りを探す
    （SGR論文等でも使われている「等間隔性から欠測値を推定する」手法）。
    VLMなどで既にtarget_valueの値そのものは分かっている場合にのみ使うこと
    （このAPI自体は値を発見するものではなく、既知の値の位置を探すためのもの）。
    見つかった目盛りの座標(x, y)、見つからなければNoneを返す。
    """
    predicted_angle = _predict_angle_for_value(bound, target_value)
    if predicted_angle is None:
        return None

    best_tick, best_diff = None, math.radians(max_angle_deg)
    for t in ticks:
        if not t['is_major']:
            continue
        diff = abs(((t['angle'] - predicted_angle + math.pi) % (2 * math.pi)) - math.pi)
        if diff < best_diff:
            best_diff = diff
            best_tick = t

    if best_tick is None:
        return None
    return (int(round(best_tick['centroid'][0])), int(round(best_tick['centroid'][1])))


def _synthesize_tick_point(ticks, center, angle):
    """
    angle方向に実在する目盛り線が見つからない場合の最終手段として、
    他の主目盛りの平均半径を使って座標だけを合成する。
    針が目盛りに重なって輪郭ごと検出から漏れている（そもそも候補が
    存在しない）ケースでのみ使う想定。
    """
    cx, cy = center
    major = [t for t in ticks if t['is_major']] or list(ticks)
    if not major:
        return None
    radii = [math.hypot(t['centroid'][0] - cx, t['centroid'][1] - cy) for t in major]
    r = sum(radii) / len(radii)
    return (int(round(cx + r * math.cos(angle))), int(round(cy + r * math.sin(angle))))


def _make_occlusion_check(img):
    """
    「針が0の目盛りに重なっているか」をVLMに問い合わせる関数を返す。
    呼び出しは重いため、実際に必要になるまで行わず、一度呼んだら
    結果をキャッシュして使い回す（1回の検出につき最大1回だけ問い合わせる）。
    """
    cache = {}

    def check():
        if 'v' not in cache:
            try:
                cache['v'] = vlm_scale_value.check_needle_overlaps_zero(img)
            except Exception:
                cache['v'] = None
        return bool(cache['v'])

    return check


def _resolve_scale_position(img, numbers, ticks, center, bound, value,
                             is_zero=False, occlusion_check=None):
    """
    target_valueに対応する目盛り位置を特定する。
    OCRで直接読めていればそれを、読めていなければ等間隔性からの推定
    （locate_value_by_extrapolation）を使い、通常は該当箇所を再OCRして
    実在を確認できた場合のみ採用する（VLMのハルシネーション対策）。

    ただし is_zero=True の場合に限り、再OCRでの確認が失敗しても、
    「針が0の目盛りに重なっている」ことがVLMで確認できていれば、
    見えなくて当然なので確認をスキップしてそのまま採用する。
    さらに、針と目盛りの輪郭が融合して目盛り候補自体が見つからない
    場合は、等間隔性から予測した角度と他の主目盛りの平均半径を使って
    座標を合成する（この合成もis_zero=True かつ重なりを確認できた
    場合のみ行う。それ以外では根拠のない当てずっぽうになるため使わない）。

    occlusion_check: 「針が0の目盛りに重なっているか」を返す0引数の関数
    （呼び出しは重いので必要になるまで遅延評価する）。Noneの場合は
    この判定なしで、通常通りの安全側の挙動（確認できなければ採用しない）になる。

    戻り値: (座標 or None, 視覚的な裏取りなしに「重なり」を理由として採用したか)
    """
    pt = locate_value_on_ticks(numbers, ticks, center, value)
    if pt is not None:
        return pt, False

    pt = locate_value_by_extrapolation(bound, ticks, value)
    if pt is not None:
        if _verify_label_near_position(img, pt, value):
            return pt, False
        if is_zero and occlusion_check is not None and occlusion_check():
            return pt, True
        return None, False

    if is_zero and occlusion_check is not None and occlusion_check():
        predicted_angle = _predict_angle_for_value(bound, value)
        if predicted_angle is not None:
            synth = _synthesize_tick_point(ticks, center, predicted_angle)
            if synth is not None:
                return synth, True
    return None, False


def _verify_label_near_position(img, pt, target_value, radius=60, upscale=4):
    """
    ptの周辺だけを切り出して拡大し、OCRを再実行してtarget_valueに一致する
    数字が実際にそこにあるかを確認する。

    VLMがmin_value/max_valueを誤って報告する（ハルシネーション）ことがあり、
    その値をそのまま信じてOCR＋目盛りの結果を上書きするのは危険なため、
    上書きを許可する前に「本当にその位置にその数字が見えるか」を
    ローカルクロップで再検証する。全体画像では小さすぎて拾えなかった数字も、
    該当箇所だけを拡大することで読み取れることが多い一方、
    実際には存在しない数字はここでも見つからず、誤った上書きを防げる。
    """
    x, y = pt
    h, w = img.shape[:2]
    x0, x1 = max(0, x - radius), min(w, x + radius)
    y0, y1 = max(0, y - radius), min(h, y + radius)
    crop = img[y0:y1, x0:x1]
    if crop.size == 0:
        return False

    upscaled = cv2.resize(crop, (crop.shape[1] * upscale, crop.shape[0] * upscale),
                           interpolation=cv2.INTER_CUBIC)
    try:
        local_numbers = read_scale_numbers(upscaled)
    except Exception:
        return False
    return any(abs(n['value'] - target_value) < 1e-6 for n in local_numbers)


# 計器のフルスケールは、切りの良い値（標準数）から選ばれるのが普通。
# 1, 1.5, 2, 2.5, 3, 4, 5, 6, 7.5, 8 ... に10のべき乗を掛けた値。
# このプロジェクトで扱っている計器も 8 / 10 / 20 / 30 / 60 / 100 / 150 / 400 と、
# すべてこの形に収まっている。
_PLAUSIBLE_FULLSCALE_MANTISSAS = (1.0, 1.2, 1.5, 2.0, 2.5, 3.0, 4.0, 5.0,
                                  6.0, 7.5, 8.0)


def is_plausible_fullscale(value, rel_tol=0.005):
    """
    フルスケールとしてありえる値か（標準数かどうか）を判定する。

    OCRが目盛り線を数字と誤読すると、`1111` のような現実にはあり得ない
    フルスケール値が出ることがある。2026-08-25の実測では、
    20260817_134619.jpg でスケールが 20〜1111 と誤検出され、真値45に対し
    1101.91と読んで引用誤差880%FSを記録していた。**この1枚だけで全体の
    平均引用誤差が16%FSから60%FSへ跳ね上がっていた。**

    ここで弾いた場合、値を捨てるのではなく信頼度を下げる。
    既存のVLMフォールバックに委ねるほうが安全なため。
    """
    if value is None or value <= 0:
        return False
    exponent = math.floor(math.log10(abs(value)))
    mantissa = abs(value) / (10.0 ** exponent)
    for m in _PLAUSIBLE_FULLSCALE_MANTISSAS:
        if abs(mantissa - m) <= rel_tol * m:
            return True
    return False


def determine_min_max(bound_pairs, min_points=3, n_ocr_unique=None, ticks=None):
    """
    数字が対応付けられた目盛りの集合から、0目盛り・フルスケール目盛りを決定する。

    盤面には数字の並んでいない「隙間」（例: 0とフルスケールの間の未使用区間）が
    あるのが普通なので、角度差が最大の箇所を隙間とみなして円環を1本の直線に開き、
    その上で値が単調に並ぶ最長部分列を求める。これにより、誤読や無関係な数字
    （シリアル番号の一部など）が混入していても外れ値として除外できる。

    n_ocr_unique: OCRが読み取った数字の異なる値の種類数（分かる場合）。
    盤面上の目盛り線検出そのものが一部の領域で失敗していると、
    OCRは正しく数字を読めていても対応付く目盛りが少数に偏り、
    「対応付いた中では辻褄が合っている」ように見えてしまうことがある。
    そこでOCRが読めた値の種類数に対して実際に採用できた値の種類数の
    割合も見て、信頼度判定に使う。

    戻り値: {'zero_pt', 'full_pt', 'min_value', 'max_value', 'n_used', 'n_total'}
             または、対応付けが不十分な場合はNone
    """
    if len(bound_pairs) < min_points:
        return None

    ordered = sorted(bound_pairs, key=lambda b: b['angle'])
    n = len(ordered)
    gaps = []
    for i in range(n):
        a1 = ordered[i]['angle']
        a2 = ordered[(i + 1) % n]['angle']
        gaps.append((a2 - a1) % (2 * math.pi))

    # 最大の隙間1つだけを正解と決め打ちすると、OCRが連続する数字を
    # 複数読み漏らした場合に生じる「見かけ上大きな隙間」に惑わされて、
    # 本来の隙間（フルスケールと0の間）とは違う場所で円を切り開いてしまい、
    # 結果として本来の最小値・最大値の一方を外れ値扱いしてしまうことがある
    # （読み漏れが多いほど誤った隙間が本物と同程度の大きさになりやすい）。
    # そこで隙間が大きい候補を複数試し、単調部分列が最も長くなる
    # （＝最も辻褄が合う）ものを採用する。
    n_candidates = min(n, 5)
    seam_candidates = sorted(range(n), key=lambda i: gaps[i], reverse=True)[:n_candidates]

    best = None
    for seam in seam_candidates:
        linear = ordered[seam + 1:] + ordered[:seam + 1]
        values = [b['value'] for b in linear]
        inc_idx = _longest_monotonic(values, increasing=True)
        dec_idx = _longest_monotonic(values, increasing=False)
        idx = inc_idx if len(inc_idx) >= len(dec_idx) else dec_idx
        if len(idx) < min_points:
            continue
        if best is None or len(idx) > len(best[0]):
            best = (idx, linear)

    if best is None:
        return None
    best_idx, linear = best

    survivors = [linear[i] for i in best_idx]
    zero_pair = min(survivors, key=lambda b: b['value'])
    full_pair = max(survivors, key=lambda b: b['value'])
    if zero_pair['value'] == full_pair['value']:
        return None

    n_used = len(survivors)
    n_total = len(bound_pairs)
    # 対応付けできた数字が少ない・採用率が低い場合は、真の0/フルスケールの
    # tickがそもそも候補から漏れている可能性が高く、信頼度が低いとみなす
    is_confident = n_used >= 6 and (n_used / n_total) >= 0.6

    if is_confident and n_ocr_unique:
        # 目盛り線検出が盤面の一部でしか成功していない場合、対応付けできた
        # 値の種類が少数に偏っていても「対応付いた中では辻褄が合う」ため
        # 上のチェックだけでは高信頼と誤判定してしまう。OCRが読めた値のうち
        # 実際に採用できた値の割合が低ければ信頼度を下げる。
        value_coverage = len({b['value'] for b in survivors}) / n_ocr_unique
        is_confident = value_coverage >= 0.5

    # フルスケールが標準数から外れている場合は、OCRが目盛り線を数字と
    # 誤読した可能性が高い。値は捨てず信頼度だけ下げ、VLMフォールバックに委ねる
    if is_confident and not is_plausible_fullscale(full_pair['value']):
        is_confident = False

    # OCRが最小ラベルを読み落としていても、等間隔に並ぶ主目盛りが実在する場合だけ
    # 1本ずつ最小値を補完する。弧の端までは外挿しない。
    if ticks:
        unique_values = sorted({pair['value'] for pair in survivors})
        steps = [unique_values[i + 1] - unique_values[i]
                 for i in range(len(unique_values) - 1)
                 if unique_values[i + 1] > unique_values[i]]
        if steps:
            step = min(steps)
            original_min = zero_pair['value']
            original_span = full_pair['value'] - original_min
            # 元の値幅の50%以内で、かつ数目盛りまでに制限する。
            max_extension_steps = min(3, int(original_span / (2.0 * step)))
            all_observed_non_negative = all(pair['value'] >= 0 for pair in bound_pairs)
            used_tick_points = {
                (int(round(pair['tick']['centroid'][0])),
                 int(round(pair['tick']['centroid'][1])))
                for pair in survivors
            }

            for _index in range(max_extension_steps):
                candidate_value = zero_pair['value'] - step
                if all_observed_non_negative and candidate_value < 0:
                    break
                candidate_pt = locate_value_by_extrapolation(
                    survivors, ticks, candidate_value)
                # 許容角内に既存の対応済み目盛りしかない場合は、候補の主目盛りは
                # 実在しない。既存目盛りの再利用による誤延長を防ぐ。
                if candidate_pt is None or candidate_pt in used_tick_points:
                    break
                zero_pair = {
                    'value': candidate_value,
                    'tick': {'centroid': candidate_pt},
                }
                used_tick_points.add(candidate_pt)

    return {
        'zero_pt': (int(round(zero_pair['tick']['centroid'][0])),
                    int(round(zero_pair['tick']['centroid'][1]))),
        'full_pt': (int(round(full_pair['tick']['centroid'][0])),
                    int(round(full_pair['tick']['centroid'][1]))),
        'min_value': zero_pair['value'],
        'max_value': full_pair['value'],
        'n_used': n_used,
        'n_total': n_total,
        'is_confident': is_confident,
        'source': 'ocr_tick',
        'needle_overlap_zero': False,
    }


def locate_value_on_ticks(numbers, ticks, center, target_value, max_angle_deg=15.0,
                           major_bonus_deg=4.0):
    """
    target_valueに一致する（無ければ最も近い）OCR数字を探し、
    その角度に最も近い目盛り線の座標を返す（主目盛りを優先。理由はbind_numbers_to_ticks参照）。
    近傍に目盛り線が見つからない場合は、数字ラベル自体の座標を返す
    （目盛り線検出が漏れている場合の次善策）。
    見つからなければNone。
    """
    if not numbers:
        return None

    exact = [n for n in numbers if abs(n['value'] - target_value) < 1e-6]
    if exact:
        candidates = exact
    else:
        closest = min(numbers, key=lambda n: abs(n['value'] - target_value))
        if abs(closest['value'] - target_value) > max(1.0, abs(target_value) * 0.05):
            return None
        candidates = [closest]

    cx, cy = center
    max_diff = math.radians(max_angle_deg)
    bonus = math.radians(major_bonus_deg)
    best_pt, best_score = None, max_diff
    fallback_number = candidates[0]

    for n in candidates:
        angle = math.atan2(n['y'] - cy, n['x'] - cx)
        for t in ticks:
            diff = abs(((t['angle'] - angle + math.pi) % (2 * math.pi)) - math.pi)
            if diff >= max_diff:
                continue
            score = diff - bonus if t['is_major'] else diff
            if score < best_score:
                best_score = score
                best_pt = (int(round(t['centroid'][0])), int(round(t['centroid'][1])))

    if best_pt is not None:
        return best_pt
    # 近傍に目盛り線が無い場合は、数字ラベルの位置をそのまま採用する
    return (int(round(fallback_number['x'])), int(round(fallback_number['y'])))


def _run_ocr_tick(img, ticks, center, max_angle_deg, min_points):
    """1つの（前処理済み）画像に対してOCR＋目盛り対応付けを1回実行する。"""
    numbers = read_scale_numbers(img)
    bound = bind_numbers_to_ticks(numbers, ticks, center, max_angle_deg=max_angle_deg)
    n_ocr_unique = len({n['value'] for n in numbers})
    return determine_min_max(bound, min_points=min_points, n_ocr_unique=n_ocr_unique,
                             ticks=ticks)


def _find_agreeing_result(results):
    """
    複数の（前処理違いの）試行結果のうち、min/maxが一致するものが
    2件以上あれば、その中で最もn_usedが大きいものを返す。
    どの2件も一致しなければNone（クロスチェック不成立＝信頼できない）。
    """
    groups = {}
    for r in results:
        key = (round(r['min_value'], 3), round(r['max_value'], 3))
        groups.setdefault(key, []).append(r)

    best_group = max(groups.values(), key=len, default=[])
    if len(best_group) < 2:
        return None
    return max(best_group, key=lambda r: r['n_used'])


def detect_scale_values(img, ticks, center, max_angle_deg=12.0, min_points=3):
    """
    元画像と、CLAHE（コントラスト強調）を適用した複数のバリアントそれぞれで
    OCR＋目盛り対応付けを行い、min/maxの判定が一致するかをクロスチェックする。

    単一の前処理条件だけでは「対応付いた中では辻褄が合っている」ように見える
    誤った結果を信頼度チェックだけで見抜けないことがある（反射・グレア等で
    目盛り線検出が偏る場合）。前処理条件を変えても同じ答えになるかを見ることで、
    より頑健に信頼性を判定する。

    どの2条件も一致しない場合は、VLMにmin_value/max_valueだけを問い合わせ、
    該当するOCR数字の位置を探して結果を補う。

    複数条件が一致した場合でも、それだけでは安心できない：OCRがある数字
    （典型的には0）をどの前処理条件でも一貫して読み落とすケースでは、
    全条件が「同じ間違い」で一致してしまい、クロスチェックをすり抜ける。
    そのためVLMのmin_value/max_valueとも必ず突き合わせ、食い違う側だけを
    OCR数字の再探索・等間隔性からの推定で補正する。

    呼び出し側が既に検出済みのticks（呼び出し側がどんな前処理を使っていても良い）も
    クロスチェックの候補の1つとして扱う。内部で試す元画像／CLAHE各条件は、
    呼び出し側の前処理設定に関わらず必ずそれぞれ独立に検出し直す
    （呼び出し側の前処理を「元画像」枠に混ぜてしまうと、クロスチェックの
    前提である「独立した複数条件での再現性確認」が崩れてしまうため）。
    """
    variant_images = [img, tick_detect.apply_clahe(img, 1.5), tick_detect.apply_clahe(img, 2.5)]

    results = []
    try:
        result = _run_ocr_tick(img, ticks, center, max_angle_deg, min_points)
        if result is not None:
            results.append(result)
    except Exception:
        pass

    for variant_img in variant_images:
        try:
            variant_ticks = tick_detect.detect_scale_ticks(variant_img, center)
            result = _run_ocr_tick(variant_img, variant_ticks, center, max_angle_deg, min_points)
        except Exception:
            result = None
        if result is not None:
            results.append(result)

    agreed = _find_agreeing_result(results)

    numbers = read_scale_numbers(img)
    vlm_result = vlm_scale_value.read_min_max(img)

    if agreed is not None:
        agreed['is_confident'] = True
        agreed['source'] = 'ocr_tick'

        if vlm_result is not None:
            # 既に複数条件で一致した結果をVLMの値で上書きするのは、
            # VLMが値を誤って報告する（ハルシネーション）リスクがあるため慎重に行う。
            # OCRが実際にその数字を読めていた場合（locate_value_on_ticks成功）は
            # そのまま信頼するが、等間隔性からの推定（locate_value_by_extrapolation）
            # しか根拠が無い場合は、対象位置をローカルで再OCRして実在を確認できた
            # ときだけ採用する。
            vlm_min, vlm_max = vlm_result
            bound = None
            occlusion_check = _make_occlusion_check(img)
            if abs(agreed['min_value'] - vlm_min) > 1e-6:
                bound = bind_numbers_to_ticks(numbers, ticks, center, max_angle_deg=max_angle_deg)
                pt, overlap = _resolve_scale_position(
                    img, numbers, ticks, center, bound, vlm_min,
                    is_zero=True, occlusion_check=occlusion_check)
                if pt is not None:
                    agreed['zero_pt'] = pt
                    agreed['min_value'] = vlm_min
                    agreed['needle_overlap_zero'] = overlap
            if abs(agreed['max_value'] - vlm_max) > 1e-6:
                if bound is None:
                    bound = bind_numbers_to_ticks(numbers, ticks, center, max_angle_deg=max_angle_deg)
                pt, _overlap = _resolve_scale_position(
                    img, numbers, ticks, center, bound, vlm_max,
                    is_zero=False, occlusion_check=occlusion_check)
                if pt is not None:
                    agreed['full_pt'] = pt
                    agreed['max_value'] = vlm_max

        return agreed

    # 前処理条件間で結果が割れた（不安定）、またはどれも対応付け不足
    if vlm_result is not None:
        min_value, max_value = vlm_result
        bound = bind_numbers_to_ticks(numbers, ticks, center, max_angle_deg=max_angle_deg)
        occlusion_check = _make_occlusion_check(img)

        zero_pt, zero_overlap = _resolve_scale_position(
            img, numbers, ticks, center, bound, min_value,
            is_zero=True, occlusion_check=occlusion_check)
        full_pt, _overlap = _resolve_scale_position(
            img, numbers, ticks, center, bound, max_value,
            is_zero=False, occlusion_check=occlusion_check)

        if zero_pt is not None and full_pt is not None:
            return {
                'zero_pt': zero_pt,
                'full_pt': full_pt,
                'min_value': min_value,
                'max_value': max_value,
                'n_used': 2,
                'n_total': 2,
                'is_confident': True,
                'source': 'vlm',
                'needle_overlap_zero': zero_overlap,
            }

    # VLMも失敗した場合、条件間で割れた結果のうち一番マシなものを
    # 「低信頼」として返す（無ければNoneのまま手動選択にフォールバック）
    if results:
        best = max(results, key=lambda r: r['n_used'])
        best['is_confident'] = False
        best['source'] = 'ocr_tick'
        return best
    return None
