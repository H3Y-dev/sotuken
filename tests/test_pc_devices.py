import http.client
import json
from pathlib import Path
import sqlite3
import tempfile
import threading
import unittest
from urllib.parse import quote

from manager.devices import create_device, get_device, register_device
from manager.storage import Storage
from pc_api.launcher import VerificationLauncher
from pc_api.server import PCAPI


def _payload(**overrides):
    data = {
        'device_name': 'Pressure Gauge',
        'unit': 'MPa',
        'min_value': 0.0,
        'max_value': 100.0,
        'tolerance_min': 10.0,
        'tolerance_max': 80.0,
    }
    data.update(overrides)
    return data


class PCDevicesTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.images = root / 'images'
        self.images.mkdir()
        self.db_path = root / 'manager.db'
        self.storage = Storage(str(self.db_path))
        self.api = PCAPI(self.db_path, image_dirs=[self.images], port=0)
        self.api.start()
        self.addCleanup(self.api.stop)
        self.origin = f'http://127.0.0.1:{self.api.port}'
        self.cookie, self.csrf = self._authenticate()

    def _authenticate(self):
        launch_key = self.api.sessions.issue_launch_key()
        status, body, set_cookies = self._raw_request(
            '/api/v1/session',
            'POST',
            headers={'Origin': self.origin, 'Content-Type': 'application/json'},
            body=json.dumps({'launch_key': launch_key}).encode('utf-8'),
        )
        self.assertEqual(status, 200)
        return set_cookies[0].split(';', 1)[0], body['csrf_token']

    def _raw_request(self, path, method='GET', headers=None, body=None):
        conn = http.client.HTTPConnection('127.0.0.1', self.api.port, timeout=5)
        try:
            conn.request(method, path, body=body, headers=dict(headers or {}))
            response = conn.getresponse()
            data = response.read()
            mime = response.getheader('Content-Type') or ''
            parsed = json.loads(data) if data and 'application/json' in mime else data
            return response.status, parsed, response.headers.get_all('Set-Cookie', [])
        finally:
            conn.close()

    def _authed(self, path, method='GET', body=None, headers=None):
        req_headers = {'Cookie': self.cookie}
        if method != 'GET':
            req_headers.update({
                'Origin': self.origin,
                'X-CSRF-Token': self.csrf,
                'Content-Type': 'application/json',
            })
        if headers:
            req_headers.update(headers)
        raw = json.dumps(body).encode('utf-8') if isinstance(body, (dict, list)) else body
        status, parsed, _ = self._raw_request(path, method=method, headers=req_headers, body=raw)
        return status, parsed

    def test_rejected_requests_with_body_return_complete_json(self):
        cases = [
            ({'Cookie': self.cookie, 'Origin': self.origin, 'Content-Type': 'application/json'}, 403),
            ({'Cookie': self.cookie, 'Origin': 'http://evil.example', 'X-CSRF-Token': self.csrf, 'Content-Type': 'application/json'}, 403),
            ({'Cookie': self.cookie, 'Origin': self.origin, 'X-CSRF-Token': self.csrf, 'Content-Type': 'text/plain'}, 400),
        ]
        for _ in range(10):
            for headers, expected in cases:
                status, body, _ = self._raw_request('/api/v1/devices', 'POST', headers, b'{}')
                self.assertEqual(status, expected)
                self.assertIn('error', body)

    def test_list_devices_empty_binary_order_and_limit_1000(self):
        status, body = self._authed('/api/v1/devices')
        self.assertEqual(status, 200)
        self.assertEqual(body, {'items': []})

        create_device(self.storage, 'a-1', _payload(device_name='Lower'))
        create_device(self.storage, 'B-1', _payload(device_name='Upper'))
        status, body = self._authed('/api/v1/devices')
        self.assertEqual(status, 200)
        self.assertEqual([item['device_id'] for item in body['items']], ['B-1', 'a-1'])
        self.assertEqual(
            set(body['items'][0]),
            {
                'device_id',
                'device_name',
                'unit',
                'min_value',
                'max_value',
                'tolerance_min',
                'tolerance_max',
                'provisional',
            },
        )
        self.assertIs(body['items'][0]['provisional'], False)

        status, err = self._authed('/api/v1/devices?limit=10')
        self.assertEqual(status, 400)
        self.assertEqual(err['error']['code'], 'invalid_request')

        with self.storage.connection() as conn:
            conn.executemany(
                'INSERT INTO devices (device_id, device_name, provisional) VALUES (?, ?, 0)',
                [(f'dev-{i:04d}', f'Device {i}') for i in range(999)],
            )
        status, err = self._authed('/api/v1/devices')
        self.assertEqual(status, 422)
        self.assertEqual(err['error']['code'], 'validation_failed')

    def test_create_device_success_conflict_and_validation_errors(self):
        status, created = self._authed(
            '/api/v1/devices',
            method='POST',
            body={'device_id': 'Pump-01', **_payload(device_name='  Main Pump  ', unit=' bar ')},
        )
        self.assertEqual(status, 201)
        self.assertEqual(created['device_id'], 'Pump-01')
        self.assertEqual(created['device_name'], 'Main Pump')
        self.assertEqual(created['unit'], 'bar')
        self.assertIs(created['provisional'], False)

        for conflict_id in ('Pump-01', 'pump-01'):
            status, err = self._authed(
                '/api/v1/devices',
                method='POST',
                body={'device_id': conflict_id, **_payload()},
            )
            self.assertEqual(status, 409)
            self.assertEqual(err['error']['code'], 'device_conflict')

        # 422 validation_failed cases (including tolerance_min > tolerance_max)
        invalid_payloads = [
            {'device_id': ' bad ', **_payload()},
            {'device_id': 'ok-1', **_payload(device_name='unknown')},
            {'device_id': 'ok-2', **_payload(tolerance_min=90.0, tolerance_max=20.0)},
            {'device_id': 'ok-3', **_payload(min_value=10.0, max_value=10.0)},
            {'device_id': 'ok-4', **_payload(min_value=0.0, max_value=50.0, tolerance_min=0.0, tolerance_max=60.0)},
            {'device_id': 'ok-5', **_payload(unit='a\nb')},
            {'device_id': 'ok-6', **_payload(min_value=True, max_value=10.0)},
        ]
        for payload in invalid_payloads:
            status, err = self._authed('/api/v1/devices', method='POST', body=payload)
            self.assertEqual(status, 422)
            self.assertEqual(err['error']['code'], 'validation_failed')

        # 400 invalid_request cases (missing/unknown/duplicate JSON keys, malformed JSON)
        for bad_body in (
            json.dumps(_payload()).encode('utf-8'),  # missing device_id
            json.dumps({'device_id': 'ok-7', **_payload(), 'extra': 1}).encode('utf-8'),
            b'{"device_id":"ok-8","device_id":"ok-9","device_name":"A","unit":null,"min_value":null,"max_value":null,"tolerance_min":null,"tolerance_max":null}',
            b'{"device_id":',
            b'[]',
        ):
            status, err = self._authed('/api/v1/devices', method='POST', body=bad_body)
            self.assertEqual(status, 400)
            self.assertEqual(err['error']['code'], 'invalid_request')

        # 413 too_large (> 16,384 bytes)
        oversized = b'{"device_id":"big","device_name":"' + (b'x' * 16400) + b'"}'
        status, err = self._authed('/api/v1/devices', method='POST', body=oversized)
        self.assertEqual(status, 413)
        self.assertEqual(err['error']['code'], 'too_large')

    def test_update_device_replaces_clears_null_and_handles_special_ids(self):
        register_device(
            self.storage,
            'dev-1',
            device_name='Auto Name',
            unit='kPa',
            min_value=0.0,
            max_value=50.0,
            kind='pressure',
            provisional=True,
            note='keep-note',
        )

        status, updated = self._authed(
            '/api/v1/devices/id-dev-1',
            method='PUT',
            body=_payload(
                device_name='Edited Name',
                unit=None,
                min_value=None,
                max_value=None,
                tolerance_min=None,
                tolerance_max=None,
            ),
        )
        self.assertEqual(status, 200)
        self.assertEqual(updated['device_name'], 'Edited Name')
        self.assertIsNone(updated['unit'])
        self.assertIsNone(updated['min_value'])
        self.assertIsNone(updated['tolerance_min'])
        self.assertIs(updated['provisional'], False)

        stored = get_device(self.storage, 'dev-1')
        self.assertEqual(stored['kind'], 'pressure')
        self.assertEqual(stored['note'], 'keep-note')

        status, err = self._authed('/api/v1/devices/id-missing', method='PUT', body=_payload())
        self.assertEqual(status, 404)
        self.assertEqual(err['error']['code'], 'not_found')

        status, err = self._authed('/api/v1/devices/id-dev-1/', method='PUT', body=_payload())
        self.assertEqual(status, 404)
        self.assertEqual(err['error']['code'], 'not_found')

        for special_id in ('.', '..', 'labels.pdf'):
            create_device(self.storage, special_id, _payload(device_name=f'Before {special_id}'))
            encoded = quote(special_id, safe='')
            status, body = self._authed(
                f'/api/v1/devices/id-{encoded}',
                method='PUT',
                body=_payload(device_name=f'After {special_id}'),
            )
            self.assertEqual(status, 200)
            self.assertEqual(body['device_id'], special_id)
            self.assertEqual(body['device_name'], f'After {special_id}')

    def test_auth_csrf_origin_and_content_type_enforcement(self):
        create_device(self.storage, 'dev-auth', _payload())

        # Unauthenticated requests -> 401
        for path, method, body in (
            ('/api/v1/devices', 'GET', None),
            ('/api/v1/devices', 'POST', json.dumps({'device_id': 'x', **_payload()}).encode('utf-8')),
            ('/api/v1/devices/id-dev-auth', 'PUT', json.dumps(_payload()).encode('utf-8')),
        ):
            status, err, _ = self._raw_request(path, method=method, body=body)
            self.assertEqual(status, 401)
            self.assertEqual(err['error']['code'], 'unauthenticated')

        # Missing/wrong CSRF or Origin -> 403
        valid_put = json.dumps(_payload()).encode('utf-8')
        for bad_headers in (
            {'Cookie': self.cookie, 'Origin': self.origin, 'Content-Type': 'application/json'},
            {'Cookie': self.cookie, 'Origin': self.origin, 'X-CSRF-Token': 'wrong', 'Content-Type': 'application/json'},
            {'Cookie': self.cookie, 'X-CSRF-Token': self.csrf, 'Content-Type': 'application/json'},
            {'Cookie': self.cookie, 'Origin': 'http://evil.example', 'X-CSRF-Token': self.csrf, 'Content-Type': 'application/json'},
        ):
            status, err, _ = self._raw_request('/api/v1/devices/id-dev-auth', method='PUT', headers=bad_headers, body=valid_put)
            self.assertEqual(status, 403)
            self.assertEqual(err['error']['code'], 'forbidden_origin')

        # Non-JSON Content-Type -> 400
        for content_type in ('text/plain', 'application/json; charset=shift_jis'):
            status, err, _ = self._raw_request(
                '/api/v1/devices',
                method='POST',
                headers={
                    'Cookie': self.cookie,
                    'Origin': self.origin,
                    'X-CSRF-Token': self.csrf,
                    'Content-Type': content_type,
                },
                body=json.dumps({'device_id': 'x', **_payload()}).encode('utf-8'),
            )
            self.assertEqual(status, 400)
            self.assertEqual(err['error']['code'], 'invalid_request')

    def test_concurrent_create_same_id_allows_only_one_success(self):
        barrier = threading.Barrier(4)
        results = []
        lock = threading.Lock()

        def worker():
            barrier.wait()
            status, body = self._authed(
                '/api/v1/devices',
                method='POST',
                body={'device_id': 'race-01', **_payload()},
            )
            with lock:
                results.append((status, body))

        threads = [threading.Thread(target=worker) for _ in range(4)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        statuses = [status for status, _ in results]
        self.assertEqual(statuses.count(201), 1)
        self.assertEqual(statuses.count(409), 3)

    def test_launcher_migrates_legacy_db_before_serving_devices(self):
        legacy_dir = Path(self.tmp.name) / 'legacy'
        legacy_dir.mkdir()
        (legacy_dir / 'incoming').mkdir()
        (legacy_dir / 'images').mkdir()
        (legacy_dir / 'overlays').mkdir()
        legacy_db = legacy_dir / 'manager.db'
        conn = sqlite3.connect(legacy_db)
        try:
            conn.executescript(
                """
                CREATE TABLE meter_readings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    device_name TEXT NOT NULL,
                    value REAL,
                    stage TEXT NOT NULL,
                    image_path TEXT NOT NULL,
                    raw_data_json TEXT
                );
                CREATE TABLE devices (
                    device_id TEXT PRIMARY KEY,
                    device_name TEXT NOT NULL,
                    unit TEXT,
                    min_value REAL,
                    max_value REAL,
                    kind TEXT,
                    provisional INTEGER DEFAULT 0,
                    note TEXT,
                    created_at TEXT,
                    updated_at TEXT
                );
                INSERT INTO devices (device_id, device_name, provisional)
                VALUES ('LEGACY-1', 'Legacy Gauge', 0);
                """
            )
            conn.commit()
        finally:
            conn.close()

        launcher = VerificationLauncher(
            db_path=legacy_db,
            incoming_dir=legacy_dir / 'incoming',
            images_dir=legacy_dir / 'images',
            overlays_dir=legacy_dir / 'overlays',
            port=18766,
            owner_port=18767,
        )
        launcher.start()
        try:
            launch_key = launcher.launch_url.split('#k=', 1)[1]
            origin = f'http://127.0.0.1:{launcher.port}'
            conn_http = http.client.HTTPConnection('127.0.0.1', launcher.port, timeout=5)
            try:
                conn_http.request(
                    'POST',
                    '/api/v1/session',
                    body=json.dumps({'launch_key': launch_key}).encode('utf-8'),
                    headers={'Origin': origin, 'Content-Type': 'application/json'},
                )
                resp = conn_http.getresponse()
                resp.read()
                self.assertEqual(resp.status, 200)
                cookie = resp.headers.get_all('Set-Cookie', [])[0].split(';', 1)[0]

                conn_http.request('GET', '/api/v1/devices', headers={'Cookie': cookie})
                dev_resp = conn_http.getresponse()
                dev_body = json.loads(dev_resp.read())
                self.assertEqual(dev_resp.status, 200)
                self.assertEqual(len(dev_body['items']), 1)
                self.assertEqual(dev_body['items'][0]['device_id'], 'LEGACY-1')
                self.assertIsNone(dev_body['items'][0]['tolerance_min'])
            finally:
                conn_http.close()
        finally:
            launcher.stop()

