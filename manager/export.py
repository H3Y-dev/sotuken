import csv  # CSVファイルを読み書きするための標準ライブラリを呼び出す


def export_to_csv(readings, output_path):
    """
    記録のリストをCSVファイルに書き出す関数

    readings: MeterReadingのリスト（データが詰まった配列）
    output_path: 書き出すCSVファイルの保存先パス（例: "test_output.csv"）
    """
    with open(output_path, "w", encoding="utf-8-sig", newline="") as f:
        # "utf-8-sig" を指定することで、Excelで開いたときの日本語文字化けを防ぐ
        writer = csv.writer(f)

        # 表の一番上の行（ヘッダー項目名）を書き込む
        writer.writerow(["ID", "日時", "機器名", "値", "ステージ", "画像パス"])

        # データを1件ずつ取り出して、表の1行として書き込む
        for r in readings:
            writer.writerow([r.id, r.timestamp, r.device_name, r.value, r.stage, r.image_path])