from contextlib import closing
import hashlib
import http.client
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import Mock, patch

from manager.routes import arrived_manifest_devices, inspection_status, save_manifest
from manager.storage import Storage
from pc_api.launcher import VerificationLauncher
from pc_api.server import PCAPI


def _free_port():
    import socket
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


def _make_manifest(inspection_id, photos):
    return {
        'v': 1,
        'inspection_id': inspection_id,
        'inspection_name': f'点検-{inspection_id}',
        'route_id': None,
        'operator': '担当A',
        'place': '1F',
        'started_at': '2026-11-18T09:00:00+09:00',
        'completed_at': '2026-11-18T09:10:00+09:00',
        'missing': [],
        'extra': [],
        'photos': photos,
    }


class InspectionStatusAPITests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.incoming = self.root / 'incoming'
        self.images = self.root / 'images'
        self.overlays = self.root / 'overlays'
        for d in (self.incoming, self.images, self.overlays):
            d.mkdir()
        self.db = self.root / 'manager.db'
        self.storage = Storage(str(self.db))

        self.photo_a_bytes = b'\x89PNG\r\n\x1a\nphoto-a'
        self.photo_b_bytes = b'\x89PNG\r\n\x1a\nphoto-b'
        self.hash_a = hashlib.sha256(self.photo_a_bytes).hexdigest()
        self.hash_b = hashlib.sha256(self.photo_b_bytes).hexdigest()

        self.api = PCAPI(
            self.db,
            incoming_dir=self.incoming,
            image_dirs=[self.incoming, self.images, self.overlays],
            port=0,
        )
        self.api.start()
        self.addCleanup(self.api.stop)
        sid, csrf = self.api.sessions.exchange_launch_key(self.api.sessions.issue_launch_key())
        self.session_cookie = f'pc_session={sid}'
        self.csrf_token = csrf

    def request(self, path, method='GET', headers=None, auth=True):
        conn = http.client.HTTPConnection('127.0.0.1', self.api.port, timeout=3)
        try:
            req_headers = dict(headers or {})
            if auth:
                req_headers.setdefault('Cookie', self.session_cookie)
                if method not in ('GET', 'HEAD'):
                    req_headers.setdefault('Origin', f'http://127.0.0.1:{self.api.port}')
                    req_headers.setdefault('X-CSRF-Token', self.csrf_token)
            conn.request(method, path, headers=req_headers)
            res = conn.getresponse()
            raw = res.read()
            mime = res.getheader('Content-Type') or ''
            body = json.loads(raw) if raw and 'application/json' in mime else raw
            return res.status, body, dict(res.getheaders())
        finally:
            conn.close()

    def test_unauthenticated_returns_401(self):
        status, body, headers = self.request('/api/v1/inspections/I-1/status', auth=False)
        self.assertEqual(status, 401)
        self.assertEqual(body['error']['code'], 'unauthenticated')
        self.assertEqual(headers.get('Cache-Control'), 'no-store')

    def test_unknown_and_invalid_ids_and_queries(self):
        status, body, _ = self.request('/api/v1/inspections/unknown-id/status')
        self.assertEqual(status, 404)
        self.assertEqual(body['error']['code'], 'not_found')

        for bad_path in (
            '/api/v1/inspections/./status',
            '/api/v1/inspections/../status',
            '/api/v1/inspections/%2e/status',
            '/api/v1/inspections/%2e%2e/status',
            '/api/v1/inspections/a%2Fb/status',
            '/api/v1/inspections/' + ('a' * 65) + '/status',
            '/api/v1/inspections/I-1/status?extra=1',
        ):
            status, body, _ = self.request(bad_path)
            self.assertEqual(status, 400, bad_path)
            self.assertEqual(body['error']['code'], 'invalid_request', bad_path)

        status, body, _ = self.request('/api/v1/inspections/I-1/status', method='POST')
        self.assertEqual(status, 400)
        self.assertEqual(body['error']['code'], 'invalid_request')

    def test_history_only_returns_receiving(self):
        with self.storage.connection() as conn:
            conn.execute(
                'INSERT INTO meter_readings (timestamp, device_name, value, stage, image_path, inspection_id) VALUES (?, ?, ?, ?, ?, ?)',
                ('2026-11-18T09:05:00+09:00', 'M1', 12.3, 'done', str(self.images / 'm1.png'), 'H-ONLY'),
            )
        status, body, headers = self.request('/api/v1/inspections/H-ONLY/status')
        self.assertEqual(status, 200)
        self.assertEqual(headers.get('Cache-Control'), 'no-store')
        self.assertEqual(body, {'state': '受信中', 'matched': 0, 'missing_photos': []})

    def test_manifest_only_missing_arrived_and_null_hash(self):
        save_manifest(
            self.storage,
            'M-1',
            _make_manifest('M-1', [
                {'file_name': 'a.jpg', 'sha256': self.hash_a, 'device_id': 'D1', 'device_id_source': 'qr', 'captured_at': '2026-11-18T09:01:00+09:00'},
                {'file_name': 'b.jpg', 'sha256': self.hash_b, 'device_id': 'D2', 'device_id_source': 'qr', 'captured_at': '2026-11-18T09:02:00+09:00'},
            ]),
            self.incoming,
        )
        # Neither arrived yet
        status, body, _ = self.request('/api/v1/inspections/M-1/status')
        self.assertEqual(status, 200)
        self.assertEqual(body, {'state': '不足あり', 'matched': 0, 'missing_photos': ['a.jpg', 'b.jpg']})

        # One arrives in incoming folder
        (self.incoming / 'a.jpg').write_bytes(self.photo_a_bytes)
        status, body, _ = self.request('/api/v1/inspections/M-1/status')
        self.assertEqual(status, 200)
        self.assertEqual(body, {'state': '不足あり', 'matched': 1, 'missing_photos': ['b.jpg']})

        # Second arrives in meter_readings DB
        with self.storage.connection() as conn:
            conn.execute(
                'INSERT INTO meter_readings (timestamp, device_name, value, stage, image_path, image_sha256, inspection_id) VALUES (?, ?, ?, ?, ?, ?, ?)',
                ('2026-11-18T09:03:00+09:00', 'D2', 45.6, 'done', str(self.images / 'b.jpg'), self.hash_b.upper(), 'M-1'),
            )
        status, body, _ = self.request('/api/v1/inspections/M-1/status')
        self.assertEqual(status, 200)
        self.assertEqual(body, {'state': '完了', 'matched': 2, 'missing_photos': []})

        # Manifest with null sha256 stays missing
        save_manifest(
            self.storage,
            'M-NULL',
            _make_manifest('M-NULL', [
                {'file_name': 'a.jpg', 'sha256': self.hash_a, 'device_id': 'D1', 'device_id_source': 'qr', 'captured_at': '2026-11-18T09:01:00+09:00'},
                {'file_name': 'null.jpg', 'sha256': None, 'device_id': 'D3', 'device_id_source': 'manual', 'captured_at': '2026-11-18T09:02:00+09:00'},
            ]),
            self.incoming,
        )
        status, body, _ = self.request('/api/v1/inspections/M-NULL/status')
        self.assertEqual(status, 200)
        self.assertEqual(body, {'state': '不足あり', 'matched': 1, 'missing_photos': ['null.jpg']})

    def test_db_busy_returns_503_with_retry_after(self):
        with patch.object(self.api.storage, '_get_connection', side_effect=sqlite3.OperationalError('database is locked')):
            status, body, headers = self.request('/api/v1/inspections/I-1/status')
        self.assertEqual(status, 503)
        self.assertEqual(body['error']['code'], 'db_busy')
        self.assertEqual(headers.get('Retry-After'), '1')
        self.assertEqual(headers.get('Cache-Control'), 'no-store')

    def test_invalid_manifest_json_and_photo_limit(self):
        with self.storage.connection() as conn:
            conn.execute(
                'INSERT INTO inspections VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)',
                ('BAD-JSON', '壊れ', None, None, None, None, None, None, '{not-json'),
            )
        status, body, _ = self.request('/api/v1/inspections/BAD-JSON/status')
        self.assertEqual(status, 503)
        self.assertEqual(body['error']['code'], 'data_invalid')

        with self.storage.connection() as conn:
            conn.execute(
                'INSERT INTO inspections VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)',
                ('OVER-LIMIT', '超過', None, None, None, None, None, None,
                 json.dumps({'v': 1, 'inspection_id': 'OVER-LIMIT', 'photos': [{'file_name': f'p{i}.jpg', 'sha256': None} for i in range(10001)]})),
            )
        status, body, _ = self.request('/api/v1/inspections/OVER-LIMIT/status')
        self.assertEqual(status, 422)
        self.assertEqual(body['error']['code'], 'validation_failed')

    def test_routes_helpers_regression_and_hashes_kwarg(self):
        manifest = _make_manifest('R-1', [
            {'file_name': 'a.jpg', 'sha256': self.hash_a, 'device_id': 'D1', 'device_id_source': 'qr', 'captured_at': '2026-11-18T09:01:00+09:00'},
        ])
        res = save_manifest(self.storage, 'R-1', manifest, self.incoming)
        self.assertEqual(res, {'ok': True, 'matched': 0, 'missing_photos': ['a.jpg']})
        self.assertEqual(inspection_status(self.storage, 'R-1', self.incoming), {'state': '不足あり', 'matched': 0, 'missing_photos': ['a.jpg']})
        self.assertEqual(inspection_status(self.storage, 'R-1', self.incoming, hashes={self.hash_a}), {'state': '完了', 'matched': 1, 'missing_photos': []})
        self.assertEqual(arrived_manifest_devices(self.storage, manifest, [], self.incoming, hashes={self.hash_a}), [{'device_id': 'D1'}])

    def test_launcher_passes_real_incoming_dir_to_server(self):
        self.api.stop()
        real_incoming = self.root / 'receiver_incoming'
        real_incoming.mkdir()
        (real_incoming / 'a.jpg').write_bytes(self.photo_a_bytes)
        save_manifest(
            self.storage,
            'L-1',
            _make_manifest('L-1', [
                {'file_name': 'a.jpg', 'sha256': self.hash_a, 'device_id': 'D1', 'device_id_source': 'qr', 'captured_at': '2026-11-18T09:01:00+09:00'},
            ]),
            real_incoming,
        )
        receiver = Mock()
        receiver.pairing_status.return_value = None
        receiver.incoming_dir = str(real_incoming)
        info = dict(
            running=True,
            server=receiver,
            thread=None,
            url='http://127.0.0.1:8765',
            external_process=False,
        )
        port = _free_port()
        with patch('pc_api.owner.init_receiver_for_app', return_value=info):
            launcher = VerificationLauncher(
                db_path=self.db,
                incoming_dir=self.incoming,
                images_dir=self.images,
                overlays_dir=self.overlays,
                port=port,
                owner_port=0,
            )
            launcher.start()
            self.addCleanup(launcher.stop)

            launch_key = launcher.launch_url.split('#k=', 1)[1]
            with closing(http.client.HTTPConnection('127.0.0.1', port, timeout=3)) as conn:
                conn.request(
                    'POST',
                    '/api/v1/session',
                    body=json.dumps({'launch_key': launch_key}).encode('utf-8'),
                    headers={
                        'Host': f'127.0.0.1:{port}',
                        'Origin': f'http://127.0.0.1:{port}',
                        'Content-Type': 'application/json',
                    },
                )
                sess_res = conn.getresponse()
                sess_res.read()
                self.assertEqual(sess_res.status, 200)
                cookie = sess_res.getheader('Set-Cookie').split(';', 1)[0]

                conn.request(
                    'GET',
                    '/api/v1/inspections/L-1/status',
                    headers={'Host': f'127.0.0.1:{port}', 'Cookie': cookie},
                )
                status_res = conn.getresponse()
                payload = json.loads(status_res.read().decode('utf-8'))
                self.assertEqual(status_res.status, 200)
                self.assertEqual(payload, {'state': '完了', 'matched': 1, 'missing_photos': []})
