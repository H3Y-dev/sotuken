"""
フォルダ監視および既存meter_pipeline呼び出し（SR-03/SR-04/SR-05）の手動検証用スクリプト。
指定フォルダ（デフォルト: incoming/）を監視し、新規画像およびサイドカーJSONを検出して
既存の meter_pipeline を自動実行し、戻り値（成功/失敗結果）を記録・表示します。
Ctrl+C で終了します。
"""
import argparse
import os
import sys
import time
from typing import Any, Dict, Optional

# ルートディレクトリをパスに追加
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from manager.watcher import FolderWatcher
from manager.sidecar import SidecarMetadata


def main():
    parser = argparse.ArgumentParser(description="SR-05 フォルダ監視・meter_pipeline呼び出しスクリプト")
    parser.add_argument(
        "--watch-dir",
        default=os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "incoming"),
        help="監視対象ディレクトリ（デフォルト: リポジトリ直下の incoming/）",
    )
    parser.add_argument(
        "--use-vlm",
        action="store_true",
        help="VLM（Ollama）を使用する場合は指定（デフォルトはFalse）",
    )
    args = parser.parse_args()

    watch_dir = os.path.abspath(args.watch_dir)
    os.makedirs(watch_dir, exist_ok=True)

    print(f"[SR-05 Watcher] 監視フォルダ: {watch_dir}")
    print("[SR-05 Watcher] 画像ファイルを配置すると、meter_pipeline が自動実行されます。")
    print("[SR-05 Watcher] 停止するには Ctrl+C を押してください。")

    detected_count = 0

    def on_pipeline_result(img_path: str, sidecar: Optional[SidecarMetadata], result: Dict[str, Any]):
        nonlocal detected_count
        detected_count += 1
        print(f"[SR-05 DETECTED #{detected_count}] 新規画像を検出: {img_path}")
        if sidecar:
            print(f"  [メタデータ] 機器名: {sidecar.device_name}, 真値: {sidecar.operator_value}, メモ: {sidecar.operator_note}")
        else:
            print("  [メタデータ] なし（サイドカーJSON未配置）")

        stage = result.get("stage")
        val = result.get("value")
        err = result.get("error")

        if stage == "ok":
            print(f"  [パイプライン成功] stage: {stage}, 読み取り値: {val}, 針角度: {result.get('angle_deg')}")
        else:
            print(f"  [パイプライン失敗] stage: {stage}, エラー情報: {err}")

    watcher = FolderWatcher(
        watch_dir=watch_dir,
        on_pipeline_result=on_pipeline_result,
        auto_run_pipeline=True,
        use_vlm=args.use_vlm,
    )

    initial_images = watcher.scan_existing()
    if initial_images:
        print(f"[SR-05 Watcher] 既存の画像を {len(initial_images)} 件検出・処理しました。")

    watcher.start()
    try:
        while True:
            time.sleep(0.5)
    except KeyboardInterrupt:
        print("\n[SR-05 Watcher] 監視を停止しています...")
    finally:
        watcher.stop()
        print(f"[SR-05 Watcher] 終了しました。検出画像総数: {len(watcher.detected_images)} 件")


if __name__ == "__main__":
    main()
