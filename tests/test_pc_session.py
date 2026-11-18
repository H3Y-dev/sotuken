import http.client
import json
from pathlib import Path
import tempfile
import unittest

from manager.storage import Storage
from pc_api.server import PCAPI


class FakeClock:
    def __init__(self, now=1000.0):
        self.now = now

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


class PCSessionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        images = root / 'images'
        images.mkdir()
        db = root / 'manager.db'
        Storage(str(db))
        self.clock = FakeClock()
        self.api = PCAPI(db, image_dirs=[images], port=0, clock=self.clock)
        self.api.start()
        self.addCleanup(self.api.stop)
        self.origin = f'http://127.0.0.1:{self.api.port}'

    def request(self, path='/api/v1/session', method='GET', headers=None, body=None):
        conn = http.client.HTTPConnection('127.0.0.1', self.api.port, timeout=3)
        try:
            conn.request(method, path, body=body, headers=dict(headers or {}))
            response = conn.getresponse()
            data = response.read()
            mime = response.getheader('Content-Type') or ''
            parsed = json.loads(data) if data and 'application/json' in mime else data
            return response.status, parsed, dict(response.getheaders()), response.headers.get_all('Set-Cookie', [])
        finally:
            conn.close()

    def exchange(self, launch_key):
        return self.request(
            '/api/v1/session',
            method='POST',
            headers={'Origin': self.origin, 'Content-Type': 'application/json'},
            body=json.dumps({'launch_key': launch_key}).encode('utf-8'),
        )

    def cookie_pair(self, set_cookies):
        self.assertEqual(len(set_cookies), 1)
        return set_cookies[0].split(';', 1)[0]

    def test_exchange_sets_cookie_attributes_and_get_restores_csrf(self):
        key = self.api.sessions.issue_launch_key()
        status, body, _, set_cookies = self.exchange(key)
        self.assertEqual(status, 200)
        self.assertIsInstance(body['csrf_token'], str)
        self.assertTrue(body['csrf_token'])

        attrs = [p.strip() for p in set_cookies[0].split(';')]
        self.assertIn('HttpOnly', attrs)
        self.assertIn('SameSite=Strict', attrs)
        self.assertIn('Path=/', attrs)

        cookie = self.cookie_pair(set_cookies)
        status, restored, _, _ = self.request('/api/v1/session', method='GET', headers={'Cookie': cookie})
        self.assertEqual(status, 200)
        self.assertEqual(restored['csrf_token'], body['csrf_token'])

    def test_launch_key_reuse_rejected(self):
        key = self.api.sessions.issue_launch_key()
        status, _, _, _ = self.exchange(key)
        self.assertEqual(status, 200)

        status, body, _, set_cookies = self.exchange(key)
        self.assertEqual(status, 401)
        self.assertEqual(body['error']['code'], 'unauthenticated')
        self.assertEqual(body['error']['message'], 'unauthenticated')
        self.assertTrue(body['error']['request_id'])
        self.assertEqual(set_cookies, [])

    def test_launch_key_expiry_boundary(self):
        before_key = self.api.sessions.issue_launch_key()
        self.clock.advance(59.999)
        status, _, _, _ = self.exchange(before_key)
        self.assertEqual(status, 200)

        expired_key = self.api.sessions.issue_launch_key()
        self.clock.advance(60.0)
        status, body, _, _ = self.exchange(expired_key)
        self.assertEqual(status, 401)
        self.assertEqual(body['error']['code'], 'unauthenticated')

    def test_non_json_content_type_rejected(self):
        key = self.api.sessions.issue_launch_key()
        payload = json.dumps({'launch_key': key}).encode('utf-8')
        for headers in (
            {'Origin': self.origin},
            {'Origin': self.origin, 'Content-Type': 'text/plain'},
            {'Origin': self.origin, 'Content-Type': 'application/x-www-form-urlencoded'},
            {'Origin': self.origin, 'Content-Type': 'application/json; charset=shift_jis'},
        ):
            status, body, _, _ = self.request('/api/v1/session', method='POST', headers=headers, body=payload)
            self.assertEqual(status, 400)
            self.assertEqual(body['error']['code'], 'invalid_request')

    def test_different_or_missing_origin_rejected(self):
        key = self.api.sessions.issue_launch_key()
        payload = json.dumps({'launch_key': key}).encode('utf-8')
        for headers in (
            {'Content-Type': 'application/json'},
            {'Origin': 'http://evil.example', 'Content-Type': 'application/json'},
            {'Origin': 'null', 'Content-Type': 'application/json'},
        ):
            status, body, _, _ = self.request('/api/v1/session', method='POST', headers=headers, body=payload)
            self.assertEqual(status, 403)
            self.assertEqual(body['error']['code'], 'forbidden_origin')

        status, body, _, set_cookies = self.exchange(key)
        self.assertEqual(status, 200)
        cookie = self.cookie_pair(set_cookies)
        for headers in (
            {'Cookie': cookie, 'X-CSRF-Token': body['csrf_token']},
            {'Origin': 'http://evil.example', 'Cookie': cookie, 'X-CSRF-Token': body['csrf_token']},
        ):
            status, err, _, _ = self.request('/api/v1/session', method='DELETE', headers=headers)
            self.assertEqual(status, 403)
            self.assertEqual(err['error']['code'], 'forbidden_origin')

    def test_missing_or_mismatched_csrf_rejected(self):
        key = self.api.sessions.issue_launch_key()
        _, body, _, set_cookies = self.exchange(key)
        cookie = self.cookie_pair(set_cookies)

        for headers in (
            {'Origin': self.origin, 'Cookie': cookie},
            {'Origin': self.origin, 'Cookie': cookie, 'X-CSRF-Token': 'wrong-csrf'},
        ):
            status, err, _, _ = self.request('/api/v1/session', method='DELETE', headers=headers)
            self.assertEqual(status, 403)
            self.assertEqual(err['error']['code'], 'forbidden_origin')

    def test_delete_revokes_session_and_clears_cookie(self):
        key = self.api.sessions.issue_launch_key()
        _, body, _, set_cookies = self.exchange(key)
        cookie = self.cookie_pair(set_cookies)

        # DELETE without Content-Type: application/json or empty body is rejected.
        for headers, req_body in (
            ({'Origin': self.origin, 'Cookie': cookie, 'X-CSRF-Token': body['csrf_token']}, b'{}'),
            ({'Origin': self.origin, 'Cookie': cookie, 'X-CSRF-Token': body['csrf_token'], 'Content-Type': 'application/json'}, None),
        ):
            status, err, _, _ = self.request('/api/v1/session', method='DELETE', headers=headers, body=req_body)
            self.assertEqual(status, 400)
            self.assertEqual(err['error']['code'], 'invalid_request')

        status, del_body, _, del_cookies = self.request(
            '/api/v1/session',
            method='DELETE',
            headers={
                'Origin': self.origin,
                'Cookie': cookie,
                'X-CSRF-Token': body['csrf_token'],
                'Content-Type': 'application/json',
            },
            body=b'{}',
        )
        self.assertEqual(status, 204)
        self.assertEqual(del_body, b'')
        self.assertEqual(len(del_cookies), 1)
        self.assertIn('Max-Age=0', del_cookies[0])

        status, err, _, _ = self.request('/api/v1/session', method='GET', headers={'Cookie': cookie})
        self.assertEqual(status, 401)
        self.assertEqual(err['error']['code'], 'unauthenticated')

        status, err, _, _ = self.request(
            '/api/v1/session',
            method='DELETE',
            headers={
                'Origin': self.origin,
                'Cookie': cookie,
                'X-CSRF-Token': body['csrf_token'],
                'Content-Type': 'application/json',
            },
            body=b'{}',
        )
        self.assertEqual(status, 401)
        self.assertEqual(err['error']['code'], 'unauthenticated')

    def test_session_expiry_after_8_hours(self):
        key = self.api.sessions.issue_launch_key()
        _, body, _, set_cookies = self.exchange(key)
        cookie = self.cookie_pair(set_cookies)

        self.clock.advance(8 * 3600.0 - 0.1)
        status, restored, _, _ = self.request('/api/v1/session', method='GET', headers={'Cookie': cookie})
        self.assertEqual(status, 200)
        self.assertEqual(restored['csrf_token'], body['csrf_token'])

        self.clock.advance(0.1)
        status, err, _, _ = self.request('/api/v1/session', method='GET', headers={'Cookie': cookie})
        self.assertEqual(status, 401)
        self.assertEqual(err['error']['code'], 'unauthenticated')

    def test_session_cookie_required_for_api_and_no_pc_token_meta(self):
        status, html, _, _ = self.request('/', method='GET')
        self.assertEqual(status, 200)
        self.assertNotIn(b'<meta name="pc-token"', html)

        status, err, _, _ = self.request('/api/v1/readings', method='GET')
        self.assertEqual(status, 401)
        self.assertEqual(err['error']['code'], 'unauthenticated')

        status, err, _, _ = self.request('/api/v1/readings', method='GET', headers={'X-PC-Token': 'anything'})
        self.assertEqual(status, 401)
        self.assertEqual(err['error']['code'], 'unauthenticated')

        key = self.api.sessions.issue_launch_key()
        _, body, _, set_cookies = self.exchange(key)
        cookie = self.cookie_pair(set_cookies)

        status, readings, _, _ = self.request('/api/v1/readings', method='GET', headers={'Cookie': cookie})
        self.assertEqual(status, 200)
        self.assertEqual(readings['total'], 0)

        status, err, _, _ = self.request(
            '/api/v1/pairing',
            method='POST',
            headers={'Origin': self.origin, 'Cookie': cookie},
            body=b'{}',
        )
        self.assertEqual(status, 403)
        self.assertEqual(err['error']['code'], 'forbidden_origin')

        status, err, _, _ = self.request(
            '/api/v1/pairing',
            method='POST',
            headers={'Origin': self.origin, 'Cookie': cookie, 'X-CSRF-Token': body['csrf_token'], 'Content-Type': 'text/plain'},
            body=b'{}',
        )
        self.assertEqual(status, 400)
        self.assertEqual(err['error']['code'], 'invalid_request')

        status, _, _, _ = self.request(
            '/api/v1/pairing',
            method='POST',
            headers={'Origin': self.origin, 'Cookie': cookie, 'X-CSRF-Token': body['csrf_token'], 'Content-Type': 'application/json'},
            body=b'{}',
        )
        self.assertNotIn(status, (400, 401, 403))

        for method in ('PUT', 'PATCH', 'DELETE'):
            status, err, _, _ = self.request(
                '/api/v1/pairing',
                method=method,
                headers={'Origin': self.origin, 'Cookie': cookie, 'X-CSRF-Token': body['csrf_token'], 'Content-Type': 'text/plain'},
                body=b'{}',
            )
            self.assertEqual(status, 400)
            self.assertEqual(err['error']['code'], 'invalid_request')
