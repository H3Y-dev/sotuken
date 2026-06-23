import cv2
import pytesseract

pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'

def main():
    img = cv2.imread("meter1.jpg")
    if img is None:
        print("画像が見つかりません。")
        return

    output_img = img.copy()

   # 2. 前処理（大津の二値化）
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    _, thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

    # ★【新規追加】文字を「太らせて」繋げる処理
    # (これにより、1文字ずつの泣き別れを防ぎ、ノイズを統合します)
    kernel_size = 5 # 繋げる強さ。1文字泣き別れが多い場合は大きくします
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (kernel_size, kernel_size))
    
    # 膨張処理 (一度白を太らせる)
    dilated = cv2.dilate(thresh, kernel, iterations=1)
    # 【チェック用】文字が繋がっているか確認
    cv2.imshow("Check Dilation Image", dilated)

    # 3. 輪郭（文字の塊）を見つける
    # ★【変更】thresh ではなく、繋げたあとの dilated を渡します
    contours, _ = cv2.findContours(dilated, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    print("--- 各塊のサイズチェック ---")
    for cnt in contours:
        x, y, w, h = cv2.boundingRect(cnt)
        
        # ★【超重要】メーターの数字（横長）に合わせたサイズフィルター
        # 1文字だけの縦線（幅が狭すぎるもの）や、右下の巨大なノイズ（幅・高さが大きすぎるもの）を完全に弾きます
        if w < 40 or h < 35:   # 縦線や小さすぎるゴミを無視
            continue
        if w > 200 or h > 100: # 画面全体や大きすぎるノイズを無視
            continue
            
        print(f"塊を発見 -> 座標:({x}, {y}) 幅(w):{w}, 高さ(h):{h}")
        
        # 切り出しマージン（Tesseractが認識しやすい適度な広さ）
        margin = 10
        ymin = max(0, y - margin)
        ymax = min(img.shape[0], y + h + margin)
        xmin = max(0, x - margin)
        xmax = min(img.shape[1], x + w + margin)
        
        cropped = thresh[ymin:ymax, xmin:xmax]

        # ★ 傾き補正ではなく、Tesseractのモードを「--psm 7（単一のテキスト行）」に変更
        # これにより、多少傾いていても「1行の文字列」として文字の並びを正しく認識してくれます
        custom_config = r'--psm 7 -c tessedit_char_whitelist=0123456789km/h'
        text = pytesseract.image_to_string(cropped, config=custom_config).strip()
        
        # 誤認識でよくある「/」などの記号単体や、1文字のゴミは無視する
        if text and text not in ['/', 'l', 'I', '|']:
            print(f"  └ 【OCR成功】: {text}")
            # 描画
            cv2.rectangle(output_img, (x, y), (x + w, y + h), (0, 255, 0), 2)
            cv2.putText(output_img, text, (x, y - 5), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2)

    # 6. 結果を表示
    cv2.imshow("Advanced OCR Result", output_img)
    cv2.waitKey(0)
    cv2.destroyAllWindows()

if __name__ == "__main__":
    main()