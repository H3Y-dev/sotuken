import cv2
import pytesseract
import numpy as np
import re

pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'


def preprocess(img):
    """
    画像の前処理を行い、OCRしやすい二値画像を返す。
    """
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    # ★【改善1: CLAHE】明るさのムラを補正してコントラストを均等化する
    # メーター画像は中心が明るく周辺が暗い場合が多い。
    # 大域的な二値化だと暗い部分の文字が消えてしまうが、CLAHEで局所的に補正することで防げる。
    # clipLimit: コントラスト強化の上限（2.0が標準。大きいとノイズも強調される）
    # tileGridSize: 局所補正する領域のサイズ（8x8ピクセル単位）
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    gray = clahe.apply(gray)

    # ★【改善2: ガウシアンブラー】二値化の前にノイズを除去する
    # 細かいノイズを二値化する前に平滑化することで、不要な輪郭が生まれにくくなる。
    # (3, 3) は小さめのカーネル。ノイズが多い場合は (5, 5) に変えてみる。
    blurred = cv2.GaussianBlur(gray, (3, 3), 0)

    # 大津の二値化（自動でしきい値を決める）
    _, thresh = cv2.threshold(blurred, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

    return thresh


def rotate_crop(crop, angle):
    """
    画像を指定した角度だけ回転させる。
    回転後に端が切れないよう、画像サイズを自動で広げる。

    angle: 回転角度（度）。正の値 = 反時計回り
    """
    h, w = crop.shape[:2]
    cx, cy = w / 2, h / 2

    # 回転後に必要な画像サイズを計算（三角関数で求める）
    angle_rad = np.radians(angle)
    new_w = int(abs(w * np.cos(angle_rad)) + abs(h * np.sin(angle_rad)))
    new_h = int(abs(w * np.sin(angle_rad)) + abs(h * np.cos(angle_rad)))

    # 回転行列を作成し、中心がずれないよう平行移動を加える
    M = cv2.getRotationMatrix2D((cx, cy), angle, 1.0)
    M[0, 2] += (new_w - w) / 2
    M[1, 2] += (new_h - h) / 2

    return cv2.warpAffine(crop, M, (new_w, new_h),
                          flags=cv2.INTER_CUBIC,
                          borderMode=cv2.BORDER_REPLICATE)


def draw_debug_contours(img, contours):
    """
    検出した全輪郭を色分けして描画し、デバッグ画像として保存・表示する。

    色の意味:
      緑 : サイズフィルターとアスペクト比フィルターを両方通過（OCR対象）
      赤 : サイズフィルターで弾かれた（小さすぎ・大きすぎ）
      黄 : サイズは通ったがアスペクト比フィルターで弾かれた
    """
    debug_img = img.copy()

    print("\n===== デバッグ: 全輪郭一覧 =====")
    print(f"{'No':>3}  {'x':>4} {'y':>4}  {'w':>4} {'h':>4}  {'比率':>5}  判定")
    print("-" * 50)

    for i, cnt in enumerate(contours):
        x, y, w, h = cv2.boundingRect(cnt)
        aspect_ratio = w / h

        # フィルター判定（main() と同じ条件）
        if w < 40 or h < 35 or w > 200 or h > 100:
            color = (0, 0, 255)       # 赤：サイズで除外
            label = f"NG-size w={w},h={h}"
            reason = "サイズNG"
        elif aspect_ratio > 5.0 or aspect_ratio < 0.2:
            color = (0, 255, 255)     # 黄：アスペクト比で除外
            label = f"NG-ratio {aspect_ratio:.1f}"
            reason = f"比率NG({aspect_ratio:.1f})"
        else:
            color = (0, 255, 0)       # 緑：OCR対象
            label = f"OK w={w},h={h}"
            reason = "OCR対象"

        print(f"{i:>3}  {x:>4} {y:>4}  {w:>4} {h:>4}  {aspect_ratio:>5.1f}  {reason}")

        # 矩形を描画（太さ2）
        cv2.rectangle(debug_img, (x, y), (x + w, y + h), color, 2)

        # ラベルを矩形の上に表示
        # 画面上端にはみ出さないよう、y座標が小さい場合は矩形の下に出す
        label_y = y - 5 if y > 20 else y + h + 15
        cv2.putText(debug_img, label, (x, label_y),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.45, color, 1)

    print("=================================\n")

    # 凡例を左上に追加
    legend_items = [
        ((0, 255, 0),   "OK: OCR対象"),
        ((0, 0, 255),   "NG: サイズ外"),
        ((0, 255, 255), "NG: 縦横比"),
    ]
    for idx, (c, text) in enumerate(legend_items):
        ly = 20 + idx * 22
        cv2.rectangle(debug_img, (5, ly - 12), (18, ly + 2), c, -1)
        cv2.putText(debug_img, text, (22, ly), cv2.FONT_HERSHEY_SIMPLEX, 0.55, c, 1)

    cv2.imshow("Debug: 全輪郭（緑=OK, 赤=サイズNG, 黄=比率NG）", debug_img)
    cv2.imwrite("debug_contours.jpg", debug_img)
    print("デバッグ画像を debug_contours.jpg に保存しました。")

    return debug_img


def main():
    img = cv2.imread("meter1.jpg")
    if img is None:
        print("画像が見つかりません。")
        return

    output_img = img.copy()
    img_h, img_w = img.shape[:2]

    # ★【追加】メーター中心座標（円形メーターは画像中心に近似）
    # もし認識がズレる場合は、実際のメーター中心ピクセル座標に手動で修正する
    meter_cx = img_w // 2
    meter_cy = img_h // 2

    # 前処理（改善1・2が適用される）
    thresh = preprocess(img)
    cv2.imshow("Step1: 二値化後", thresh)

    # 文字を太らせて繋げる（膨張処理）
    kernel_size = 5
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (kernel_size, kernel_size))
    dilated = cv2.dilate(thresh, kernel, iterations=1)

    # ★【改善3: モルフォロジークロージング】膨張後の小さな穴や隙間を埋める
    # 膨張だけだと輪郭の内側に小さな穴が残ることがある。
    # クロージング（膨張→収縮）を行うと、穴が塞がってより「塊」がはっきりする。
    # 小さめのカーネルを使って、文字同士が意図せず合体しないようにする。
    small_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
    closed = cv2.morphologyEx(dilated, cv2.MORPH_CLOSE, small_kernel)
    cv2.imshow("Step2: 膨張+クロージング後", closed)

    # 輪郭を検出（closedを使う）
    contours, _ = cv2.findContours(closed, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    # ★【デバッグ】全輪郭を色分けして描画・保存する
    draw_debug_contours(img, contours)

    print("--- OCR処理（フィルター通過分のみ）---")

    # OCRで認識した数値を (数値, x, y, w, h) の形で蓄積し、後で最大値を特定する
    ocr_results = []

    for cnt in contours:
        x, y, w, h = cv2.boundingRect(cnt)

        # サイズフィルター（元と同じ）
        if w < 40 or h < 35:
            continue
        if w > 200 or h > 100:
            continue

        # ★【改善4: アスペクト比フィルター】数字らしい縦横比かチェックする
        # 数字の縦横比（幅÷高さ）は通常 0.3〜4.0 程度。
        # それを大きく外れるもの（極端に横長・縦長）は文字ではなく線やノイズの可能性が高い。
        aspect_ratio = w / h
        if aspect_ratio > 5.0 or aspect_ratio < 0.2:
            continue

        # ★【追加】円形メーターの傾き補正
        # 目盛りの数字は円周上に並ぶため、位置によって回転している。
        # 例：右側（3時方向）の「120」「130」は約90°傾いている。
        #
        # 考え方：
        #   - 輪郭の中心とメーター中心の角度（極角）を計算する
        #   - 12時方向（極角90°）の文字は傾き0°（そのまま読める）
        #   - 3時方向（極角0°）の文字は時計回りに90°傾いているので、
        #     -90°回転させると正立する
        #   - 補正角度 = 90° - 極角  という式で統一的に計算できる
        cnt_cx = x + w // 2
        cnt_cy = y + h // 2
        dx = cnt_cx - meter_cx
        dy = meter_cy - cnt_cy   # 画像のy軸は下向きなので反転する
        polar_angle = np.degrees(np.arctan2(dy, dx))  # -180〜180 の範囲
        text_correction = 90.0 - polar_angle

        print(f"塊を発見 -> 座標:({x}, {y}) w={w} h={h} 極角={polar_angle:.1f}° 補正={text_correction:.1f}°")

        # 切り出しマージン
        margin = 10
        ymin = max(0, y - margin)
        ymax = min(img_h, y + h + margin)
        xmin = max(0, x - margin)
        xmax = min(img_w, x + w + margin)

        cropped = thresh[ymin:ymax, xmin:xmax]

        # ★【追加】傾き補正：位置から計算した角度で回転させる
        corrected = rotate_crop(cropped, text_correction)

        # ★【改善5: 画像を2倍に拡大してからOCRにかける】
        # Tesseractは文字が小さいと誤認識しやすい（推奨は文字高さ30px以上）。
        # 2倍に拡大するだけで認識率が大幅に向上することが多い。
        # INTER_CUBIC は拡大時に画質を保ちやすい補間方式。
        scale = 2.0
        cropped_resized = cv2.resize(corrected, None, fx=scale, fy=scale,
                                     interpolation=cv2.INTER_CUBIC)

        # ★【改善6: --oem 1 で LSTM エンジンを明示的に使う】
        # whitelist は数字のみ（温度計の目盛りは数字だけ）
        custom_config = r'--oem 1 --psm 7 -c tessedit_char_whitelist=0123456789'
        text_raw = pytesseract.image_to_string(cropped_resized, config=custom_config).strip()

        # ★【改善7: 正規表現で数字以外を除去する】
        text = re.sub(r'[^0-9]', '', text_raw)

        if text:
            print(f"  └ 【OCR成功】: {text}  (元テキスト: '{text_raw}')")
            ocr_results.append((int(text), x, y, w, h))
            cv2.rectangle(output_img, (x, y), (x + w, y + h), (0, 255, 0), 2)
            cv2.putText(output_img, text, (x, y - 5),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2)

    # ★【追加】認識した数値の中から最大値を特定して青枠で強調表示する
    if ocr_results:
        max_val, mx, my, mw, mh = max(ocr_results, key=lambda r: r[0])
        print(f"\n★ 最大値: {max_val}")
        cv2.rectangle(output_img, (mx, my), (mx + mw, my + mh), (255, 0, 0), 3)
        cv2.putText(output_img, f"MAX:{max_val}", (mx, my - 5),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 0, 0), 2)
    else:
        print("\n数値を認識できませんでした。")

    cv2.imshow("Step3: OCR結果", output_img)
    cv2.waitKey(0)
    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
