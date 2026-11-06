"""Saved routes and phone completion manifests; OCR results remain independent."""
import json
import re
import secrets
import os
from functools import lru_cache
from datetime import datetime, timezone

from manager.qr_label import validate_device_id, validate_device_name
from manager.sidecar import normalize_captured_at


def init_tables(conn):
    conn.execute('CREATE TABLE IF NOT EXISTS inspection_routes (route_id TEXT PRIMARY KEY, name TEXT NOT NULL, updated_at TEXT NOT NULL)')
    conn.execute('CREATE TABLE IF NOT EXISTS inspection_route_devices (route_id TEXT NOT NULL, position INTEGER NOT NULL, device_id TEXT NOT NULL, device_name TEXT NOT NULL, PRIMARY KEY(route_id, position))')
    conn.execute('CREATE TABLE IF NOT EXISTS inspections (inspection_id TEXT PRIMARY KEY, inspection_name TEXT, route_id TEXT, operator TEXT, place TEXT, started_at TEXT, completed_at TEXT, manifest_received_at TEXT, manifest_json TEXT NOT NULL)')


def validate_id(value):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9._-]{1,64}', value):
        raise ValueError('IDは英数字・.・_・-の1〜64文字で入力してください')
    return value


def now():
    return datetime.now(timezone.utc).isoformat(timespec='microseconds')


def save_route(storage, name, devices, route_id=None):
    name = validate_device_name(name)
    route_id = validate_id(route_id) if route_id is not None else 'R-' + datetime.now().strftime('%Y%m%d%H%M%S') + '-' + secrets.token_hex(2)
    checked = []
    for device in devices:
        validate_device_id(device['id'])
        checked.append(dict(id=device['id'], name=validate_device_name(device['name'])))
    if len({d['id'] for d in checked}) != len(checked):
        raise ValueError('同じ機器IDを複数登録できません')
    with storage.connection() as conn:
        conn.execute('INSERT INTO inspection_routes VALUES (?, ?, ?) ON CONFLICT(route_id) DO UPDATE SET name=excluded.name, updated_at=excluded.updated_at', (route_id, name, now()))
        conn.execute('DELETE FROM inspection_route_devices WHERE route_id=?', (route_id,))
        conn.executemany('INSERT INTO inspection_route_devices VALUES (?, ?, ?, ?)',
                         [(route_id, i, d['id'], d['name']) for i, d in enumerate(checked)])
    return get_route(storage, route_id)


def get_route(storage, route_id):
    with storage.connection() as conn:
        row = conn.execute('SELECT route_id, name, updated_at FROM inspection_routes WHERE route_id=?', (route_id,)).fetchone()
        if row is None:
            return None
        devices = [dict(id=r[0], name=r[1]) for r in conn.execute('SELECT device_id, device_name FROM inspection_route_devices WHERE route_id=? ORDER BY position', (route_id,))]
    return dict(v=1, route_id=row[0], name=row[1], devices=devices, updated_at=row[2])


def list_routes(storage):
    with storage.connection() as conn:
        rows = conn.execute('SELECT r.route_id, r.name, COUNT(d.position), r.updated_at FROM inspection_routes r LEFT JOIN inspection_route_devices d ON r.route_id=d.route_id GROUP BY r.route_id ORDER BY r.name, r.route_id').fetchall()
    return dict(v=1, routes=[dict(route_id=r[0], name=r[1], count=r[2], updated_at=r[3]) for r in rows])


def delete_route(storage, route_id):
    with storage.connection() as conn:
        conn.execute('DELETE FROM inspection_route_devices WHERE route_id=?', (route_id,))
        conn.execute('DELETE FROM inspection_routes WHERE route_id=?', (route_id,))


def route_qr_payload(route):
    payload = 'SOTUKEN-ROUTE:' + json.dumps(route, ensure_ascii=False, separators=(',', ':'))
    return payload if len(payload.encode('utf-8')) <= 1500 else None


def validate_manifest(inspection_id, data):
    validate_id(inspection_id)
    if not isinstance(data, dict) or type(data.get('v')) is not int or data['v'] != 1 or data.get('inspection_id') != inspection_id:
        raise ValueError('manifestの版または点検IDが不正です')
    validate_device_name(data.get('inspection_name'))
    if data.get('route_id') is not None:
        validate_id(data['route_id'])
    for key in ('operator', 'place'):
        if not isinstance(data.get(key), str) or len(data[key]) > 256 or any(ord(c) < 32 for c in data[key]):
            raise ValueError(key + 'が不正です')
    for key in ('started_at', 'completed_at'):
        if normalize_captured_at(data.get(key)) is None:
            raise ValueError(key + 'が不正です')
    for key in ('missing', 'extra'):
        if not isinstance(data.get(key), list):
            raise ValueError(key + 'は配列です')
        for device_id in data[key]:
            validate_device_id(device_id)
    if not isinstance(data.get('photos'), list):
        raise ValueError('photosは配列です')
    names = set()
    for photo in data['photos']:
        if not isinstance(photo, dict):
            raise ValueError('写真が不正です')
        name = photo.get('file_name')
        if not isinstance(name, str) or not re.fullmatch(r'[A-Za-z0-9._-]{1,255}', name) or name in ('.', '..') or name in names:
            raise ValueError('写真名が不正または重複しています')
        names.add(name)
        if not isinstance(photo.get('sha256'), str) or not re.fullmatch('[0-9a-fA-F]{64}', photo['sha256']):
            raise ValueError('sha256が不正です')
        if photo.get('device_id') is not None:
            validate_device_id(photo['device_id'])
        if photo.get('device_id_source') not in (None, 'qr', 'manual', 'sidecar', 'sidecar_qr', 'sidecar_manual', 'pc_qr'):
            raise ValueError('機器IDの出所が不正です')
        if normalize_captured_at(photo.get('captured_at')) is None:
            raise ValueError('撮影日時が不正です')
    return data


def save_manifest(storage, inspection_id, data, incoming_dir=None):
    validate_manifest(inspection_id, data)
    fields = ('inspection_name', 'route_id', 'operator', 'place', 'started_at', 'completed_at')
    with storage.connection() as conn:
        conn.execute('INSERT INTO inspections VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(inspection_id) DO UPDATE SET inspection_name=excluded.inspection_name, route_id=excluded.route_id, operator=excluded.operator, place=excluded.place, started_at=excluded.started_at, completed_at=excluded.completed_at, manifest_received_at=excluded.manifest_received_at, manifest_json=excluded.manifest_json',
                     (inspection_id, *(data.get(k) for k in fields), now(), json.dumps(data, ensure_ascii=False)))
    status = inspection_status(storage, inspection_id, incoming_dir)
    return dict(ok=True, matched=status['matched'], missing_photos=status['missing_photos'])


def get_manifest(storage, inspection_id):
    with storage.connection() as conn:
        row = conn.execute('SELECT manifest_json FROM inspections WHERE inspection_id=?', (inspection_id,)).fetchone()
    return json.loads(row[0]) if row else None


@lru_cache(maxsize=4096)
def _file_hash(path, size, mtime_ns):
    # Stat fields invalidate cached hashes when a received file changes.
    from manager.batch import calculate_file_hash
    return calculate_file_hash(path)


def received_hashes(storage, incoming_dir=None):
    hashes = {h.lower() for h in storage.get_processed_hashes()}
    if incoming_dir and os.path.isdir(incoming_dir):
        with os.scandir(incoming_dir) as files:
            for entry in files:
                if not entry.name.lower().endswith(('.jpg', '.jpeg', '.png')):
                    continue
                try:
                    if entry.is_file(follow_symlinks=False):
                        stat = entry.stat(follow_symlinks=False)
                        hashes.add(_file_hash(entry.path, stat.st_size, stat.st_mtime_ns).lower())
                except OSError:
                    continue  # The ingest process may have moved this file.
    return hashes


def inspection_status(storage, inspection_id, incoming_dir=None):
    manifest = get_manifest(storage, inspection_id)
    if manifest is None:
        return dict(state='受信中', matched=0, missing_photos=[])
    hashes = received_hashes(storage, incoming_dir)
    missing = [p['file_name'] for p in manifest['photos'] if p['sha256'].lower() not in hashes]
    return dict(state='不足あり' if missing else '完了', matched=len(manifest['photos']) - len(missing), missing_photos=missing)


def arrived_manifest_devices(storage, manifest, readings, incoming_dir=None):
    """Use received photo hashes before OCR has produced a reading row."""
    hashes = received_hashes(storage, incoming_dir)
    recorded = {r.image_sha256.lower() for r in readings if r.image_sha256}
    return [dict(device_id=p.get('device_id')) for p in (manifest or {}).get('photos', [])
            if p['sha256'].lower() in hashes and p['sha256'].lower() not in recorded]


def route_progress(route, readings, manifest=None):
    """Actual photos override phone missing/extra claims; retain pending extras."""
    def field(row, key):
        return row.get(key) if isinstance(row, dict) else getattr(row, key, None)
    actual = {field(r, 'device_id') for r in readings} - {None, ''}
    planned = {d['id'] for d in route['devices']}
    manifest = manifest or {}
    rows = [dict(機器ID=d['id'], 機器名=d['name'], 撮影状態='撮影済み' if d['id'] in actual else '未撮影',
                 スマホ申告='未撮影' if d['id'] in manifest.get('missing', []) else '') for d in route['devices']]
    rows += [dict(機器ID=d, 機器名='', 撮影状態='追加', スマホ申告='追加' if d in manifest.get('extra', []) else '') for d in sorted(actual - planned)]
    rows += [dict(機器ID=d, 機器名='', 撮影状態='追加（未着）', スマホ申告='追加') for d in dict.fromkeys(manifest.get('extra', [])) if d not in actual and d not in planned]
    return rows
