"""
GUIを起動せずに、画像1枚からメーターの値までを一気通貫で求めるモジュール。

main_sotuken.py のGUIが順番に呼んでいる処理（盤面のクロップ →
中心点検出 → 目盛り線検出 → 目盛り数値の読み取り → 針の読み取り）を、
ユーザー操作を挟まずに同じ順序で実行する。

GUIは各段階でユーザーに確認を求めるが、ここでは全て自動採用する。
つまりこのモジュールが返す結果は「人が一切手を貸さなかった場合の
自動検出の実力」であり、精度評価にはこの条件が適している。

どの段階で失敗したかを stage に入れて返すので、評価時に
「中心が取れないのか、目盛りが読めないのか、針が見えないのか」を
切り分けられる。
"""
import math

import numpy as np

import meter_reader
import orientation
import scale_value_detect
import tick_detect
import vlm_scale_value
import detect_meter_center_v2
import center_estimate
import circle_fit
import center_consensus

# 処理段階。失敗した場合、その段階名が結果の stage に入る
STAGE_CENTER = 'center'
STAGE_SCALE = 'scale'
STAGE_NEEDLE = 'needle'
STAGE_OK = 'ok'


def _detect_center(img):
    """
    Hough円検出・estimate_center（目盛り線の交点）・円フィッティング
    （目盛りcentroid群への当てはめ）の3候補の一致度から中心を決める。

    3候補が対等な3票ではないことに注意: estimate_centerと円フィッティングは
    どちらも同じ目盛り検出結果（ticks）に依存しているため独立した情報源
    ではない。Hough円検出のみが盤面外周ベゼルという別の画像特徴を見る
    独立した情報源。resolve_center_consensus側でこの前提を踏まえて
    一致度判定・ネジ等の誤検出対策を行う。
    """
    h, w = img.shape[:2]

    # 候補1: Hough円検出
    hough_result = detect_meter_center_v2.detect_meter_center_from_raw(img)

    # refine_center_iterativeのseedには、旧来通りHough中心があればそれを使う
    seed = hough_result["center"] if hough_result is not None else (w // 2, h // 2)

    # 目盛り検出は1回だけ行い、estimate_centerとfit_circle_to_ticksの両方に渡す
    try:
        _refined, ticks = tick_detect.refine_center_iterative(img, seed)
    except Exception:
        ticks = None

    # 候補2: estimate_center（目盛り線の交点）
    estimate = None
    if ticks:
        try:
            estimate = center_estimate.estimate_center(img, ticks)
        except Exception:
            estimate = None

    # 候補3: 円フィッティング（Taubin法）
    fit_result = None
    if ticks:
        try:
            fit_result = circle_fit.fit_circle_to_ticks(ticks, method="taubin")
        except Exception:
            fit_result = None

    center, source = center_consensus.resolve_center_consensus(
        hough_result, estimate, fit_result, img.shape, ticks=ticks
    )
    return center, source


def read_meter(img, use_vlm=True):
    """
    画像1枚を自動で読み取る。

    use_vlm: Falseにすると、VLM（Ollama）を使う処理をすべて飛ばす。
             VLMはモデルのロード状態で応答が変わることがあるため、測定結果を
             再現可能にして比較したいときは必ずFalseにする。

    戻り値: dict
        stage        : 'ok' か、失敗した段階名（center / scale / needle）
        value        : 読み取った値（失敗時 None）
        min_value/max_value : 自動検出した目盛りの最小値・最大値
        center, zero_pt, full_pt : 検出した各点
        n_ticks      : 検出した目盛り線の本数
        scale_source : 目盛り数値をどう決めたか（'ocr_tick' / 'vlm'）
        cropped      : VLMによる盤面クロップが効いたか
        processed_img : クロップ・向き補正を適用した後の画像。
                        center/zero_pt/full_pt等の座標はこの画像を
                        基準にしている（呼び出し元が渡した元のimgでは
                        ないので、オーバーレイ描画等に座標を使うときは
                        必ずこちらを使うこと）
    """
    result = {
        'stage': None,
        'value': None,
        'ratio': None,
        'angle_deg': None,
        'min_value': None,
        'max_value': None,
        'center': None,
        'zero_pt': None,
        'full_pt': None,
        'n_ticks': 0,
        'scale_source': None,
        'scale_confident': None,
        'center_source': None,
        'cropped': False,
        'orientation_angle': None,
        'processed_img': None,
        'error': None,
    }

    # ── 盤面のクロップ（失敗しても元画像で続行する） ──
    if use_vlm:
        try:
            bbox = vlm_scale_value.detect_meter_bbox(img)
            if bbox is not None:
                cropped = tick_detect.crop_with_margin(img, bbox)
                if cropped is not None:
                    img = cropped
                    result['cropped'] = True
        except Exception:
            pass

    # ── 向きの正規化（90度単位の回転を検出して直す） ──
    # 4方向でOCRを試し、一番多く数字が読めた向きを採用する。
    # 中心点検出より前に行う必要がある（回転したままだと目盛りの
    # 角度配置自体がずれ、中心・目盛り検出の前提が崩れるため）。
    try:
        img, orientation_angle, _best_count, _zero_count = (
            orientation.normalize_orientation(img))
        result['orientation_angle'] = orientation_angle
    except Exception:
        pass

    # クロップ・向き補正が終わった後の画像。以降このimgは書き換わらない
    result['processed_img'] = img

    # ── 中心点 ──
    center, center_source = _detect_center(img)
    result['center_source'] = center_source
    if center is None:
        result['stage'] = STAGE_CENTER
        return result
    result['center'] = center

    # ── 目盛り線（CLAHEでコントラストを上げてから検出する） ──
    try:
        enhanced = tick_detect.apply_clahe(img, clip_limit=2.0)
        ticks = tick_detect.detect_scale_ticks(enhanced, center)
        if len(ticks) >= 3:
            refined = tick_detect.refine_center_from_ticks(
                ticks, center, img.shape)
            if refined is not None:
                center = refined
                result['center'] = center
    except Exception as e:
        ticks = []
        result['error'] = str(e)
    result['n_ticks'] = len(ticks)

    # ── 目盛りの数値（OCR、必要時のみVLMで補助する） ──
    try:
        scale = scale_value_detect.detect_scale_values(
            img, ticks, center, use_vlm=use_vlm)
    except Exception as e:
        scale = None
        result['error'] = str(e)

    if scale is None:
        result['stage'] = STAGE_SCALE
        return result

    # 数字の位置から主目盛りを付け直した目盛りが返ってきていれば、
    # そちらを以後の基準にする（描画・検証も同じ判定を見られるようにする）
    if scale.get('ticks'):
        ticks = scale['ticks']
    result['ticks'] = ticks

    result['zero_pt'] = scale['zero_pt']
    result['full_pt'] = scale['full_pt']
    result['min_value'] = scale['min_value']
    result['max_value'] = scale['max_value']
    result['scale_source'] = scale.get('source')
    result['scale_confident'] = scale.get('is_confident')

    # ── 針 ──
    # 目盛りの角度を渡すことで、スケールがどちら回りかを推測せず確定できる。
    # 渡さないと、針がスケール範囲の外を指したときに逆回りの弧に収まって
    # しまい大きく誤読する（meter_reader.arc_ratio のdocstring参照）
    tick_angles = [t['angle'] for t in ticks if 'angle' in t] if ticks else None

    reading = meter_reader.compute_reading(
        img, center, scale['zero_pt'], scale['full_pt'],
        scale['min_value'], scale['max_value'],
        tick_angles=tick_angles,
        calibration_angles=scale.get('calibration'))
    if reading is None:
        result['stage'] = STAGE_NEEDLE
        return result

    result['value'] = reading['value']
    result['ratio'] = reading['ratio']
    result['angle_deg'] = reading['angle_deg']
    result['stage'] = STAGE_OK
    return result
