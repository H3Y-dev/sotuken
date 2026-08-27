import csv  # CSVファイルを読み書きするための標準ライブラリを呼び出す

def filter_readings(readings, device_name=None, start_date=None, end_date=None):
    """記録のリストを機器名・日付の範囲で絞り込む。

    指定しなかった条件は絞り込まない（Noneのままなら全件通す）。
    """
    result = readings

    # 1. 機器名が指定されていれば絞り込む
    if device_name is not None:
        result = [r for r in result if r.device_name == device_name]

    # 2. 開始日が指定されていれば、それ以降のデータを残す
    if start_date is not None:
        result = [r for r in result if r.timestamp >= start_date]

    # 3. 終了日が指定されていれば、それ以前のデータを残す
    if end_date is not None:
        result = [r for r in result if r.timestamp <= end_date]

    return result
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