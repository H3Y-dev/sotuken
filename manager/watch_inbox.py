"""
フォルダ監視（SR-03）の手動検証用スクリプト。
指定フォルダ（デフォルト: incoming/）を監視し、新規画像が配置されたことを検出して記録を表示します。
Ctrl+C で終了します。
"""
import argparse
import os
import sys
import time

# ルートディレクトリをパスに追加
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from manager.watcher import FolderWatcher


def main():
    parser = argparse.ArgumentParser(description="SR-03 フォルダ監視・新規画像検出スクリプト")
    parser.add_argument(
        "--watch-dir",
        default=os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "incoming"),
        help="監視対象ディレクトリ（デフォルト: リポジトリ直下の incoming/）",
    )
    args = parser.parse_args()

    watch_dir = os.path.abspath(args.watch_dir)
    os.makedirs(watch_dir, exist_ok=True)

    print(f"[SR-03 Watcher] 監視フォルダ: {watch_dir}")
    print("[SR-03 Watcher] 画像ファイル (.jpg, .jpeg, .png) を監視フォルダに配置してください。")
    print("[SR-03 Watcher] 停止するには Ctrl+C を押してください。")

    detected_count = 0

    def on_detected(img_path: str):
        nonlocal detected_count
        detected_count += 1
        print(f"[SR-03 DETECTED #{detected_count}] 新規画像を検出しました: {img_path}")

    watcher = FolderWatcher(watch_dir=watch_dir, on_image_detected=on_detected)

    # 起動時に既存ファイルをチェック
    initial_images = watcher.scan_existing()
    if initial_images:
        print(f"[SR-03 Watcher] 既存の画像を {len(initial_images)} 件検出しました。")

    watcher.start()
    try:
        while True:
            time.sleep(0.5)
    except KeyboardInterrupt:
        print("\n[SR-03 Watcher] 監視を停止しています...")
    finally:
        watcher.stop()
        print(f"[SR-03 Watcher] 終了しました。検出画像総数: {len(watcher.detected_images)} 件")


if __name__ == "__main__":
    main()
