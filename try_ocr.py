import cv2
import numpy as np
import os
import glob
import scale_value_detect

def imread_ja(path):
    """日本語パス対応の画像読み込み"""
    data = np.fromfile(path, dtype=np.uint8)
    return cv2.imdecode(data, cv2.IMREAD_COLOR)

def imwrite_ja(filename, img):
    """日本語パス対応の画像保存"""
    ext = os.path.splitext(filename)[1]
    result, nparr = cv2.imencode(ext, img)
    if result:
        with open(filename, 'wb') as f:
            f.write(nparr)

def process_meter_image(image_path):
    """1枚の画像に対する処理と結果画像の描画・保存"""
    img = imread_ja(image_path)
    filename = os.path.basename(image_path)
    
    if img is None:
        print(f"❌ 画像読み込み失敗: {filename}")
        return

    h, w, _ = img.shape
    # ノイズ削減のため中央部をクロップ（元の座標計算用に切断位置を保持）
    crop_y1, crop_y2 = int(h*0.2), int(h*0.8)
    crop_x1, crop_x2 = int(w*0.2), int(w*0.8)
    crop_img = img[crop_y1:crop_y2, crop_x1:crop_x2]

    best_angle = 0
    best_results = []

    # 回転判定 (0°, 90°, 180°, 270°)
    angles = [0, 90, 180, 270]
    for angle in angles:
        if angle == 0:
            rotated = crop_img
        elif angle == 90:
            rotated = cv2.rotate(crop_img, cv2.ROTATE_90_CLOCKWISE)
        elif angle == 180:
            rotated = cv2.rotate(crop_img, cv2.ROTATE_180)
        elif angle == 270:
            rotated = cv2.rotate(crop_img, cv2.ROTATE_90_COUNTERCLOCKWISE)

        results = scale_value_detect.read_scale_numbers(rotated)

        if len(results) > len(best_results):
            best_results = results
            best_angle = angle

    # 結果ログの表示
    print("\n" + "="*50)
    print(f"📄 ファイル名    : {filename}")
    print(f"🔄 判定された向き: {best_angle}度")
    print(f"🔢 検出された数字: {len(best_results)}個")
    
    # 描画用の画像を作成
    vis_img = img.copy()

    if best_results:
        vals = [item['value'] for item in best_results]
        print(f"💡 認識された数値: {vals}")
        
        for r in best_results:
            # クロップ位置からの絶対座標を計算
            cx = int(r['x'] + crop_x1)
            cy = int(r['y'] + crop_y1)
            val = r['value']
            
            # 画像上に赤丸とテキストを描画
            cv2.circle(vis_img, (cx, cy), 8, (0, 0, 255), -1)
            cv2.putText(vis_img, f"{val}", (cx + 10, cy + 5),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 255), 2)

        # 結果画像の保存
        save_dir = r"C:\卒研\git_stk\sotuken\meter_data"
        save_path = os.path.join(save_dir, f"result_{filename}")
        imwrite_ja(save_path, vis_img)
        print(f"🖼️ 確認用画像を保存しました: result_{filename}")
    else:
        print("⚠️ 目盛り数字が検出できませんでした")
    print("="*50)

def main():
    target_dir = r"C:\卒研\git_stk\sotuken\meter_data"
    extensions = ["*.png", "*.jpg", "*.jpeg", "*.PNG", "*.JPG", "*.JPEG"]
    
    image_paths = []
    for ext in extensions:
        # 結果画像(result_)は処理対象から除外
        if "result_" not in ext:
            for p in glob.glob(os.path.join(target_dir, "**", ext), recursive=True):
                if "result_" not in os.path.basename(p):
                    image_paths.append(p)

    print("🚀 === meter_data フォルダ内の自動テストを開始します ===")
    
    if not image_paths:
        print(f"⚠️ {target_dir} に対象の画像ファイルがありません。")
        return

    for path in image_paths:
        process_meter_image(path)

if __name__ == "__main__":
    main()