import csv  # CSVファイルを読み書きするための標準ライブラリを呼び出す

def filter_readings(readings, start_date=None, end_date=None, device_name=None):
    """記録リストを指定条件で絞り込む。"""
    result = readings
    if start_date:
        result = [r for r in result if r.captured_at >= start_date]
    if end_date:
        result = [r for r in result if r.captured_at <= end_date]
    if device_name:
        result = [r for r in result if r.device_name == device_name]
    return result
def export_to_csv(readings, output_path):
    """記録リストをCSVファイルへ出力する。"""
    import csv

    with open(output_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        # ヘッダー行（新スキーマに対応）
        writer.writerow(["reading_id", "captured_at", "device_name", "value", "stage", "image_path"])
        for r in readings:
            writer.writerow([r.reading_id, r.captured_at, r.device_name, r.value, r.stage, r.image_path])
def group_by_device(readings):
    """記録のリストを機器名ごとの辞書にまとめる。"""
    groups = {}
    for r in readings:
        groups.setdefault(r.device_name, []).append(r)
    return groups


def readings_to_series(readings):
    """
    1つの機器分の記録リストを受け取り、「撮影日時 -> 値」の辞書を作成する。
    value が None の記録（読み取り失敗）は除外する。
    """
    series = {}
    for r in readings:
        if r.value is not None:
            series[r.captured_at] = r.value
    return series