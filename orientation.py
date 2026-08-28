import cv2
import scale_value_detect

def normalize_orientation(img, min_margin=2):
    """
    画像を0度・90度・180度・270度回転させてOCRを試し、
    一番多く数字が読めた向きに直した画像を返す。

    0度（正立）が僅差で他の向きに負けただけで回転してしまうと、
    既に正しい向きの写真まで誤って回転させてしまう（反射・グレア等で
    OCRの検出数が±1個程度ぶれることがあるため。2026-08-28、
    企業提供画像の耐圧試験_昇圧前圧力計.jpgで実測: 0度=4個、180度=5個
    という僅差で180度が選ばれ、354.99という全く誤った値になった）。
    0度より `min_margin` 個以上多く読めた場合のみ、他の向きを採用する。

    戻り値:
        (直した画像, 採用した角度, 採用した角度での検出数, 0度での検出数)
    """
    counts = {}
    for angle in (0, 90, 180, 270):
        rotated = _rotate(img, angle)
        results = scale_value_detect.read_scale_numbers(rotated)
        counts[angle] = len(results) if results else 0

    zero_count = counts[0]
    best_angle = 0
    best_count = zero_count
    for angle in (90, 180, 270):
        if counts[angle] >= zero_count + min_margin and counts[angle] > best_count:
            best_count = counts[angle]
            best_angle = angle

    return _rotate(img, best_angle), best_angle, best_count, zero_count

def _rotate(img, angle):
    """画像を指定した角度だけ回転させる。0度はそのまま返す。"""
    if angle == 0:
        return img
    elif angle == 90:
        return cv2.rotate(img, cv2.ROTATE_90_CLOCKWISE)
    elif angle == 180:
        return cv2.rotate(img, cv2.ROTATE_180)
    elif angle == 270:
        return cv2.rotate(img, cv2.ROTATE_90_COUNTERCLOCKWISE)
    return img