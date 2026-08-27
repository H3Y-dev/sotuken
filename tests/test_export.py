import csv  # CSVファイルを読み込むための道具
import os  # ファイルのパスを操作するための道具
import tempfile  # テスト用の「一時的なファイル」を作るための道具
import unittest  # テストを自動化するためのPython標準ライブラリ

from manager.export import export_to_csv  # KPくんが作った関数を呼び出す


# テスト用の偽データ（ダミー）の型を定義
class DummyReading:

    def __init__(self, id, timestamp, device_name, value, stage, image_path):
        self.id = id
        self.timestamp = timestamp
        self.device_name = device_name
        self.value = value
        self.stage = stage
        self.image_path = image_path


# テストケースの本体
class TestExportToCsv(unittest.TestCase):

    def test_writes_header_and_rows(self):
        # 1. テスト用のダミーデータを1件用意する
        readings = [
            DummyReading(
                1, "2026-08-27", "meter1", 42.0, "ok", "img1.jpg"
            )
        ]

        # 2. 自動で消える一時フォルダを作成して、その中に出力ファイル名をセットする
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "out.csv")

            # 3. KPくんが作った export_to_csv を実行！
            export_to_csv(readings, path)

            # 4. 書き出されたCSVを読み直して内容を確認する
            with open(path, encoding="utf-8-sig") as f:
                rows = list(csv.reader(f))

        # 5. 検証: 1行目（ヘッダー）が正しく書かれているかチェック！
        self.assertEqual(
            rows[0],
            ["ID", "日時", "機器名", "値", "ステージ", "画像パス"],
        )
        # 6. 検証: 2行目のIDが「1」になっているかチェック！
        self.assertEqual(rows[1][0], "1")

    def test_empty_list_writes_header_only(self):
        # 1. 自動で消える一時フォルダ内にファイル名をセット
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "out.csv")

            # 2. 空のリスト [] を渡して関数を実行！
            export_to_csv([], path)

            # 3. 書き出されたCSVを読み直す
            with open(path, encoding="utf-8-sig") as f:
                rows = list(csv.reader(f))

        # 4. 検証: 行数が「1行（ヘッダーのみ）」になっているかチェック！
        self.assertEqual(len(rows), 1)


if __name__ == "__main__":
    unittest.main()