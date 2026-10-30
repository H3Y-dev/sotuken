"""機器名の一覧ファイルからQR機器ラベルPDFを生成するCLIツール。

使い方:
    python tools/make_qr_labels.py <機器名の一覧ファイル> [-o 出力PDF]

仕様:
    - 一覧は1行1台のテキスト（UTF-8、BOM対応）または1列目が機器名のCSV（拡張子で判断）。
    - CSVのヘッダー行「機器名」があれば自動でスキップする。
    - 空行と重複は除く（重複は警告を出力）。
    - 不正な名前（64文字超、制御文字等）は該当の行番号を出力して中止する。
    - 出力の既定は一覧ファイルと同じフォルダの「機器ラベル.pdf」。
"""

from __future__ import annotations

import argparse
import csv
import os
from pathlib import Path
import sys

# プロジェクトルートをインポートパスに追加
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from manager.qr_label import build_payload, make_label_sheet


def load_device_names(file_path: Path) -> list[str]:
    """ファイルから機器名リストを読み込み、検証・重複除外を行って返す。

    Raises
    ------
    ValueError
        不正な機器名が含まれている場合（行番号を含むエラーメッセージ）。
    FileNotFoundError
        入力ファイルが存在しない場合。
    """
    if not file_path.exists():
        raise FileNotFoundError(f"入力ファイルが見つかりません: {file_path}")

    is_csv = file_path.suffix.lower() == ".csv"
    seen: set[str] = set()
    device_names: list[str] = []

    with open(file_path, mode="r", encoding="utf-8-sig") as f:
        if is_csv:
            reader = csv.reader(f)
            first_row = True
            for line_no, row in enumerate(reader, start=1):
                if not row or not any(cell.strip() for cell in row):
                    continue  # 空行をスキップ

                col0 = row[0].strip()
                if first_row and col0 == "機器名":
                    first_row = False
                    continue  # ヘッダー行をスキップ
                first_row = False

                if not col0:
                    continue  # 1列目が空の場合はスキップ

                # 不正な名前の検証
                try:
                    build_payload(col0)
                except ValueError as e:
                    raise ValueError(f"{line_no}行目の機器名 '{col0}' が不正です: {e}") from e

                if col0 in seen:
                    print(f"警告: {line_no}行目の機器名 '{col0}' は重複しているためスキップします", file=sys.stderr)
                    continue

                seen.add(col0)
                device_names.append(col0)
        else:
            for line_no, line in enumerate(f, start=1):
                stripped = line.strip()
                if not stripped:
                    continue  # 空行をスキップ

                # 不正な名前の検証
                try:
                    build_payload(stripped)
                except ValueError as e:
                    raise ValueError(f"{line_no}行目の機器名 '{stripped}' が不正です: {e}") from e

                if stripped in seen:
                    print(f"警告: {line_no}行目の機器名 '{stripped}' は重複しているためスキップします", file=sys.stderr)
                    continue

                seen.add(stripped)
                device_names.append(stripped)

    return device_names


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="機器名の一覧ファイルからA4印刷用QR機器ラベルPDFを生成します。"
    )
    parser.add_argument("input_file", type=str, help="機器名の一覧ファイル（.txt または .csv）")
    parser.add_argument("-o", "--output", type=str, default=None, help="出力PDFパス（省略時は一覧と同じフォルダの機器ラベル.pdf）")

    args = parser.parse_args(argv)
    input_path = Path(args.input_file)

    try:
        names = load_device_names(input_path)
    except FileNotFoundError as e:
        print(f"エラー: {e}", file=sys.stderr)
        return 1
    except ValueError as e:
        print(f"エラー: {e}", file=sys.stderr)
        return 1

    if not names:
        print("エラー: 有効な機器名が1件もありませんでした。", file=sys.stderr)
        return 1

    if args.output:
        out_path = Path(args.output)
    else:
        out_path = input_path.resolve().parent / "機器ラベル.pdf"

    try:
        make_label_sheet(names, out_path)
    except Exception as e:
        print(f"エラー: ラベルシートの生成に失敗しました: {e}", file=sys.stderr)
        return 1

    print(f"{len(names)}台の機器ラベルを生成しました: {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
