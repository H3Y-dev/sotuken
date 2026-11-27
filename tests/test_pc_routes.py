import http.client
import json
from pathlib import Path
import tempfile
import unittest
from urllib.parse import quote

from manager.storage import Storage
from pc_api.server import PCAPI


def _route_body(name='Line A', devices=None):
    if devices is None:
        devices = [
            {'id': 'G-1', 'name': 'Pressure Gauge'},
            {'id': 'G-2', 'name': 'Temperature Gauge'},
        ]
    return {'name': name, 'devices': devices}


class PCRoutesTests(unittest.TestCase):
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
        raw = json.dumps(body).encode('utf-8') if isinstance(body, dict) else body
        status, parsed, _ = self._raw_request(path, method=method, headers=req_headers, body=raw)
        return status, parsed

    def test_crud_and_qr_png(self):
        status, body = self._authed('/api/v1/routes')
        self.assertEqual(status, 200)
        self.assertEqual(body, {'items': []})

        status, created = self._authed('/api/v1/routes', method='POST', body=_route_body())
        self.assertEqual(status, 201)
        self.assertIn('route_id', created)
        self.assertEqual(created['name'], 'Line A')
        self.assertEqual([d['id'] for d in created['devices']], ['G-1', 'G-2'])
        self.assertIsInstance(created['qr_payload'], str)
        self.assertTrue(created['qr_payload'].startswith('SOTUKEN-ROUTE:'))
        route_id = created['route_id']

        status, listed = self._authed('/api/v1/routes')
        self.assertEqual(status, 200)
        self.assertEqual(len(listed['items']), 1)
        self.assertEqual(listed['items'][0]['route_id'], route_id)
        self.assertEqual(listed['items'][0]['count'], 2)
        self.assertEqual(set(listed['items'][0]), {'route_id', 'name', 'count', 'updated_at'})

        status, detail = self._authed(f'/api/v1/routes/{quote(route_id)}')
        self.assertEqual(status, 200)
        self.assertEqual(detail['route_id'], route_id)
        self.assertEqual(detail['name'], 'Line A')
        self.assertEqual([d['id'] for d in detail['devices']], ['G-1', 'G-2'])
        self.assertIn('updated_at', detail)
        self.assertEqual(detail['qr_payload'], created['qr_payload'])

        status, updated = self._authed(
            f'/api/v1/routes/{quote(route_id)}',
            method='PUT',
            body=_route_body(name='Line B', devices=[{'id': 'G-3', 'name': 'Flow Meter'}]),
        )
        self.assertEqual(status, 200)
        self.assertEqual(updated['route_id'], route_id)
        self.assertEqual(updated['name'], 'Line B')
        self.assertEqual(updated['devices'], [{'id': 'G-3', 'name': 'Flow Meter'}])

        status, png = self._authed(f'/api/v1/routes/{quote(route_id)}/qr')
        self.assertEqual(status, 200)
        self.assertIsInstance(png, bytes)
        self.assertTrue(png.startswith(b'\x89PNG'))

        status, body = self._authed(f'/api/v1/routes/{quote(route_id)}', method='DELETE', body={})
        self.assertEqual(status, 204)
        self.assertEqual(body, b'')

        status, err = self._authed(f'/api/v1/routes/{quote(route_id)}')
        self.assertEqual(status, 404)
        self.assertEqual(err['error']['code'], 'not_found')

    def test_qr_rejects_payload_over_1500_bytes(self):
        devices = [{'id': f'DEV-{i:03d}', 'name': 'N' * 64} for i in range(40)]
        status, created = self._authed('/api/v1/routes', method='POST', body=_route_body(devices=devices))
        self.assertEqual(status, 201)
        self.assertIsNone(created['qr_payload'])

        status, err = self._authed(f'/api/v1/routes/{quote(created["route_id"])}/qr')
        self.assertEqual(status, 422)
        self.assertEqual(err['error']['code'], 'validation_failed')

    def test_invalid_requests_and_ids(self):
        status, err = self._authed('/api/v1/routes?limit=1')
        self.assertEqual(status, 400)
        self.assertEqual(err['error']['code'], 'invalid_request')

        for bad_path in ('/api/v1/routes/.', '/api/v1/routes/..', '/api/v1/routes/%20bad', '/api/v1/routes/bad%2Fid'):
            for method, body in (('GET', None), ('PUT', _route_body()), ('DELETE', {})):
                status, err = self._authed(bad_path, method=method, body=body)
                self.assertEqual(status, 400, (bad_path, method))
                self.assertEqual(err['error']['code'], 'invalid_request')

        status, err = self._authed('/api/v1/routes/missing-id')
        self.assertEqual(status, 404)
        self.assertEqual(err['error']['code'], 'not_found')

        status, err = self._authed('/api/v1/routes/missing-id', method='PUT', body=_route_body())
        self.assertEqual(status, 404)
        self.assertEqual(err['error']['code'], 'not_found')

        status, err = self._authed('/api/v1/routes/missing-id', method='DELETE', body={})
        self.assertEqual(status, 404)
        self.assertEqual(err['error']['code'], 'not_found')

        status, err = self._authed('/api/v1/routes/extra/segment')
        self.assertEqual(status, 404)
        self.assertEqual(err['error']['code'], 'not_found')

        status, err = self._authed('/api/v1/routes', method='PATCH', body={})
        self.assertEqual(status, 400)
        self.assertEqual(err['error']['code'], 'invalid_request')

    def test_body_structure_is_400(self):
        cases = [
            {},
            {'name': 'Only name'},
            {'devices': []},
            {'name': 'X', 'devices': [], 'extra': 1},
            {'name': 'X', 'devices': 'nope'},
            {'name': 'X', 'devices': [{'id': 'G-1'}]},
            {'name': 'X', 'devices': [{'id': 'G-1', 'name': 'A', 'extra': 1}]},
            {'name': 'X', 'devices': ['G-1']},
        ]
        for case in cases:
            status, err = self._authed('/api/v1/routes', method='POST', body=case)
            self.assertEqual(status, 400, case)
            self.assertEqual(err['error']['code'], 'invalid_request')

        status, created = self._authed('/api/v1/routes', method='POST', body=_route_body())
        self.assertEqual(status, 201)
        for case in cases:
            status, err = self._authed(
                f'/api/v1/routes/{quote(created["route_id"])}', method='PUT', body=case
            )
            self.assertEqual(status, 400, case)
            self.assertEqual(err['error']['code'], 'invalid_request')

    def test_validation_failures_are_422(self):
        cases = [
            {'name': '', 'devices': [{'id': 'G-1', 'name': 'A'}]},
            {'name': '   ', 'devices': [{'id': 'G-1', 'name': 'A'}]},
            {'name': 'X', 'devices': []},
            {'name': 'X', 'devices': [{'id': 'G-1', 'name': 'A'}, {'id': 'G-1', 'name': 'B'}]},
            {'name': 'X', 'devices': [{'id': 'bad id', 'name': 'A'}]},
            {'name': 'X', 'devices': [{'id': 'G-1', 'name': ''}]},
        ]
        for case in cases:
            status, err = self._authed('/api/v1/routes', method='POST', body=case)
            self.assertEqual(status, 422, case)
            self.assertEqual(err['error']['code'], 'validation_failed')

        status, created = self._authed('/api/v1/routes', method='POST', body=_route_body())
        self.assertEqual(status, 201)
        for case in cases:
            status, err = self._authed(
                f'/api/v1/routes/{quote(created["route_id"])}', method='PUT', body=case
            )
            self.assertEqual(status, 422, case)
            self.assertEqual(err['error']['code'], 'validation_failed')

    def test_auth_csrf_origin_and_content_type_enforcement(self):
        status, err, _ = self._raw_request('/api/v1/routes')
        self.assertEqual(status, 401)
        self.assertEqual(err['error']['code'], 'unauthenticated')

        status, err, _ = self._raw_request(
            '/api/v1/routes',
            method='POST',
            headers={'Origin': self.origin, 'Content-Type': 'application/json'},
            body=json.dumps(_route_body()).encode('utf-8'),
        )
        self.assertEqual(status, 401)
        self.assertEqual(err['error']['code'], 'unauthenticated')

        valid_post = json.dumps(_route_body()).encode('utf-8')
        for bad_headers in (
            {'Cookie': self.cookie, 'Content-Type': 'application/json'},
            {'Cookie': self.cookie, 'Origin': 'http://evil.example', 'X-CSRF-Token': self.csrf, 'Content-Type': 'application/json'},
            {'Cookie': self.cookie, 'Origin': self.origin, 'X-CSRF-Token': 'wrong', 'Content-Type': 'application/json'},
        ):
            status, err, _ = self._raw_request('/api/v1/routes', method='POST', headers=bad_headers, body=valid_post)
            self.assertEqual(status, 403)
            self.assertEqual(err['error']['code'], 'forbidden_origin')

        status, err, _ = self._raw_request(
            '/api/v1/routes',
            method='POST',
            headers={
                'Cookie': self.cookie,
                'Origin': self.origin,
                'X-CSRF-Token': self.csrf,
                'Content-Type': 'text/plain',
            },
            body=valid_post,
        )
        self.assertEqual(status, 400)
        self.assertEqual(err['error']['code'], 'invalid_request')


if __name__ == '__main__':
    unittest.main()
