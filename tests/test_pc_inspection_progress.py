import hashlib
import http.client
import json
from pathlib import Path
import tempfile
import unittest

from manager.routes import save_manifest, save_route
from manager.storage import Storage
from pc_api.inspection_progress import summarize_progress
from pc_api.server import PCAPI


def _make_manifest(inspection_id, photos, *, route_id=None, missing=None, extra=None):
    return {
        'v': 1,
        'inspection_id': inspection_id,
        'inspection_name': f'点検-{inspection_id}',
        'route_id': route_id,
        'operator': '担当A',
        'place': '1F',
        'started_at': '2026-11-18T09:00:00+09:00',
        'completed_at': '2026-11-18T09:30:00+09:00',
        'missing': missing or [],
        'extra': extra or [],
        'photos': photos,
    }


class InspectionProgressAPITests(unittest.TestCase):
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

        self.api = PCAPI(
            self.db,
            incoming_dir=self.incoming,
            image_dirs=[self.incoming, self.images, self.overlays],
            port=0,
        )
        self.api.start()
        self.addCleanup(self.api.stop)
        sid, _ = self.api.sessions.exchange_launch_key(self.api.sessions.issue_launch_key())
        self.session_cookie = f'pc_session={sid}'

    def request(self, path, method='GET', auth=True):
        conn = http.client.HTTPConnection('127.0.0.1', self.api.port, timeout=3)
        try:
            headers = {'Cookie': self.session_cookie} if auth else {}
            conn.request(method, path, headers=headers)
            res = conn.getresponse()
            raw = res.read()
            mime = res.getheader('Content-Type') or ''
            body = json.loads(raw) if raw and 'application/json' in mime else raw
            return res.status, body, dict(res.getheaders())
        finally:
            conn.close()

    def _insert_device(self, device_id, name, *, unit=None, min_val=None, max_val=None, tol_min=None, tol_max=None):
        with self.storage.connection() as conn:
            conn.execute(
                'INSERT OR REPLACE INTO devices '
                '(device_id, device_name, unit, min_value, max_value, tolerance_min, tolerance_max) '
                'VALUES (?, ?, ?, ?, ?, ?, ?)',
                (device_id, name, unit, min_val, max_val, tol_min, tol_max),
            )

    def _insert_reading(self, inspection_id, *, device_id=None, device_name='unknown', value=None,
                        status='ok', stage='done', image_sha256=None, device_id_source=None,
                        captured_at=None, received_at=None, timestamp='2026-11-18T09:10:00+09:00',
                        inspection_name=None, route_id=None):
        with self.storage.connection() as conn:
            conn.execute(
                'INSERT INTO meter_readings '
                '(timestamp, device_name, value, stage, image_path, image_sha256, status, '
                'device_id, device_id_source, captured_at, received_at, inspection_id, inspection_name, route_id) '
                'VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
                (timestamp, device_name, value, stage, str(self.images / 'x.jpg'), image_sha256, status,
                 device_id, device_id_source, captured_at, received_at, inspection_id, inspection_name, route_id),
            )

    def test_route_order_stages_and_extra_declaration(self):
        route = save_route(self.storage, '1F巡回', [
            {'id': 'D1', 'name': 'R-D1'},
            {'id': 'D2', 'name': 'R-D2'},
            {'id': 'D3', 'name': 'R-D3'},
            {'id': 'D4', 'name': 'R-D4'},
        ])
        self._insert_device('D4', 'DB-D4', unit='MPa', min_val=0.0, max_val=10.0, tol_min=1.0, tol_max=5.0)
        b2 = b'img-d2'
        b4 = b'img-d4'
        b_ext = b'img-ext'
        h2 = hashlib.sha256(b2).hexdigest()
        h4 = hashlib.sha256(b4).hexdigest()
        h_ext = hashlib.sha256(b_ext).hexdigest()
        (self.incoming / 'd2.jpg').write_bytes(b2)

        save_manifest(
            self.storage,
            'INSP-1',
            _make_manifest(
                'INSP-1',
                [
                    {'file_name': 'd2.jpg', 'sha256': h2, 'device_id': 'D2', 'device_id_source': 'qr', 'captured_at': '2026-11-18T09:02:00+09:00'},
                    {'file_name': 'd3.jpg', 'sha256': None, 'device_id': 'D3', 'device_id_source': 'manual', 'captured_at': '2026-11-18T09:03:00+09:00'},
                    {'file_name': 'd4.jpg', 'sha256': h4, 'device_id': 'D4', 'device_id_source': 'sidecar_qr', 'captured_at': '2026-11-18T09:04:00+09:00'},
                    {'file_name': 'ext.jpg', 'sha256': h_ext, 'device_id': 'D_EXT', 'device_id_source': 'list', 'captured_at': '2026-11-18T09:05:00+09:00'},
                ],
                route_id=route['route_id'],
                missing=['D1'],
                extra=['D_EXT', 'D_DECLARED_ONLY'],
            ),
            self.incoming,
        )
        self._insert_reading(
            'INSP-1', device_id='D4', device_name='OCR-D4', value=3.2, status='ok',
            image_sha256=h4.upper(), device_id_source='pc_qr', captured_at='2026-11-18T09:04:00+09:00',
        )

        status, body, headers = self.request('/api/v1/inspections/INSP-1/progress')
        self.assertEqual(status, 200)
        self.assertEqual(headers.get('Cache-Control'), 'no-store')
        self.assertEqual(body['route_id'], route['route_id'])
        self.assertEqual(body['route_name'], '1F巡回')
        self.assertEqual(body['status'], {'state': '不足あり', 'matched': 2, 'missing_photos': ['d3.jpg', 'ext.jpg']})

        keys = [d['key'] for d in body['devices']]
        self.assertEqual(keys, ['device:D1', 'device:D2', 'device:D3', 'device:D4', 'device:D_DECLARED_ONLY', 'device:D_EXT'])

        d1, d2, d3, d4, d_decl, d_ext = body['devices']
        self.assertEqual((d1['seq'], d1['off_route'], d1['stage'], d1['photos'], d1['name']), (1, False, 0, 0, 'R-D1'))
        self.assertEqual((d2['seq'], d2['off_route'], d2['stage'], d2['photos'], d2['sources']), (2, False, 2, 1, ['phone_qr']))
        self.assertEqual((d3['seq'], d3['off_route'], d3['stage'], d3['photos'], d3['sources']), (3, False, 1, 1, ['manual']))
        self.assertEqual((d4['seq'], d4['off_route'], d4['stage'], d4['photos']), (4, False, 4, 1))
        self.assertEqual(d4['name'], 'DB-D4')
        self.assertEqual(d4['unit'], 'MPa')
        self.assertEqual(d4['scale'], [0.0, 10.0])
        self.assertEqual(d4['tolerance'], [1.0, 5.0])
        self.assertEqual(d4['value'], 3.2)
        self.assertEqual(d4['read_status'], 'ok')
        self.assertEqual(d4['sources'], ['phone_qr', 'pc_qr'])
        self.assertEqual((d_decl['seq'], d_decl['off_route'], d_decl['stage'], d_decl['photos']), (None, True, 1, 0))
        self.assertEqual((d_ext['seq'], d_ext['off_route'], d_ext['stage'], d_ext['photos'], d_ext['sources']), (None, True, 1, 1, []))

    def test_photo_deduplication_and_priority(self):
        b1 = b'dup-photo'
        h1 = hashlib.sha256(b1).hexdigest()
        # Same sha256 twice in manifest + matched DB reading with non-empty device_id overriding manifest.
        save_manifest(
            self.storage,
            'INSP-DUP',
            _make_manifest('INSP-DUP', [
                {'file_name': 'first.jpg', 'sha256': h1, 'device_id': 'M_OLD', 'device_id_source': 'qr', 'captured_at': '2026-11-18T09:01:00+09:00'},
                {'file_name': 'second.jpg', 'sha256': h1, 'device_id': 'M_OLD', 'device_id_source': 'manual', 'captured_at': '2026-11-18T09:01:00+09:00'},
                {'file_name': 'nohash1.jpg', 'sha256': None, 'device_id': None, 'device_id_source': None, 'captured_at': '2026-11-18T09:02:00+09:00'},
            ]),
            self.incoming,
        )
        self._insert_reading(
            'INSP-DUP', device_id='D_DB', device_name='機器DB名', value=4.5, status='ok',
            image_sha256=h1, device_id_source='pc_qr', captured_at=None,
        )
        # Two DB readings without sha256 for the same unnamed device -> counted separately by row id
        self._insert_reading('INSP-DUP', device_id=None, device_name='unknown', value=1.0, status='ok', image_sha256=None)
        self._insert_reading('INSP-DUP', device_id=None, device_name='', value=2.0, status='ok', image_sha256=None)

        status, body, _ = self.request('/api/v1/inspections/INSP-DUP/progress')
        self.assertEqual(status, 200)
        by_key = {d['key']: d for d in body['devices']}
        self.assertIn('device:D_DB', by_key)
        self.assertNotIn('device:M_OLD', by_key)
        dev = by_key['device:D_DB']
        self.assertEqual(dev['photos'], 1)
        self.assertEqual(dev['sources'], ['phone_qr', 'pc_qr'])
        self.assertEqual(dev['captured_at'], '2026-11-18T09:01:00+09:00')
        self.assertIn('photo:file:nohash1.jpg', by_key)
        row_keys = [k for k in by_key if k.startswith('photo:row:')]
        self.assertEqual(len(row_keys), 2)
        for k in row_keys:
            self.assertEqual(by_key[k]['name'], '名前なし')

    def test_failed_row_and_unnamed_vs_named_without_id(self):
        # Latest reading is failed even though an older reading succeeded; value must be null.
        self._insert_reading(
            'INSP-FAIL', device_id='D1', device_name='計器1', value=5.0, status='ok',
            captured_at='2026-11-18T09:00:00+09:00',
        )
        self._insert_reading(
            'INSP-FAIL', device_id='D1', device_name='計器1', value=99.9, status='failed',
            captured_at='2026-11-18T09:05:00+09:00',
        )
        # Named without device_id
        self._insert_reading(
            'INSP-FAIL', device_id=None, device_name='手動ボイラー', value=7.7, status='ok',
            captured_at='2026-11-18T09:06:00+09:00',
        )
        # Unnamed without device_id
        self._insert_reading(
            'INSP-FAIL', device_id=None, device_name='unknown', value=8.8, status='ok',
            captured_at='2026-11-18T09:07:00+09:00',
        )

        status, body, _ = self.request('/api/v1/inspections/INSP-FAIL/progress')
        self.assertEqual(status, 200)
        self.assertEqual(body['status'], {'state': '受信中', 'matched': 0, 'missing_photos': []})
        self.assertEqual(body['started_at'], '2026-11-18T09:00:00+09:00')
        by_key = {d['key']: d for d in body['devices']}
        self.assertEqual(by_key['device:D1']['value'], None)
        self.assertEqual(by_key['device:D1']['read_status'], 'failed')
        self.assertEqual(by_key['name:手動ボイラー']['name'], '手動ボイラー')
        self.assertEqual(by_key['name:手動ボイラー']['device_id'], None)
        self.assertEqual(by_key['name:手動ボイラー']['value'], 7.7)
        row_items = [d for k, d in by_key.items() if k.startswith('photo:row:')]
        self.assertEqual(len(row_items), 1)
        self.assertEqual(row_items[0]['name'], '名前なし')

    def test_tolerance_boundaries_and_unregistered_summary(self):
        self._insert_device('D_LO', '下限', tol_min=10.0, tol_max=20.0)
        self._insert_device('D_HI', '上限', tol_min=10.0, tol_max=20.0)
        self._insert_device('D_UNREG', '未登録')  # tolerance is None
        h_lo = hashlib.sha256(b'lo').hexdigest()
        h_hi = hashlib.sha256(b'hi').hexdigest()
        h_un = hashlib.sha256(b'un').hexdigest()
        save_manifest(
            self.storage,
            'INSP-TOL',
            _make_manifest('INSP-TOL', [
                {'file_name': 'lo.jpg', 'sha256': h_lo, 'device_id': 'D_LO', 'device_id_source': 'qr', 'captured_at': '2026-11-18T09:01:00+09:00'},
                {'file_name': 'hi.jpg', 'sha256': h_hi, 'device_id': 'D_HI', 'device_id_source': 'qr', 'captured_at': '2026-11-18T09:02:00+09:00'},
                {'file_name': 'un.jpg', 'sha256': h_un, 'device_id': 'D_UNREG', 'device_id_source': 'qr', 'captured_at': '2026-11-18T09:03:00+09:00'},
            ]),
            self.incoming,
        )
        self._insert_reading('INSP-TOL', device_id='D_LO', value=10.0, status='ok', image_sha256=h_lo)
        self._insert_reading('INSP-TOL', device_id='D_HI', value=20.0, status='ok', image_sha256=h_hi)
        self._insert_reading('INSP-TOL', device_id='D_UNREG', value=999.0, status='ok', image_sha256=h_un)

        status, body, _ = self.request('/api/v1/inspections/INSP-TOL/progress')
        self.assertEqual(status, 200)
        summary = summarize_progress(body)
        self.assertEqual(summary['out_of_tolerance'], 0)
        self.assertTrue(summary['all_ok'])
        self.assertFalse(summary['needs_action'])

        # Out of tolerance
        self._insert_reading('INSP-TOL', device_id='D_LO', value=9.99, status='ok', image_sha256=h_lo,
                             captured_at='2026-11-18T09:15:00+09:00')
        status, body2, _ = self.request('/api/v1/inspections/INSP-TOL/progress')
        self.assertEqual(status, 200)
        summary2 = summarize_progress(body2)
        self.assertEqual(summary2['out_of_tolerance'], 1)
        self.assertFalse(summary2['all_ok'])
        self.assertTrue(summary2['needs_action'])

    def test_limits_and_error_responses(self):
        # 401 unauthenticated
        status, body, _ = self.request('/api/v1/inspections/X/progress', auth=False)
        self.assertEqual(status, 401)
        self.assertEqual(body['error']['code'], 'unauthenticated')

        # 404 unknown
        status, body, _ = self.request('/api/v1/inspections/UNKNOWN/progress')
        self.assertEqual(status, 404)
        self.assertEqual(body['error']['code'], 'not_found')

        # 400 invalid query / id
        for bad in ('/api/v1/inspections/../progress', '/api/v1/inspections/X/progress?a=1'):
            status, body, _ = self.request(bad)
            self.assertEqual(status, 400, bad)
            self.assertEqual(body['error']['code'], 'invalid_request', bad)

        # > 10,000 readings -> 422
        with self.storage.connection() as conn:
            conn.executemany(
                'INSERT INTO meter_readings (timestamp, device_name, value, stage, image_path, status, device_id, inspection_id) '
                'VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
                [('2026-11-18T09:00:00+09:00', 'M', 1.0, 'done', 'p.jpg', 'ok', 'D1', 'OVER-READ') for _ in range(10001)],
            )
        status, body, _ = self.request('/api/v1/inspections/OVER-READ/progress')
        self.assertEqual(status, 422)
        self.assertEqual(body['error']['code'], 'validation_failed')

        # > 10,000 manifest photos -> 422
        with self.storage.connection() as conn:
            conn.execute(
                'INSERT INTO inspections VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)',
                ('OVER-PHOTO', '超過', None, None, None, None, None, None,
                 json.dumps({'v': 1, 'inspection_id': 'OVER-PHOTO', 'photos': [{'file_name': f'p{i}.jpg', 'sha256': None} for i in range(10001)]})),
            )
        status, body, _ = self.request('/api/v1/inspections/OVER-PHOTO/progress')
        self.assertEqual(status, 422)
        self.assertEqual(body['error']['code'], 'validation_failed')

        # > 1,000 devices -> 422
        with self.storage.connection() as conn:
            conn.executemany(
                'INSERT INTO meter_readings (timestamp, device_name, value, stage, image_path, status, device_id, inspection_id) '
                'VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
                [('2026-11-18T09:00:00+09:00', f'M{i}', 1.0, 'done', 'p.jpg', 'ok', f'D{i:04d}', 'OVER-DEV') for i in range(1001)],
            )
        status, body, _ = self.request('/api/v1/inspections/OVER-DEV/progress')
        self.assertEqual(status, 422)
        self.assertEqual(body['error']['code'], 'validation_failed')
