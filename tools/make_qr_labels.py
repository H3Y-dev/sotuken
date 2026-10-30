"""機器一覧CSVからQR機器ラベルPDFを生成するCLIツール。

使い方:
    python tools/make_qr_labels.py <機器一覧CSV> [-o 出力PDF]

仕様:
    - 入力はCSVファイル（UTF-8、BOM対応）。
    - 1列目=機器ID、2列目=機器名。
    - ヘッダー行「機器ID,機器名」があれば自動でスキップする。
    - 機器IDの重複があれば行番号を出力して処理を中止する（機器名の重複は許容）。
    - 不正な行（列数不足、不正なID/名前など）は該当の行番号を出力して処理を中止する。
    - 出力の既定は一覧ファイルと同じフォルダの「機器ラベル.pdf」。
"""

from __future__ import annotations

import argparse
import csv
from pathlib import Path
import sys

# プロジェクトルートをインポートパスに追加
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from manager.qr_label import build_payload, make_label_sheet


def load_devices(file_path: Path) -> list[tuple[str, str]]:
    """CSVファイルから (機器ID, 機器名) のリストを読み込み、検証を行う。

    Parameters
    ----------
    file_path : Path
        入力CSVファイルのパス。

    Returns
    -------
    list[tuple[str, str]]
        (機器ID, 機器名) のリスト。

    Raises
    ------
    FileNotFoundError
        入力ファイルが存在しない場合。
    ValueError
        不正な行やID重複が含まれている場合（行番号を含むエラーメッセージ）。
    """
    if not file_path.exists():
        raise FileNotFoundError(f"入力ファイルが見つかりません: {file_path}")

    devices: list[tuple[str, str]] = []
    seen_ids: set[str] = set()

    with open(file_path, mode="r", encoding="utf-8-sig", newline="") as f:
        reader = csv.reader(f)
        first_row = True
        for line_no, row in enumerate(reader, start=1):
            if not row or not any(cell.strip() for cell in row):
                continue  # 空行をスキップ

            # ヘッダー行判定（1行目の 機器ID, 機器名）
            if first_row:
                first_row = False
                col0 = row[0].strip() if len(row) > 0 else ""
                col1 = row[1].strip() if len(row) > 1 else ""
                if col0 == "機器ID" and col1 == "機器名":
                    continue

            # 列数検証（最低2列必要）
            if len(row) < 2:
                raise ValueError(
                    f"{line_no}行目の形式が不正です（機器IDと機器名の2列が必要です）"
                )

            device_id = row[0].strip()
            device_name = row[1].strip()

            # ID・名前の検証（build_payload で仕様検証）
            try:
                build_payload(device_id, device_name)
            except ValueError as e:
                raise ValueError(
                    f"{line_no}行目（ID='{device_id}', 名前='{device_name}'）が不正です: {e}"
                ) from e

            # ID重複検証（中止）
            if device_id in seen_ids:
                raise ValueError(
                    f"{line_no}行目の機器ID '{device_id}' が重複しています"
                )

            seen_ids.add(device_id)
            devices.append((device_id, device_name))

    return devices


# 旧コードや一部呼び出しの互換性用エイリアス
load_device_names = load_devices


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="機器一覧CSVからA4印刷用QR機器ラベルPDFを生成します。"
    )
    parser.add_argument("input_file", type=str, help="機器一覧CSVファイル")
    parser.add_argument(
        "-o",
        "--output",
        type=str,
        default=None,
        help="出力PDFパス（省略時は一覧と同じフォルダの機器ラベル.pdf）",
    )

    args = parser.parse_args(argv)
    input_path = Path(args.input_file)

    try:
        devices = load_devices(input_path)
    except FileNotFoundError as e:
        print(f"エラー: {e}", file=sys.stderr)
        return 1
    except ValueError as e:
        print(f"エラー: {e}", file=sys.stderr)
        return 1

    if not devices:
        print("エラー: 有効な機器データが1件もありませんでした。", file=sys.stderr)
        return 1

    if args.output:
        out_path = Path(args.output)
    else:
        out_path = input_path.resolve().parent / "機器ラベル.pdf"

    try:
        make_label_sheet(devices, out_path)
    except Exception as e:
        print(f"エラー: ラベルシートの生成に失敗しました: {e}", file=sys.stderr)
        return 1

    print(f"{len(devices)}台の機器ラベルを生成しました: {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
