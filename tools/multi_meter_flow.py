"""Isolated HTTP -> manifest -> real pipeline -> SQLite multi-meter exercise.

Run with the project venv: python tools/multi_meter_flow.py
No application defaults or real incoming/database paths are used.
"""
from pathlib import Path
import argparse
import base64
import hashlib
import json
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
import urllib.error

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from manager.storage import Storage
from manager.receiver import ReceiverServer
from manager.routes import (save_route, inspection_status, route_progress,
                            arrived_manifest_devices)
from manager.export import inspection_devices
from manager.ingest import ingest_result
from manager.sidecar import load_sidecar
from manager.pipeline_caller import execute_pipeline
from manager.qr_decode import read_device_qr

DATA = Path('C:/卒研/合成画像/テスト用QR付き_20261030')
IID = 'I-MULTI-20261112'


def fixtures(directory, synthetic=False):
    if synthetic:
        import qrcode
        from manager.qr_label import build_payload
        rows = []
        for n in range(1, 7):
            path = Path(directory) / f'fixture{n}.png'
            qrcode.make(build_payload(f'FLOW-{n:03}', f'Meter {n}')).save(path)
            rows.append(dict(image=str(path), device_id=f'FLOW-{n:03}',
                             device_name=f'Meter {n}', true_value=None))
        return rows
    rows = json.loads((DATA / '正解_QR付き.json').read_text(encoding='utf-8'))
    selected = {}
    for row in rows:
        if row['category'] == '正面' and row['device_id'] not in selected:
            if Path(row['image']).is_file():
                selected[row['device_id']] = row
        if len(selected) == 6:
            return list(selected.values())
    raise RuntimeError('Need six distinct front-facing synthetic QR fixtures')


def run_flow(directory, synthetic_fixtures=False):
    base = Path(directory)
    incoming = base / 'incoming'
    incoming.mkdir()
    storage = Storage(str(base / 'flow.db'))
    selected = fixtures(base, synthetic_fixtures)
    route = save_route(storage, 'Multi meter flow',
                       [dict(id=r['device_id'], name=r['device_name']) for r in selected[:5]],
                       route_id='R-MULTI')
    server = ReceiverServer(('127.0.0.1', 0), token='isolated-test-token',
                            incoming_dir=str(incoming), db_path=storage.db_path,
                            receiver_id='test-multi', quiet=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    def request(endpoint, body=None, headers=None):
        req = urllib.request.Request(
            f'http://127.0.0.1:{server.server_address[1]}{endpoint}', data=body,
            headers={'X-Sotuken-Token': 'isolated-test-token', **(headers or {})})
        with urllib.request.urlopen(req, timeout=30) as response:
            return json.load(response)
    try:
        assert request('/routes/R-MULTI')['devices'] == route['devices']
        before = inspection_status(storage, IID, str(incoming))
        photos, sent = [], []
        # Five required photos, plus an image-QR-only probe of the extra meter.
        for index, (row, source) in enumerate(
                [(r, 'qr') for r in selected[:3]] + [(selected[3], 'list'),
                 (selected[5], 'qr'), (selected[5], None)], 1):
            body = Path(row['image']).read_bytes()
            if source is None:
                body += b'pc-qr-probe'  # Distinct hash, still a valid PNG.
            sha = hashlib.sha256(body).hexdigest()
            name = f'20261112T0900{index:02}_{index}.png'
            side = dict(local_id=index, captured_at='2026-11-12T09:00:00+09:00',
                        inspection_id=IID, inspection_name='Multi meter flow',
                        route_id=route['route_id'])
            if source:
                side.update(device_id=row['device_id'], device_name=row['device_name'],
                            device_id_source=source)
            reply = request('/upload', body, {
                'X-File-Name': name, 'X-Image-Sha256': sha,
                'X-Sidecar-Json': base64.urlsafe_b64encode(json.dumps(side).encode()).decode().rstrip('=')})
            assert reply['stored'] == name, reply
            photos.append(dict(file_name=name, sha256=sha, device_id=row['device_id'],
                               device_id_source=source, captured_at=side['captured_at']))
            sent.append(dict(file_name=name, fixture=row['image'], device_id=row['device_id'],
                             source=source, expected_value=row['true_value'], sha256=sha))
        manifest = dict(v=1, inspection_id=IID, inspection_name='Multi meter flow',
                        route_id=route['route_id'], operator='test', place='isolated',
                        started_at='2026-11-12T00:00:00Z', completed_at='2026-11-12T01:00:00Z',
                        photos=photos, missing=[selected[4]['device_id']], extra=[selected[5]['device_id']])
        rejected = None
        try:
            manifest_reply = request(f'/inspections/{IID}/manifest', json.dumps(manifest).encode(),
                                     {'Content-Type': 'application/json'})
        except urllib.error.HTTPError as exc:
            if exc.code != 400:
                raise
            rejected = dict(status=exc.code, body=exc.read().decode(), original=manifest)
            # Diagnostic continuation only: retain list on the photo sidecar.
            manifest = json.loads(json.dumps(manifest))
            manifest['photos'][3]['device_id_source'] = 'sidecar'
            manifest_reply = request(f'/inspections/{IID}/manifest', json.dumps(manifest).encode(),
                                     {'Content-Type': 'application/json'})
        received = inspection_status(storage, IID, str(incoming))
        arrived = arrived_manifest_devices(storage, manifest, [], str(incoming))
        # A missing transport file must differ from an intentionally unshot meter.
        held = incoming / sent[0]['file_name']
        parked = base / 'held.png'
        held.rename(parked)
        try:
            missing_transport = inspection_status(storage, IID, str(incoming))
        finally:
            parked.rename(held)
        timings, decoded = [], []
        for photo in sent:
            path = incoming / photo['file_name']
            decoded.append(repr(read_device_qr(str(path))))
            started = time.perf_counter()
            result = execute_pipeline(str(path), use_vlm=False)
            ingest_result(storage, str(path), load_sidecar(str(path)), result,
                          str(base / 'images'), str(base / 'overlays'))
            timings.append(round(time.perf_counter() - started, 3))
        readings = storage.get_all_readings()
        with storage.connection() as conn:
            cursor = conn.execute('SELECT * FROM meter_readings ORDER BY id')
            rows = [dict(zip([c[0] for c in cursor.description], row)) for row in cursor.fetchall()]
        return dict(directory=str(base), route=route, sent=sent, manifest=manifest,
                    before=before, manifest_reply=manifest_reply, rejected_manifest=rejected, received=received,
                    arrived_before_ocr=arrived, missing_transport=missing_transport,
                    progress_before_ocr=route_progress(route, arrived, manifest),
                    decoded_qr=decoded, seconds=timings,
                    after=inspection_status(storage, IID, str(incoming)), rows=rows,
                    arrived_after_ocr=arrived_manifest_devices(storage, manifest, readings, str(incoming)),
                    progress=route_progress(route, readings, manifest), devices=inspection_devices(readings))
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def ollama(*args):
    try:
        run = subprocess.run(['ollama', *args], capture_output=True, text=True, timeout=30)
        return dict(code=run.returncode, stdout=run.stdout, stderr=run.stderr)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return dict(error=str(exc))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'tasks/reports/multi-meter-flow-result.json')
    args = parser.parse_args()
    before = ollama('ps')
    try:
        with tempfile.TemporaryDirectory(prefix='sotuken_multi_') as directory:
            result = run_flow(directory)
    finally:
        after = ollama('ps')
        stopped = ollama('stop', 'qwen3-vl:4b-instruct')
    result.update(ollama_before=before, ollama_after=after, ollama_stop=stopped)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str), encoding='utf-8')
    print('device | source | value | stage | seconds')
    for row, seconds in zip(result['rows'], result['seconds']):
        print(row['device_id'], row['device_id_source'], row['value'], row['stage'], seconds, sep=' | ')
    if result['rejected_manifest']:
        print('MISMATCH: list manifest rejected (manager/routes.py:validate_manifest); continued with sidecar')
    for photo, row in zip(result['sent'], result['rows']):
        if photo['source'] == 'list' and row['device_id_source'] != 'list':
            print('MISMATCH: list provenance lost (manager/sidecar.py:load_sidecar, manager/ingest.py:_sidecar_identity)')
    print('inspection_status:', result['after'])
    print('route_progress:', json.dumps(result['progress'], ensure_ascii=False))
    print('inspection_devices:', json.dumps(result['devices'], ensure_ascii=False))
    print(args.output)


if __name__ == '__main__':
    main()
