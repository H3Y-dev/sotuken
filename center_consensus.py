# -*- coding: utf-8 -*-
"""
Hough円検出・estimate_center・円フィッティングの3候補から、
どれを採用するか(多数決/棄却)を決めるロジック(T1-2)。

前提となる限界:
    estimate_center と fit_circle_to_ticks はどちらも同じ
    tick_detect.detect_scale_ticks の結果(ticks)を入力に使う。
    つまりこの2つは独立した情報源ではなく、「同じ目盛り検出結果に対する
    2通りの幾何計算」である。目盛り検出そのものが誤っていれば、
    この2つは同じ理由で同時に外れる可能性がある。
    Hough円検出だけが、目盛り検出とは無関係な独立した情報源
    (盤面の外周ベゼルという別の画像特徴)である。
    このため3候補を単純に「3つの独立した投票」として多数決するのではなく、
    「Hough vs (目盛りベースの2手法)」という構造を前提に扱う
    (2候補しか無い場合の食い違い処理、下記のネジ誤検出対策、および
    n==3のケースでの目盛りベース2候補対策に反映されている)。

一致判定の閾値は、既存のmeter_pipeline._detect_centerが使っていた
「画像短辺の3%」という考え方をそのまま踏襲する。

追記(2026-08-27): 企業提供画像での回帰を受けた対策
    結線後、企業提供画像の1枚(丸型温度計)で、中心が盤面中心ではなく
    盤面下部の取り付けネジ付近に誤検出される事例が見つかった。
    tick_detect.detect_scale_ticks() がネジのねじ山模様を目盛り線として
    誤検出し、その汚染されたticksを入力に使うestimate_centerと
    fit_circle_to_ticksの両方が「同じ理由で」ネジ側にズレて一致して
    しまい、2候補一致という判定基準のもとで誤って採用されていた。

    これは上記の「Hough vs 目盛りベース2手法」という構造の逆側の
    ケースであり、既存のHough単独誤検出対策
    (_check_hough_radius_consistency / _check_hough_tick_distance)では
    捕捉できない。resolve_center_consensus のn==3のケースに、
    「estimate-fitのみが一致し、Houghはそのどちらとも一致しない」場合は
    目盛りベース側の一致を疑いHough側を優先する対策を追加した。
"""
import math


def _extract_center(candidate):
    """candidate は dict({'center': (x, y), ...})、(x, y) タプル、または None。"""
    if candidate is None:
        return None
    if isinstance(candidate, dict):
        return candidate.get("center")
    return candidate


def _dist(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])


def _mean_point(points):
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    n = len(points)
    return (sum(xs) / n, sum(ys) / n)


def _check_hough_radius_consistency(hough, fit_result, radius_ratio_threshold):
    """Hough半径とfit_result半径が大きく食い違う(ネジ等の小円疑い)場合Falseを返す。

    どちらかの半径情報が無ければ判定できないためTrue(問題なし扱い)を返す。
    """
    if hough is None or fit_result is None:
        return True
    h_r = hough.get("radius")
    f_r = fit_result.get("radius")
    if not h_r or not f_r:
        return True
    ratio = min(h_r, f_r) / max(h_r, f_r)
    return ratio >= radius_ratio_threshold


def _check_hough_tick_distance(hough, ticks, tick_distance_ratio):
    """Hough中心が目盛り重心群の外接矩形対角線に対して極端に離れている場合Falseを返す。

    ticksが無ければ判定できないためTrue(問題なし扱い)を返す。
    """
    if hough is None or not ticks:
        return True
    xs = [t["centroid"][0] for t in ticks]
    ys = [t["centroid"][1] for t in ticks]
    if not xs:
        return True
    diagonal = math.hypot(max(xs) - min(xs), max(ys) - min(ys))
    if diagonal == 0:
        return True
    tick_centroid = (sum(xs) / len(xs), sum(ys) / len(ys))
    h_center = hough.get("center")
    if h_center is None:
        return True
    dist = _dist(h_center, tick_centroid)
    return dist <= diagonal * tick_distance_ratio


def resolve_center_consensus(
    hough,
    estimate,
    fit_result,
    img_shape,
    ticks=None,
    threshold_ratio=0.03,
    radius_ratio_threshold=0.5,
    tick_distance_ratio=0.7,
):
    """3候補の一致度から採用する中心座標を決める。

    Args:
        hough: detect_meter_center_v2.detect_meter_center_from_raw() の戻り値。
            dict({'center': (x, y), 'radius': r, ...}) または None。
        estimate: center_estimate.estimate_center() の戻り値。
            (x, y) の float タプル、または None。
        fit_result: circle_fit.fit_circle_to_ticks() の戻り値。
            dict({'center': (x, y), 'radius': r, 'method': ...}) または None。
        img_shape: img.shape (h, w[, c])。閾値を画像短辺に対する割合で決めるために使う。
        ticks: tick_detect.detect_scale_ticks() の戻り値(centroidキー付き辞書列)。
            ネジ誤検出対策(目盛り重心群からの距離チェック)に使う。省略可。
        threshold_ratio: 一致とみなす距離の閾値(画像短辺に対する割合)。
            既存の_detect_centerの3%を踏襲しデフォルト0.03。
        radius_ratio_threshold: Hough半径とfit_result半径の比がこれを下回ったら
            Hough候補をネジ等の誤検出疑いとして単独棄却する。
        tick_distance_ratio: Hough中心が目盛り重心群の外接矩形対角線の
            この割合を超えて離れていたらHough候補を単独棄却する。

    Returns:
        (center, source) のペア。
        center は (x, y) の float タプル、採用できなければ None。
        source は 'consensus'(3候補中2つ以上が一致) /
                  'hough_preferred_over_ticks'(estimate/fitのみ一致だが
                      Houghがそのどちらとも一致せず、目盛り汚染を疑い
                      Hough側を優先) /
                  'fallback_2_agree'(2候補のみで一致) /
                  'fallback_2_corrected'(2候補のみで食い違い、目盛りベース側を採用) /
                  'single'(候補が1つのみ) /
                  None(全候補が割れた、または候補が無い=棄却)。
    """
    h, w = img_shape[0], img_shape[1]
    threshold = min(h, w) * threshold_ratio

    hough_center = _extract_center(hough) if hough is not None else None
    estimate_center_pt = estimate
    fit_center = _extract_center(fit_result) if fit_result is not None else None

    # ネジ等の誤検出対策: Hough候補を採用前に単独で妥当性チェックする。
    if hough_center is not None:
        if not _check_hough_radius_consistency(hough, fit_result, radius_ratio_threshold):
            hough_center = None
        elif not _check_hough_tick_distance(hough, ticks, tick_distance_ratio):
            hough_center = None

    candidates = {}
    if hough_center is not None:
        candidates["hough"] = hough_center
    if estimate_center_pt is not None:
        candidates["estimate"] = estimate_center_pt
    if fit_center is not None:
        candidates["fit"] = fit_center

    n = len(candidates)

    if n == 0:
        return None, None

    if n == 1:
        return list(candidates.values())[0], "single"

    if n == 2:
        keys = list(candidates.keys())
        p1, p2 = candidates[keys[0]], candidates[keys[1]]
        if _dist(p1, p2) <= threshold:
            return _mean_point([p1, p2]), "fallback_2_agree"
        # 食い違う場合: 既存の_detect_centerと同じ考え方で、
        # 目盛りベース側(estimate/fit)をHoughより優先する。
        tick_based = [k for k in keys if k in ("estimate", "fit")]
        if "hough" in keys and tick_based:
            return candidates[tick_based[0]], "fallback_2_corrected"
        # 両方とも目盛りベース(同じ情報源由来)で食い違う場合は棄却する。
        return None, None

    # n == 3: 3点間の距離を計算し、2点以上が閾値以内なら一致とみなす。
    pairs = [("hough", "estimate"), ("hough", "fit"), ("estimate", "fit")]
    agreeing_pairs = [
        pair for pair in pairs if _dist(candidates[pair[0]], candidates[pair[1]]) <= threshold
    ]

    if not agreeing_pairs:
        return None, None

    # 目盛りベース2候補(estimate/fit)対策:
    # estimate と fit はどちらも同じ tick_detect.detect_scale_ticks の結果に
    # 依存しているため、独立した2つの情報源ではない。目盛り検出そのものが
    # 誤っている(例: ネジのねじ山を目盛り線として誤検出する)場合、
    # estimate と fit は同じ理由で「一緒に」ズレることがある。
    # このとき単純な多数決では、間違った2候補の一致が正しいHough候補より
    # 優先されてしまう。
    #
    # そこで、「estimate-fitのみが一致し、Houghはそのどちらとも一致しない」
    # 場合に限り、目盛りベース側の一致を疑い、独立した情報源であるHough側
    # (この時点で既に_check_hough_radius_consistency /
    # _check_hough_tick_distance を通過済み)を優先して採用する。
    # Houghがestimate・fitのどちらか一方とでも一致していれば、それは
    # 従来通り正常な多数決として扱う(このガードは発動しない)。
    tick_pair_agrees = ("estimate", "fit") in agreeing_pairs
    hough_agrees_with_either = (
        ("hough", "estimate") in agreeing_pairs or ("hough", "fit") in agreeing_pairs
    )
    if tick_pair_agrees and not hough_agrees_with_either and "hough" in candidates:
        return candidates["hough"], "hough_preferred_over_ticks"

    agree_keys = set()
    for pair in agreeing_pairs:
        agree_keys.update(pair)
    agree_points = [candidates[k] for k in agree_keys]
    return _mean_point(agree_points), "consensus"
