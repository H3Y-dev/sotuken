"""Fixed inspection membership, per-device results and audit history."""

import hashlib
import json
from contextlib import ExitStack
from datetime import date, datetime, time, timezone
from pathlib import Path

from manager.devices import list_devices
from manager.export import _reading_time, write_report_csv
from manager.record import judge_input_method


RESULT_COLUMNS = ['点検ID', '機器番号', '機器名', '単位', '測定値', '読取状態',
                  '要確認理由', '撮影日時', '測定方法', '現場入力値', '備考', '画像参照']
HISTORY_COLUMNS = ['記録ID', '撮影日時', '取込日時', *RESULT_COLUMNS[1:7],
                   *RESULT_COLUMNS[8:]]


def _device_key(row):
    return row.device_id or 'name:' + (row.device_name or '')


def _validate_inspection_id(inspection_id):
    if (not isinstance(inspection_id, str) or not inspection_id or inspection_id.endswith(('.', ' '))
            or any(char in '<>:"/\\|?*' or ord(char) < 32 for char in inspection_id)):
        raise ValueError('Invalid inspection ID')


def _report(storage, manifest, readings):
    devices = {row['device_id']: row for row in list_devices(storage)}
    truths = {row.image_sha256: vars(row) for row in storage.get_all_image_truths()}
    history = []
    latest = {}
    for reading in sorted(readings, key=lambda row: (_reading_time(row), row.id)):
        device = devices.get(reading.device_id, {})
        truth = truths.get(reading.image_sha256, {})
        raw = reading.raw_data or {}
        name = device.get('device_name') or reading.device_name
        reasons = []
        status = reading.status or ('ok' if reading.stage == 'ok' and reading.value is not None else 'failed')
        if status == 'failed':
            reasons.append('読み取り失敗')
        elif status != 'ok':
            reasons.append('読み取り要確認')
        if not reading.device_id:
            reasons.append('機器番号なし')
        if not name or name == 'unknown':
            reasons.append('名称未設定')
        if reading.device_id_issue:
            reasons.append(reading.device_id_issue)
        bounds = []
        for field, fallback in [('min_value', 'scale_min'), ('max_value', 'scale_max')]:
            value = device.get(field)
            if value is None:
                value = truth.get(fallback)
            if value is None:
                value = raw.get(field)
            bounds.append(value)
        low, high = bounds
        if reading.value is not None and ((low is not None and reading.value < low)
                                         or (high is not None and reading.value > high)):
            reasons.append('範囲外の疑い')
        method = judge_input_method(reading.value, truth.get('operator_value'))
        row = {'点検ID': manifest['inspection_id'], '記録ID': reading.reading_id,
               '機器番号': reading.device_id, '機器名': name, '単位': device.get('unit') or raw.get('unit'),
               '測定値': reading.value, '読取状態': '失敗' if status == 'failed' else '要確認' if reasons else '正常',
               '要確認理由': '；'.join(reasons), '撮影日時': reading.captured_at,
               '取込日時': reading.received_at, '測定方法': {'auto': '自動', 'manual': '手動', 'corrected': '補正'}[method],
               '現場入力値': truth.get('operator_value'), '備考': truth.get('operator_note'),
               '画像参照': reading.image_rel or reading.image_path}
        history.append(row)
        latest[_device_key(reading)] = row
    return {'manifest': manifest, 'rows': [latest[key] for key in sorted(latest)], 'history': history}


def create_inspection(storage, inspection_id, date_from, date_to, device_ids, now=None):
    """Freeze inclusive calendar dates and target IDs (legacy targets use name:)."""
    _validate_inspection_id(inspection_id)
    start, end = date.fromisoformat(str(date_from)), date.fromisoformat(str(date_to))
    if start > end:
        raise ValueError('Inspection start must not follow end')
    targets = sorted(set(device_ids))
    images = {}
    for row in storage.get_all_readings():
        key = row.image_sha256 if row.image_sha256 is not None else 'id:' + str(row.id)
        if key not in images or row.id > images[key].id:
            images[key] = row
    readings = [row for row in images.values() if _device_key(row) in targets
                and datetime.combine(start, time.min) <= _reading_time(row) <= datetime.combine(end, time.max)]
    readings.sort(key=lambda row: row.id)
    manifest = {'inspection_id': inspection_id, 'date_from': start.isoformat(), 'date_to': end.isoformat(),
                'device_ids': targets, 'generated_at': (now or datetime.now(timezone.utc)).isoformat(),
                'readings': [{'reading_id': row.reading_id, 'id': row.id} for row in readings]}
    return _report(storage, manifest, readings)


def restore_inspection(storage, manifest):
    """Rebuild only the recorded IDs; refresh registry names and units."""
    by_id = {row.id: row for row in storage.get_all_readings()}
    readings = []
    for item in manifest['readings']:
        row = by_id.get(item['id'])
        if row is None or row.reading_id != item['reading_id']:
            raise ValueError('Manifest reading is missing or mismatched')
        readings.append(row)
    return _report(storage, dict(manifest), readings)


def export_inspection(inspection, output_dir):
    """Save the result, simultaneous audit history and SHA-256 manifest."""
    manifest = dict(inspection['manifest'])
    # Revalidate IDs before using a restored manifest as a filename.
    inspection_id = manifest['inspection_id']
    _validate_inspection_id(inspection_id)
    manifest['date_from'] = date.fromisoformat(manifest['date_from']).isoformat()
    manifest['date_to'] = date.fromisoformat(manifest['date_to']).isoformat()
    stamp = date.fromisoformat(manifest['date_to']).strftime('%Y%m%d')
    directory = Path(output_dir)
    directory.mkdir(parents=True, exist_ok=True)
    stem = f'点検結果_{stamp}_{inspection_id}'
    paths = {'csv': directory / (stem + '.csv'), 'manifest': directory / (stem + '.manifest.json'),
             'history': directory / f'履歴_{manifest["date_from"]}_{manifest["date_to"]}_{inspection_id}.csv'}
    created = []
    try:
        # Keep exclusive handles until all reports finish; never replace existing files.
        with ExitStack() as stack:
            streams = {}
            for key, path in paths.items():
                streams[key] = stack.enter_context(path.open('x', newline='', encoding='utf-8' if key == 'manifest' else 'utf-8-sig'))
                created.append(path)
            for key, rows, columns in [('csv', inspection['rows'], RESULT_COLUMNS),
                                       ('history', inspection['history'], HISTORY_COLUMNS)]:
                write_report_csv(rows, columns, streams[key])
                streams[key].flush()
            manifest['csv_sha256'] = hashlib.sha256(paths['csv'].read_bytes()).hexdigest()
            json.dump(manifest, streams['manifest'], ensure_ascii=False, indent=2)
    except Exception:
        for path in created:
            path.unlink(missing_ok=True)
        raise
    return {key: str(path) for key, path in paths.items()}
