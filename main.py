import argparse
import os
import sys

# 1. カレントディレクトリをパスに追加
current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.insert(0, current_dir)

# 2. manager パッケージから MeterManager をインポート
from manager.manager import MeterManager

# 3. read_meter のインポート（未実装時のモック対応）
try:
    from reader import read_meter
except ImportError:
    try:
        from read_meter import read_meter
    except ImportError:

        def read_meter(image_path: str):
            print(f"[INFO] Mock read_meter Executing for: {image_path}")
            return {
                "stage": "ok",
                "value": 42.5,
                "ratio": 0.425,
                "angle_deg": 120.0,
                "error": None,
            }


def main():
    parser = argparse.ArgumentParser(
        description="アナログメーター自動読み取りシステム CLI"
    )
    parser.add_argument(
        "--image", "-i", type=str, help="読み取るメーター画像のパス"
    )
    parser.add_argument(
        "--device",
        "-d",
        type=str,
        default="Default_Device",
        help="メーターの識別名 (例: Pressure_Gauge_01)",
    )
    parser.add_argument(
        "--db",
        type=str,
        default="manager.db",
        help="使用するSQLite DBのファイルパス",
    )
    parser.add_argument(
        "--history", action="store_true", help="全読み取り履歴を表示"
    )
    parser.add_argument(
        "--export-csv",
        type=str,
        nargs="?",
        const="readings_export.csv",
        help="履歴をCSVファイルに出力（パス指定省略時は readings_export.csv）",
    )

    args = parser.parse_args()
    manager = MeterManager(db_path=args.db)

    if args.image:
        if not os.path.exists(args.image) and "Mock" not in str(read_meter):
            print(f"[ERROR] 指定された画像ファイルが存在しません: {args.image}")
            sys.exit(1)

        print(f"--- 画像読み取り開始: {args.image} (Device: {args.device}) ---")
        result = manager.process_image(
            image_path=args.image,
            device_name=args.device,
            reader_func=read_meter,
        )
        reading = result["reading"]

        print("\n【処理結果】")
        print(f"  ID        : {reading.id}")
        print(f"  Timestamp : {reading.timestamp}")
        print(f"  Device    : {reading.device_name}")
        print(f"  Stage     : {result['stage']}")
        print(f"  Value     : {result['val'] if result['val'] is not None else 'N/A'}")

    if args.export_csv:
        csv_path = manager.export_to_csv(args.export_csv)
        print(f"\n[INFO] 履歴データをCSVに出力しました: {csv_path}")

    if args.history or (not args.image and not args.export_csv):
        print("\n【全読み取り履歴】")
        print(manager.format_history_for_cli())


if __name__ == "__main__":
    main()