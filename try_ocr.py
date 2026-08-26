import cv2
import numpy as np
import os
import glob
import scale_value_detect
import orientation

# リポジトリのルートフォルダ（このスクリプトがある場所）を自動取得
REPO = os.path.dirname(os.path.abspath(__file__))

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
        print(f"[NG] 画像読み込み失敗: {filename}")
        return

    h, w, _ = img.shape
    # ノイズ削減のため中央部をクロップ（元の座標計算用に切断位置を保持）
    crop_y1, crop_y2 = int(h*0.2), int(h*0.8)
    crop_x1, crop_x2 = int(w*0.2), int(w*0.8)
    crop_img = img[crop_y1:crop_y2, crop_x1:crop_x2]

    # orientation.py から (直した画像, 角度, 採用時の個数, 0度の個数) を受け取る
    fixed_crop_img, angle, count, zero_count = orientation.normalize_orientation(crop_img)
    
    # 差分を計算
    diff = count - zero_count
    diff_str = f"(+{diff})" if diff > 0 else f"({diff})"

    # 結果ログの表示（絵文字を使わない安全な表記）
    print("\n" + "="*50)
    print(f"[結果] {filename} : 0度 {zero_count}個 -> {angle}度 {count}個 に採用 {diff_str}")
    
    # 直した画像から数字の座標等を取得
    best_results = scale_value_detect.read_scale_numbers(fixed_crop_img)

    # 描画用の画像を作成
    vis_img = img.copy()

    if best_results:
        vals = [item['value'] for item in best_results]
        print(f"[数値] : {vals}")
        
        for r in best_results:
            # クロップ位置からの絶対座標を計算
            cx = int(r['x'] + crop_x1)
            cy = int(r['y'] + crop_y1)
            val = r['value']
            
            # 画像上に赤丸とテキストを描画
            cv2.circle(vis_img, (cx, cy), 8, (0, 0, 255), -1)
            cv2.putText(vis_img, f"{val}", (cx + 10, cy + 5),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 255), 2)

        # 結果画像の保存（相対パスを使用）
        save_dir = os.path.join(REPO, "meter_data")
        os.makedirs(save_dir, exist_ok=True)
        save_path = os.path.join(save_dir, f"result_{filename}")
        imwrite_ja(save_path, vis_img)
        print(f"[保存] 確認用画像を保存しました: result_{filename}")
    else:
        print("[警告] 目盛り数字が検出できませんでした")
    print("="*50)

def main():
    # 相対パスを使用して meter_data フォルダを指定
    target_dir = os.path.join(REPO, "meter_data")
    extensions = ["*.png", "*.jpg", "*.jpeg", "*.PNG", "*.JPG", "*.JPEG"]
    
    image_paths = []
    if os.path.exists(target_dir):
        for ext in extensions:
            if "result_" not in ext:
                for p in glob.glob(os.path.join(target_dir, "**", ext), recursive=True):
                    if "result_" not in os.path.basename(p):
                        image_paths.append(p)

    print("=== meter_data フォルダ内の自動テストを開始します ===")
    
    if not image_paths:
        print(f"[警告] {target_dir} に対象の画像ファイルがありません。")
        return

    for path in image_paths:
        process_meter_image(path)

if __name__ == "__main__":
    main()