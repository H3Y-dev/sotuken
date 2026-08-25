import cv2
import numpy as np
import os
import sys


def preprocess(img):
    """照明ムラを抑えるための前処理(CLAHE + ぼかし)"""
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    gray = clahe.apply(gray)
    gray = cv2.medianBlur(gray, 5)
    return gray


def select_best_circle(circles, img_shape, center_tol_ratio=0.3):
    """
    検出された円候補の中から、盤面である可能性が最も高いものを選ぶ。

    基本方針:「画像の中心に一番近い円」を選ぶ(撮影ルールが
    「正面から、メーターを画面中央に収めて撮る」であるため)。

    ただし、この前提が崩れているケース
    (=一番中心に近い候補でも、実際には中心からかなり離れている)
    では、中心距離を基準にすること自体が信頼できない。
    その場合は、cv2.HoughCirclesの出力が基本的に
    「投票数(円としての一致度)が高い順」に並んでいることを利用し、
    配列の先頭(＝最も強く円だと判定されたもの)を採用する
    別ロジックに切り替える。

    どちらのロジックを使ったかを2つ目の戻り値で返す
    ("center" か "fallback_strongest")。
    """
    h, w = img_shape[:2]
    cx, cy = w / 2, h / 2
    tol = center_tol_ratio * min(h, w)

    def dist_to_center(c):
        x, y, _ = c
        return ((x - cx) ** 2 + (y - cy) ** 2) ** 0.5

    best_by_center = min(circles, key=dist_to_center)

    if dist_to_center(best_by_center) <= tol:
        # 中心付近に候補があるので、中心基準をそのまま信頼する
        return best_by_center, "center"

    # 中心基準では「近い」と言える候補が無い
    # → 中心が前提のロジックが効かないケースとみなし、
    #    投票数が最も強い円(=配列の先頭)にフォールバックする
    return circles[0], "fallback_strongest"


def crop_to_meter_face(img, margin_ratio=0.15, debug_path=None):
    """
    1段階目: 生の写真(背景込み)から、盤面のだいたいの位置を
    「厳しい判定から徐々に緩める」Hough円検出で掴み、余白付きでクロップする。

    厳しい判定(param2が高い)ほど、コントラストの強い完全な円しか
    検出されない。外周のベゼルは写真内で最もエッジが強い円であることが
    多いため、まず厳しい設定で探し、見つからない場合だけ弱い円(装飾円や
    ロゴなど)まで許容範囲を広げる。

    戻り値: (クロップ後の画像, オフセット(x0, y0))
            クロップできなかった場合は (元画像, (0, 0))
    """
    gray = preprocess(img)

    circles = None
    for param2 in range(80, 25, -5):
        circles = cv2.HoughCircles(
            gray, cv2.HOUGH_GRADIENT, dp=1.5,
            minDist=img.shape[0] // 2,
            param1=100, param2=param2,
            minRadius=int(min(img.shape[:2]) * 0.1),
            maxRadius=int(min(img.shape[:2]) * 0.8),
        )
        if circles is not None:
            break

    if circles is None:
        # 厳しい設定でも緩い設定でも見つからなかった場合は、
        # クロップせず元画像のまま次段階に渡す(縮退)
        return img, (0, 0)

    circles = np.round(circles[0, :]).astype("int")
    (x, y, r), selection_mode = select_best_circle(circles, img.shape)

    margin = int(r * (1 + margin_ratio))
    x0, y0 = max(0, x - margin), max(0, y - margin)
    x1, y1 = min(img.shape[1], x + margin), min(img.shape[0], y + margin)

    cropped = img[y0:y1, x0:x1]

    if debug_path is not None:
        ext = os.path.splitext(debug_path)[1] or ".jpg"
        success, buf = cv2.imencode(ext, cropped)
        if success:
            buf.tofile(debug_path)

    return cropped, (x0, y0)


def detect_circle_adaptive(gray, img_shape):
    """2段階目: param2を段階的に緩めながら、盤面の円を精密に検出する"""
    for param2 in range(60, 20, -5):
        circles = cv2.HoughCircles(
            gray, cv2.HOUGH_GRADIENT, dp=1.2,
            minDist=img_shape[0] // 2,
            param1=100, param2=param2,
            minRadius=int(img_shape[0] * 0.2),
            maxRadius=int(img_shape[0] * 0.6),
        )
        if circles is not None:
            return circles, param2
    return None, None


def detect_meter_center(cropped_img):
    """
    クロップ済み画像に対して、盤面の円を検出し、
    中心座標・半径・直径を求める(クロップ画像内でのローカル座標)。
    """
    gray = preprocess(cropped_img)
    circles, used_param2 = detect_circle_adaptive(gray, cropped_img.shape)

    if circles is None:
        return None

    circles = np.round(circles[0, :]).astype("int")
    (x, y, r), selection_mode = select_best_circle(circles, cropped_img.shape)

    return {
        "center": (int(x), int(y)),
        "radius": int(r),
        "diameter": int(r) * 2,
        "param2": used_param2,
        "selection_mode": selection_mode,
    }


def detect_meter_center_from_raw(raw_img):
    """
    生の写真(背景込み)を受け取り、
    1. crop_to_meter_face で盤面付近をクロップ
    2. detect_meter_center でクロップ画像内の中心を精密検出
    3. クロップ時のオフセットを足して、元の写真上での座標に変換
    を一気に行う。

    戻り値: dict(center, radius, diameter, param2, crop_box) または None
            center は元の写真上での座標(オフセット補正済み)
    """
    cropped, (x0, y0) = crop_to_meter_face(raw_img)

    result = detect_meter_center(cropped)
    if result is None:
        return None

    # クロップ画像内のローカル座標 → 元の写真上のグローバル座標に変換
    lx, ly = result["center"]
    result["center"] = (lx + x0, ly + y0)
    result["crop_box"] = (x0, y0, x0 + cropped.shape[1], y0 + cropped.shape[0])
    return result


def draw_result(img, result):
    """検出結果を可視化した画像を作る(クロップ範囲・中心点・半径円・座標テキスト)"""
    out = img.copy()
    x, y = result["center"]
    r = result["radius"]

    # クロップ範囲(あれば青枠で表示)
    if "crop_box" in result:
        x0, y0, x1, y1 = result["crop_box"]
        cv2.rectangle(out, (x0, y0), (x1, y1), (255, 128, 0), 2)

    # 検出した円周(緑)
    cv2.circle(out, (x, y), r, (0, 255, 0), 3)
    # 中心点(赤い十字+丸)
    cv2.circle(out, (x, y), 8, (0, 0, 255), -1)
    cv2.drawMarker(out, (x, y), (0, 0, 255), markerType=cv2.MARKER_CROSS,
                   markerSize=40, thickness=2)

    text_lines = [
        f"center: ({x}, {y})",
        f"radius: {r}px",
        f"diameter: {result['diameter']}px",
    ]
    for i, line in enumerate(text_lines):
        cv2.putText(out, line, (20, 40 + i * 40),
                    cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 0, 0), 5, cv2.LINE_AA)
        cv2.putText(out, line, (20, 40 + i * 40),
                    cv2.FONT_HERSHEY_SIMPLEX, 1.0, (255, 255, 255), 2, cv2.LINE_AA)

    return out


def build_output_path(img_path):
    """
    入力画像パスから、出力画像パスを自動生成する。
    例: photo01.jpg -> photo01_result.jpg
        C:\\data\\photo01.png -> C:\\data\\photo01_result.png
    """
    root, ext = os.path.splitext(img_path)
    if ext == "":
        ext = ".jpg"
    return f"{root}_result{ext}"


def main(img_path):
    out_path = build_output_path(img_path)

    # 全角パス対応(リポジトリ慣習に合わせ、imreadではなくimdecodeを使用)
    img = cv2.imdecode(np.fromfile(img_path, dtype=np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        print(f"画像を読み込めませんでした: {img_path}")
        sys.exit(1)

    result = detect_meter_center_from_raw(img)
    if result is None:
        print("円を検出できませんでした。")
        sys.exit(1)

    print(f"中心座標(元画像上): {result['center']}")
    print(f"半径: {result['radius']}px / 直径: {result['diameter']}px")
    print(f"クロップ範囲: {result['crop_box']}")
    print(f"検出時のparam2: {result['param2']}")
    print(f"選択方式: {result['selection_mode']}")

    out_img = draw_result(img, result)
    # 全角パス対応の書き出し(imwriteの代わりにimencode + tofile)
    ext = os.path.splitext(out_path)[1]
    success, buf = cv2.imencode(ext, out_img)
    if success:
        buf.tofile(out_path)
        print(f"検出結果画像を出力しました: {out_path}")
    else:
        print("検出結果画像の書き出しに失敗しました。")
        sys.exit(1)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("使い方: python3 detect_meter_center_v2.py 入力画像.jpg")
        sys.exit(1)
    main(sys.argv[1])
