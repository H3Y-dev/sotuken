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
import scale_value_detect
import tick_detect
import vlm_scale_value

# 処理段階。失敗した場合、その段階名が結果の stage に入る
STAGE_CENTER = 'center'
STAGE_SCALE = 'scale'
STAGE_NEEDLE = 'needle'
STAGE_OK = 'ok'


def _detect_center(img):
    """
    GUIと同じ手順で中心点を決める。
    Hough円検出と目盛り線からの推定を突き合わせ、大きく食い違う場合は
    目盛り線側を採用する（Houghがリベット等を誤検出した場合の対策）。
    """
    h, w = img.shape[:2]

    hough = tick_detect.auto_detect_center(img)
    seed = (hough[0], hough[1]) if hough is not None else (w // 2, h // 2)

    try:
        refined, _ticks = tick_detect.refine_center_iterative(img, seed)
    except Exception:
        refined = None

    if hough is not None and refined is not None:
        shift = math.hypot(refined[0] - hough[0], refined[1] - hough[1])
        if shift > min(h, w) * 0.03:
            return refined, 'corrected'
        return (hough[0], hough[1]), 'hough'
    if hough is not None:
        return (hough[0], hough[1]), 'hough'
    if refined is not None:
        return refined, 'ticks'
    return None, None


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
        tick_angles=tick_angles)
    if reading is None:
        result['stage'] = STAGE_NEEDLE
        return result

    result['value'] = reading['value']
    result['ratio'] = reading['ratio']
    result['angle_deg'] = reading['angle_deg']
    result['stage'] = STAGE_OK
    return result
