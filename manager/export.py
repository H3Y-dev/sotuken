import csv  # CSVファイルを読み書きするための標準ライブラリを呼び出す
import json
from datetime import datetime, time


def filter_readings(readings, device_name=None, date_from=None, date_to=None):
    """記録リストを機器名と日付範囲で絞り込む。"""
    start = datetime.combine(date_from, time.min) if date_from else None
    end = datetime.combine(date_to, time.max) if date_to else None

    result = []
    for reading in readings:
        if device_name not in (None, "すべて") and reading.device_name != device_name:
            continue

        timestamp = datetime.fromisoformat(reading.timestamp)
        if start and timestamp < start:
            continue
        if end and timestamp > end:
            continue
        result.append(reading)
    return result


def _field(reading, *names, **kwargs):
    """新旧どちらのレコード型からも値を取れるようにする。

    確定スキーマ(manager/record.py の Reading)とDB層(manager/storage.py の
    MeterReading)でフィールド名が違う箇所がある（captured_at / timestamp、
    reading_id / id、status / stage）。app.py は DB層の型を渡すため、
    片方の名前だけを直接参照すると AttributeError で画面が落ちる
    （2026-09-13、履歴画面のグラフとCSV出力で実際に発生した）。
    名前を順に試し、最初に見つかった値を返す。
    """
    default = kwargs.get("default")
    for name in names:
        value = reading.get(name) if isinstance(reading, dict) else getattr(reading, name, None)
        if value is not None:
            return value
    return default


def export_to_csv(readings, output_path):
    """記録リストをCSVファイルへ出力する。"""
    with open(output_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        # ヘッダー行（確定スキーマに対応）
        writer.writerow(["reading_id", "captured_at", "device_name", "value", "status", "failure_stage", "image_path"])
        for r in readings:
            writer.writerow([
                _field(r, "reading_id", "id"),
                _field(r, "captured_at", "timestamp"),
                _field(r, "device_name"),
                _field(r, "value"),
                _field(r, "status", "stage"),
                _field(r, "failure_stage"),
                _field(r, "image_path"),
            ])


def export_to_jsonl(readings, output_path):
    """記録リストをJSON Lines（1行1JSON）ファイルへ出力する。"""
    fields = [
        "reading_id", "local_id", "captured_at", "received_at", "processed_at", "device_name",
        "value", "unit", "status", "input_method", "confidence", "image_path", "image_sha256",
        "failure_stage", "failure_code", "failure_detail", "pipeline_version", "log_path", "overlay_path",
    ]
    with open(output_path, "w", encoding="utf-8") as f:
        for r in readings:
            row_dict = {}
            for field in fields:
                if isinstance(r, dict):
                    val = r.get(field, None)
                else:
                    val = getattr(r, field, None)
                row_dict[field] = val
            f.write(json.dumps(row_dict, ensure_ascii=False) + "\n")

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
            series[_field(r, "captured_at", "timestamp")] = r.value
    return series
