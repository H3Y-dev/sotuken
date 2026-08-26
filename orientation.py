import cv2
import scale_value_detect

def normalize_orientation(img):
    """
    画像を0度・90度・180度・270度回転させてOCRを試し、
    一番多く数字が読めた向きに直した画像を返す。
    
    戻り値:
        (直した画像, 採用した角度, 採用した角度での検出数, 0度での検出数)
    """
    best_angle = 0
    best_count = -1
    zero_count = 0

    angles = [0, 90, 180, 270]
    for angle in angles:
        rotated = _rotate(img, angle)
        results = scale_value_detect.read_scale_numbers(rotated)
        count = len(results) if results else 0

        # 0度のとき読めた個数を記録しておく
        if angle == 0:
            zero_count = count

        # 同点のときは0度を優先したいので > を使う
        if count > best_count:
            best_count = count
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