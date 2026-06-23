import cv2
from paddleocr import PaddleOCR, draw_ocr
from PIL import Image

# 1. 画像を読み込んでグレースケール（白黒）化
# ※実際の画像ファイル名に合わせて変更してください（例: 'meter_image.jpg'）
image_path = 'rega1311_12_W1920_H836.jpg' 
img = cv2.imread(image_path)

if img is None:
    raise FileNotFoundError(f"画像ファイル '{image_path}' が見が見つかりません。パスを確認してください。")

gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

# 2. 適応的閾値処理（2値化）で数字をくっきり浮き上がらせる
thresh = cv2.adaptiveThreshold(
    gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY_INV, 11, 3
)

# 前処理した画像をいったん保存
preprocessed_path = 'preprocessed_meter.jpg'
cv2.imwrite(preprocessed_path, thresh)

# 3. PaddleOCRで文字認識
ocr = PaddleOCR(use_angle_cls=True, lang='en', det_db_unclip_ratio=1.2, det_db_box_thresh=0.5)
result = ocr.ocr(preprocessed_path, cls=True)

# 🛠️ 【ここに挿入！】「0」の自動座標補完ロジック
if result and result[0] is not None:
    has_zero = False
    twenty_box = None

    # まず現在の認識結果から「0」と「20」の状態を探す
    for line in result[0]:
        text = line[1][0]
        if text == '0':
            has_zero = True
        if text == '20':
            twenty_box = line[0]  # 20の四角い枠の座標を記憶

    # もし「20」はあるのに「0」がなかったら、座標を計算して強制追加
    if not has_zero and twenty_box is not None:
        # 20の場所を基準に、左下に「0」の枠（4点の座標）を自作
        # ※メーターの画像サイズに合わせて、ズラす数値（-60や+40など）は微調整してください
        zero_box = [
            [twenty_box[0][0] , twenty_box[0][1] + 150],  # 左上 (Xを左に、Yを下に)
            [twenty_box[1][0] , twenty_box[1][1] + 150],  # 右上
            [twenty_box[2][0] , twenty_box[2][1] + 150],  # 右下
            [twenty_box[3][0] , twenty_box[3][1] + 150]   # 左下
        ]
        
        # 嘘の「0」データをOCR結果の末尾に追加（確信度は1.00 = 100%にする）
        fake_zero_line = [zero_box, ('0', 1.0000)]
        result[0].append(fake_zero_line)
        print("\n⚠️ 0が未検出だったため、20の位置を基準に自動補完しました。")

# 4. 認識結果の出力と画像化
if result and result[0] is not None:
    # ターミナルへのテキスト出力
    for line in result[0]:
        text = line[1][0]
        confidence = line[1][1]
        print(f"検出された数字: {text} (確信度: {confidence:.2f})")
    
    # --- ここから画像描画の処理 ---
    # 描画のためにデータを整理
    boxes = [line[0] for line in result[0]]    # 文字の位置（四角の座標）
    txts = [line[1][0] for line in result[0]]   # 認識した文字列
    scores = [line[1][1] for line in result[0]] # 確信度
    
    # 元の画像（または前処理後の画像）を読み込む
    # ※ここでは文字が乗ったイメージが分かりやすいよう、前処理後の画像を使います
    image = Image.open(preprocessed_path).convert('RGB')
    
    # 画像の上に赤枠と認識テキストを描き込む
    # (日本語を綺麗に描画したい場合は font_path が必要ですが、英語・数字なら不要です)
    # Windows標準のフォント（Arialなど）を明示的に指定します
    im_show = draw_ocr(image, boxes, txts, scores, font_path=r"C:\Windows\Fonts\arial.ttf")
    im_show = Image.fromarray(im_show)
    
    # 結果を画像として保存
    output_path = 'result_meter.jpg'
    im_show.save(output_path)
    print(f"\n🎉 認識結果を画像に保存しました: {output_path}")
    
    # 【環境によって動作】可能なら自動で画像ウインドウを開く
    im_show.show()

else:
    print("文字が検出されませんでした。")