import hashlib
import http.client
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from manager.routes import save_manifest, save_route
from manager.storage import Storage
from pc_api.inspection_pages import InspectionPageCache, get_page_cache
from pc_api.server import PCAPI


def _make_manifest(inspection_id, photos, *, route_id=None, started_at='2026-11-18T09:00:00+09:00', name=None):
    return {
        'v': 1,
        'inspection_id': inspection_id,
        'inspection_name': name or f'点検-{inspection_id}',
        'route_id': route_id,
        'operator': '担当A',
        'place': '1F',
        'started_at': started_at or '2026-11-18T09:00:00+09:00',
        'completed_at': '2026-11-18T09:30:00+09:00',
        'missing': [],
        'extra': [],
        'photos': photos,
    }


class InspectionPagesAPITests(unittest.TestCase):
    def setUp(self):
        get_page_cache().clear()
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
        self.addCleanup(get_page_cache().clear)
        self.session_id, self.csrf_token = self._new_session()

    def _new_session(self):
        sid, csrf = self.api.sessions.exchange_launch_key(self.api.sessions.issue_launch_key())
        return sid, csrf

    def request(self, path, method='GET', *, session_id=None, auth=True, headers=None, body=None):
        conn = http.client.HTTPConnection('127.0.0.1', self.api.port, timeout=3)
        try:
            req_headers = {}
            if auth:
                sid = session_id or self.session_id
                req_headers['Cookie'] = f'pc_session={sid}'
            if headers:
                req_headers.update(headers)
            payload = json.dumps(body).encode('utf-8') if body is not None else None
            if payload is not None:
                req_headers.setdefault('Content-Type', 'application/json')
            conn.request(method, path, body=payload, headers=req_headers)
            res = conn.getresponse()
            raw = res.read()
            mime = res.getheader('Content-Type') or ''
            parsed = json.loads(raw) if raw and 'application/json' in mime else raw
            return res.status, parsed, dict(res.getheaders())
        finally:
            conn.close()

    def _insert_device(self, device_id, name, *, unit='MPa', min_val=0.0, max_val=10.0, tol_min=1.0, tol_max=5.0):
        with self.storage.connection() as conn:
            conn.execute(
                'INSERT OR REPLACE INTO devices '
                '(device_id, device_name, unit, min_value, max_value, tolerance_min, tolerance_max) '
                'VALUES (?, ?, ?, ?, ?, ?, ?)',
                (device_id, name, unit, min_val, max_val, tol_min, tol_max),
            )

    def _insert_reading(self, inspection_id, *, device_id=None, device_name='unknown', value=2.5,
                        status='ok', stage='done', image_sha256=None, device_id_source='qr',
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

    def _put_incoming(self, name, content):
        (self.incoming / name).write_bytes(content)
        return hashlib.sha256(content).hexdigest()

    def _save_manifest(self, inspection_id, photos, **kwargs):
        save_manifest(self.storage, inspection_id, _make_manifest(inspection_id, photos, **kwargs))

    def test_preview_image_ids_match_progress(self):
        self._insert_reading('photos', device_id='D1')
        self._insert_reading('photos', device_id='D2')
        with self.storage.connection() as conn:
            conn.execute("UPDATE meter_readings SET overlay_path=? WHERE device_id='D1'", (str(self.overlays / 'result.jpg'),))
            conn.execute("UPDATE meter_readings SET image_path='' WHERE device_id='D2'")
        status, listing, _ = self.request('/api/v1/inspections')
        self.assertEqual(status, 200)
        status, detail, _ = self.request('/api/v1/inspections/photos/progress')
        self.assertEqual(status, 200)
        preview = {row['key']: row for row in listing['items'][0]['preview']}
        devices = {row['key']: row for row in detail['devices']}
        for key in ('device:D1', 'device:D2'):
            for field in ('image_id', 'overlay_image_id'):
                self.assertEqual(preview[key][field], devices[key][field])
                if key == 'device:D1':
                    self.assertIsNotNone(preview[key][field])
                else:
                    self.assertIsNone(preview[key][field])

    def test_preview_does_not_expose_image_paths(self):
        self._insert_reading('photos', device_id='D1')
        with self.storage.connection() as conn:
            conn.execute("UPDATE meter_readings SET overlay_path=?", (str(self.overlays / 'result.jpg'),))
        status, listing, _ = self.request('/api/v1/inspections')
        self.assertEqual(status, 200)
        preview = listing['items'][0]['preview']
        for row in preview:
            self.assertNotIn('image_path', row)
            self.assertNotIn('overlay_path', row)
            self.assertNotIn(str(self.images / 'x.jpg'), json.dumps(row))
            self.assertNotIn(str(self.overlays / 'result.jpg'), json.dumps(row))

    def test_manifest_only_and_readings_only_listed_and_sorted(self):
        # manifestのみ (2026-11-18T10:00:00+09:00)
        sha_m = hashlib.sha256(b'missing-photo').hexdigest()
        self._save_manifest(
            'ins-manifest',
            [{'file_name': 'm1.jpg', 'sha256': sha_m, 'device_id': 'D1', 'captured_at': '2026-11-18T10:00:00+09:00'}],
            started_at='2026-11-18T10:00:00+09:00',
            name='Manifest点検',
        )
        # 履歴のみ (2026-11-18T11:00:00+09:00)
        self._insert_device('D2', 'M2')
        self._insert_reading(
            'ins-readings',
            device_id='D2',
            device_name='M2',
            value=3.0,
            captured_at='2026-11-18T11:00:00+09:00',
            inspection_name='履歴点検',
        )
        # 同時刻タイブレーク用 (id降順: ins-tie-b > ins-tie-a)
        self._save_manifest('ins-tie-a', [], started_at='2026-11-18T09:00:00+09:00')
        self._save_manifest('ins-tie-b', [], started_at='2026-11-18T09:00:00+09:00')
        # started_at欠損は末尾
        self._save_manifest('ins-nodate', [])
        with self.storage.connection() as conn:
            conn.execute(
                "UPDATE inspections SET started_at = NULL, "
                "manifest_json = json_set(manifest_json, '$.started_at', NULL) "
                "WHERE inspection_id = 'ins-nodate'"
            )

        status, body, _ = self.request('/api/v1/inspections')
        self.assertEqual(status, 200)
        self.assertEqual(body['total'], 5)
        self.assertEqual(body['all_total'], 5)
        self.assertIsNone(body['next_cursor'])
        ids = [item['id'] for item in body['items']]
        self.assertEqual(ids, ['ins-readings', 'ins-manifest', 'ins-tie-b', 'ins-tie-a', 'ins-nodate'])

        by_id = {item['id']: item for item in body['items']}
        self.assertEqual(by_id['ins-manifest']['count'], 0)
        self.assertEqual(by_id['ins-manifest']['status'], {'state': '不足あり', 'matched': 0})
        self.assertEqual(by_id['ins-manifest']['missing_photo_count'], 1)
        self.assertTrue(by_id['ins-manifest']['summary']['needs_action'])

        self.assertEqual(by_id['ins-readings']['count'], 1)
        self.assertEqual(by_id['ins-readings']['name'], '履歴点検')
        self.assertEqual(by_id['ins-readings']['status'], {'state': '受信中', 'matched': 0})
        self.assertFalse(by_id['ins-readings']['summary']['needs_action'])

    def test_preview_limits_and_needs_action_beyond_preview(self):
        # ルート上8件 (先頭6件ok, 7件目以降にfailed) + ルート外3件
        route_devs = [{'id': f'R{i}', 'name': f'Route-{i}'} for i in range(1, 9)]
        route = save_route(self.storage, 'テストルート', route_devs)
        photos = []
        for i in range(1, 9):
            did = f'R{i}'
            self._insert_device(did, f'Route-{i}')
            sha = self._put_incoming(f'r{i}.jpg', f'r-{i}'.encode())
            photos.append({'file_name': f'r{i}.jpg', 'sha256': sha, 'device_id': did, 'captured_at': '2026-11-18T09:01:00+09:00'})
            self._insert_reading(
                'ins-route',
                device_id=did,
                device_name=f'Route-{i}',
                value=None if i == 8 else 2.5,
                status='failed' if i == 8 else 'ok',
                image_sha256=sha,
                route_id=route['route_id'],
            )
        for j in range(1, 4):
            did = f'X{j}'
            self._insert_device(did, f'Extra-{j}')
            sha = self._put_incoming(f'x{j}.jpg', f'x-{j}'.encode())
            photos.append({'file_name': f'x{j}.jpg', 'sha256': sha, 'device_id': did, 'captured_at': '2026-11-18T09:02:00+09:00'})
            self._insert_reading(
                'ins-route',
                device_id=did,
                device_name=f'Extra-{j}',
                value=2.5,
                status='ok',
                image_sha256=sha,
                route_id=route['route_id'],
            )
        self._save_manifest('ins-route', photos, route_id=route['route_id'])

        # ルートなし7件 (先頭6件ok, 7件目が許容範囲外)
        for k in range(1, 8):
            did = f'N{k}'
            self._insert_device(did, f'NoRoute-{k}')
            self._insert_reading(
                'ins-noroute',
                device_id=did,
                device_name=f'NoRoute-{k}',
                value=9.0 if k == 7 else 2.5,
                status='ok',
                captured_at='2026-11-18T08:00:00+09:00',
            )

        status, body, _ = self.request('/api/v1/inspections?filter=action')
        self.assertEqual(status, 200)
        self.assertEqual(body['action_total'], 2)
        self.assertEqual(body['total'], 2)
        by_id = {item['id']: item for item in body['items']}

        # ルートあり: ルート上6件 + ルート外2件
        route_preview = by_id['ins-route']['preview']
        self.assertEqual(len(route_preview), 8)
        self.assertEqual([m['device_id'] for m in route_preview], ['R1', 'R2', 'R3', 'R4', 'R5', 'R6', 'X1', 'X2'])
        self.assertEqual(by_id['ins-route']['summary']['fail'], 1)
        self.assertTrue(by_id['ins-route']['summary']['needs_action'])

        # ルートなし: 先頭6件のみ、プレビュー外の7件目がout_of_tolerance
        noroute_preview = by_id['ins-noroute']['preview']
        self.assertEqual(len(noroute_preview), 6)
        self.assertEqual(by_id['ins-noroute']['summary']['out_of_tolerance'], 1)
        self.assertTrue(by_id['ins-noroute']['summary']['needs_action'])

    def test_pagination_no_gaps_or_dups_during_db_updates_and_resend(self):
        for i in range(1, 6):
            self._save_manifest(f'ins-{i}', [], started_at=f'2026-11-18T0{i}:00:00+09:00')

        st1, p1, _ = self.request('/api/v1/inspections?limit=2')
        self.assertEqual(st1, 200)
        self.assertEqual([x['id'] for x in p1['items']], ['ins-5', 'ins-4'])
        self.assertEqual(p1['total'], 5)
        c1 = p1['next_cursor']
        self.assertIsNotNone(c1)

        # ページング中にDBへ新規点検を追加しても、カーソル経由の続きは同じスナップショットから返る
        self._save_manifest('ins-6', [], started_at='2026-11-18T09:00:00+09:00')

        st2, p2, _ = self.request(f'/api/v1/inspections?limit=2&cursor={c1}')
        self.assertEqual(st2, 200)
        self.assertEqual([x['id'] for x in p2['items']], ['ins-3', 'ins-2'])
        c2 = p2['next_cursor']
        self.assertIsNotNone(c2)

        # カーソル再送で同じページ・同じnext_cursor
        st2_retry, p2_retry, _ = self.request(f'/api/v1/inspections?limit=2&cursor={c1}')
        self.assertEqual(st2_retry, 200)
        self.assertEqual(p2_retry, p2)

        st3, p3, _ = self.request(f'/api/v1/inspections?limit=2&cursor={c2}')
        self.assertEqual(st3, 200)
        self.assertEqual([x['id'] for x in p3['items']], ['ins-1'])
        self.assertIsNone(p3['next_cursor'])

    def test_limit_boundaries_and_invalid_queries(self):
        self._save_manifest('ins-1', [])
        self._save_manifest('ins-2', [])

        for bad_limit in (0, 201, -1):
            st, body, _ = self.request(f'/api/v1/inspections?limit={bad_limit}')
            self.assertEqual(st, 422, f'limit={bad_limit}')
            self.assertEqual(body['error']['code'], 'validation_failed')

        for good_limit in (1, 50, 200):
            st, body, _ = self.request(f'/api/v1/inspections?limit={good_limit}')
            self.assertEqual(st, 200, f'limit={good_limit}')
            self.assertEqual(len(body['items']), min(good_limit, 2))

        for bad_query in (
            'limit=abc',
            'filter=unknown',
            'foo=bar',
            'limit=1&limit=2',
            'cursor=invalid!char',
        ):
            st, body, _ = self.request(f'/api/v1/inspections?{bad_query}')
            self.assertEqual(st, 400, bad_query)
            self.assertEqual(body['error']['code'], 'invalid_request')

    def test_cursor_rejections_condition_change_other_session_and_expiry(self):
        for i in range(1, 4):
            self._save_manifest(f'ins-{i}', [], started_at=f'2026-11-18T0{i}:00:00+09:00')

        now = [1000.0]
        cache = InspectionPageCache(clock=lambda: now[0])
        with patch('pc_api.inspection_routes.get_page_cache', return_value=cache):
            st, p1, _ = self.request('/api/v1/inspections?filter=all&limit=1')
            self.assertEqual(st, 200)
            c1 = p1['next_cursor']

            # 条件変更は400
            st_f, b_f, _ = self.request(f'/api/v1/inspections?filter=action&limit=1&cursor={c1}')
            self.assertEqual(st_f, 400)
            self.assertEqual(b_f['error']['code'], 'invalid_request')

            st_l, b_l, _ = self.request(f'/api/v1/inspections?filter=all&limit=2&cursor={c1}')
            self.assertEqual(st_l, 400)
            self.assertEqual(b_l['error']['code'], 'invalid_request')

            # 別セッションのカーソルは404
            other_sid, _ = self._new_session()
            st_other, _, _ = self.request(f'/api/v1/inspections?filter=all&limit=1&cursor={c1}', session_id=other_sid)
            self.assertEqual(st_other, 404)

            # 未知の妥当形式カーソルは410
            st_unk, b_unk, _ = self.request('/api/v1/inspections?cursor=ABCDEFGHIJKLMNOPQRSTUV')
            self.assertEqual(st_unk, 410)
            self.assertEqual(b_unk['error']['code'], 'cursor_expired')

            # 60秒経過後は410 cursor_expired
            now[0] += 60.0
            st_exp, b_exp, _ = self.request(f'/api/v1/inspections?filter=all&limit=1&cursor={c1}')
            self.assertEqual(st_exp, 410)
            self.assertEqual(b_exp['error']['code'], 'cursor_expired')

    def test_snapshot_capacity_limits_per_session_and_total(self):
        for i in range(1, 4):
            self._save_manifest(f'ins-{i}', [], started_at=f'2026-11-18T0{i}:00:00+09:00')

        # セッションあたり2件まで（3件目作成で1件目が410）
        _, p1, _ = self.request('/api/v1/inspections?limit=1')
        c1 = p1['next_cursor']
        self.request('/api/v1/inspections?limit=1')
        self.request('/api/v1/inspections?limit=1')
        st, body, _ = self.request(f'/api/v1/inspections?limit=1&cursor={c1}')
        self.assertEqual(st, 410)
        self.assertEqual(body['error']['code'], 'cursor_expired')

        # サーバー全体で8件まで（別セッションで9件目作成すると最古が410）
        get_page_cache().clear()
        s_first, _ = self._new_session()
        _, pf, _ = self.request('/api/v1/inspections?limit=1', session_id=s_first)
        c_first = pf['next_cursor']
        for _ in range(8):
            sid, _ = self._new_session()
            self.request('/api/v1/inspections?limit=1', session_id=sid)
        st_ev, b_ev, _ = self.request(f'/api/v1/inspections?limit=1&cursor={c_first}', session_id=s_first)
        self.assertEqual(st_ev, 410)
        self.assertEqual(b_ev['error']['code'], 'cursor_expired')

    def test_delete_session_discards_session_cursors(self):
        self._save_manifest('ins-1', [], started_at='2026-11-18T09:00:00+09:00')
        self._save_manifest('ins-2', [], started_at='2026-11-18T08:00:00+09:00')

        st, p1, _ = self.request('/api/v1/inspections?limit=1')
        self.assertEqual(st, 200)
        c1 = p1['next_cursor']

        # DELETE /api/v1/session でセッション失効＋スナップショット破棄
        st_del, _, _ = self.request(
            '/api/v1/session',
            method='DELETE',
            headers={
                'Origin': f'http://127.0.0.1:{self.api.port}',
                'X-CSRF-Token': self.csrf_token,
            },
            body={},
        )
        self.assertEqual(st_del, 204)

        # 旧セッションは401
        st_old, _, _ = self.request(f'/api/v1/inspections?limit=1&cursor={c1}')
        self.assertEqual(st_old, 401)

        # 別セッションから旧カーソルを送っても破棄済みのため410（404ではない）
        other_sid, _ = self._new_session()
        st_after, b_after, _ = self.request(f'/api/v1/inspections?limit=1&cursor={c1}', session_id=other_sid)
        self.assertEqual(st_after, 410)
        self.assertEqual(b_after['error']['code'], 'cursor_expired')

    def test_inspections_and_readings_limit_422(self):
        for i in range(1, 4):
            self._save_manifest(f'ins-{i}', [])
        with patch('pc_api.inspection_routes._MAX_INSPECTIONS', 2):
            st, body, _ = self.request('/api/v1/inspections')
            self.assertEqual(st, 422)
            self.assertEqual(body['error']['code'], 'validation_failed')

        for j in range(3):
            self._insert_reading('ins-1', device_id=f'D{j}', device_name=f'M{j}')
        with patch('pc_api.inspection_routes._MAX_PROGRESS_READINGS', 2):
            st, body, _ = self.request('/api/v1/inspections')
            self.assertEqual(st, 422)
            self.assertEqual(body['error']['code'], 'validation_failed')

