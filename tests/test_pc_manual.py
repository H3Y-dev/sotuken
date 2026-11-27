import http.client
import json
from pathlib import Path
import tempfile
import unittest

from manager.storage import Storage
from pc_api.server import PCAPI


def ok_reader(image_path, use_vlm=False):
    return {'value': 12.5, 'stage': 'ok', 'confidence': 0.9}


def alert_reader(image_path, use_vlm=False):
    return {'value': 55.0, 'stage': 'ok'}


def failed_reader(image_path, use_vlm=False):
    return {'stage': 'center_failed', 'value': None}


class PCManualReadingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.images = root / 'images'
        self.images.mkdir()
        self.db_path = root / 'manager.db'
        Storage(str(self.db_path))
        self.api = PCAPI(self.db_path, image_dirs=[self.images], port=0,
                         reader_func=ok_reader)
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
        conn = http.client.HTTPConnection('127.0.0.1', self.api.port, timeout=30)
        try:
            conn.request(method, path, body=body, headers=dict(headers or {}))
            response = conn.getresponse()
            data = response.read()
            mime = response.getheader('Content-Type') or ''
            parsed = json.loads(data) if data and 'application/json' in mime else data
            return response.status, parsed, response.headers.get_all('Set-Cookie', [])
        finally:
            conn.close()

    def _multipart(self, fields=(), files=()):
        boundary = '----sotukenboundary'
        out = bytearray()
        for name, value in fields:
            out += f'--{boundary}\r\n'.encode('utf-8')
            out += f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode('utf-8')
            out += value.encode('utf-8') + b'\r\n'
        for name, filename, data in files:
            out += f'--{boundary}\r\n'.encode('utf-8')
            out += (f'Content-Disposition: form-data; name="{name}"; '
                    f'filename="{filename}"\r\n').encode('utf-8')
            out += b'Content-Type: application/octet-stream\r\n\r\n'
            out += data + b'\r\n'
        out += f'--{boundary}--\r\n'.encode('utf-8')
        return bytes(out), f'multipart/form-data; boundary={boundary}'

    def _post(self, fields=(), files=(), content_type=None, path='/api/v1/manual-readings',
              auth=True, headers=None, body=None):
        if body is None:
            body, inferred = self._multipart(fields, files)
        else:
            inferred = 'multipart/form-data; boundary=----sotukenboundary'
        req_headers = {}
        if auth:
            req_headers.update({'Cookie': self.cookie, 'Origin': self.origin,
                                'X-CSRF-Token': self.csrf})
        req_headers['Content-Type'] = content_type or inferred
        if headers:
            req_headers.update(headers)
        status, parsed, _ = self._raw_request(path, 'POST', headers=req_headers, body=body)
        return status, parsed

    def _default_fields(self):
        return [('device_name', 'Gauge_01'), ('threshold_min', '0'),
                ('threshold_max', '40')]

    def test_success_returns_reading(self):
        data = b'\x89PNG\r\n\x1a\nmanual'
        status, body = self._post(
            self._default_fields(), [('image', 'photo.png', data)])
        self.assertEqual(status, 201, body)
        reading = body['reading']
        self.assertEqual(reading['device_name'], 'Gauge_01')
        self.assertEqual(reading['value'], 12.5)
        self.assertEqual(reading['stage'], 'ok')
        self.assertIsNotNone(reading['image_id'])
        self.assertFalse(body['is_alert'])
        self.assertEqual(body['stage'], 'ok')
        self.assertEqual(body['value'], 12.5)

        status, image, _ = self._raw_request(
            '/api/v1/images/' + reading['image_id'],
            headers={'Cookie': self.cookie, 'Origin': self.origin})
        self.assertEqual(status, 200)
        self.assertEqual(image, data)

    def test_threshold_alert(self):
        self.api.reader_func = alert_reader
        status, body = self._post(
            self._default_fields(), [('image', 'photo.jpg', b'\xff\xd8\xffdata')])
        self.assertEqual(status, 201, body)
        self.assertTrue(body['is_alert'])
        self.assertTrue(body['alert_message'])
        self.assertEqual(body['value'], 55.0)

    def test_failed_stage_has_no_value(self):
        self.api.reader_func = failed_reader
        status, body = self._post(
            self._default_fields(), [('image', 'photo.PNG', b'\x89PNG\r\n\x1a\n')])
        self.assertEqual(status, 201, body)
        self.assertEqual(body['stage'], 'center_failed')
        self.assertIsNone(body['value'])
        self.assertIsNone(body['reading']['value'])
        self.assertFalse(body['is_alert'])

    def test_validation_failures_are_422(self):
        image = [('image', 'photo.png', b'\x89PNG\r\n\x1a\n')]
        cases = [
            [('device_name', ''), ('image', 'photo.png', b'x')],
            [('device_name', 'bad\nname'), ('image', 'photo.png', b'x')],
            [('device_name', 'G'), ('threshold_min', 'nan'), ('image', 'photo.png', b'x')],
            [('device_name', 'G'), ('threshold_max', 'inf'), ('image', 'photo.png', b'x')],
            [('device_name', 'G'), ('threshold_min', 'abc'), ('image', 'photo.png', b'x')],
            [('device_name', 'G'), ('threshold_min', '10'), ('threshold_max', '5'),
             ('image', 'photo.png', b'x')],
            [('device_name', 'G'), ('image', 'photo.gif', b'x')],
            [('device_name', 'G'), ('image', 'photo', b'x')],
            [('device_name', 'G'), ('image', 'photo.png', b'')],
        ]
        for fields in cases:
            text = [(n, v) for n, v, *_ in fields if n != 'image']
            files = [(n, v, d) for n, v, *rest in fields if n == 'image' for d in rest]
            status, body = self._post(text, files)
            self.assertEqual(status, 422, fields)
            self.assertEqual(body['error']['code'], 'validation_failed')

    def test_bad_requests_are_400(self):
        image = [('image', 'photo.png', b'\x89PNG\r\n\x1a\n')]
        cases = [
            ([('device_name', 'G')], []),
            ([('device_name', 'G'), ('unknown', 'x')], image),
            ([('device_name', 'G'), ('device_name', 'H')], image),
            ([('device_name', 'G')], image + [('image', 'other.png', b'x')]),
        ]
        for text, files in cases:
            status, body = self._post(text, files)
            self.assertEqual(status, 400, (text, files))
            self.assertEqual(body['error']['code'], 'invalid_request')

        status, body = self._post(
            self._default_fields(), image, content_type='application/json',
            body=b'{}')
        self.assertEqual(status, 400)
        self.assertEqual(body['error']['code'], 'invalid_request')

        status, body = self._post(
            self._default_fields(), image, path='/api/v1/manual-readings?x=1')
        self.assertEqual(status, 400)
        self.assertEqual(body['error']['code'], 'invalid_request')

    def test_auth_csrf_origin_enforced(self):
        fields = self._default_fields()
        image = [('image', 'photo.png', b'\x89PNG\r\n\x1a\n')]

        status, body = self._post(fields, image, auth=False)
        self.assertEqual(status, 401)
        self.assertEqual(body['error']['code'], 'unauthenticated')

        status, body = self._post(fields, image, headers={'X-CSRF-Token': ''})
        self.assertEqual(status, 403)
        self.assertEqual(body['error']['code'], 'forbidden_origin')

        status, body = self._post(fields, image, headers={'Origin': 'http://evil.example'})
        self.assertEqual(status, 403)
        self.assertEqual(body['error']['code'], 'forbidden_origin')

        body_bytes, _ = self._multipart(fields, image)
        status, body = self._post(
            auth=False, body=body_bytes,
            headers={'Cookie': self.cookie, 'Origin': self.origin})
        self.assertEqual(status, 403)
        self.assertEqual(body['error']['code'], 'forbidden_origin')

    def test_too_large_is_413(self):
        conn = http.client.HTTPConnection('127.0.0.1', self.api.port, timeout=5)
        try:
            conn.putrequest('POST', '/api/v1/manual-readings')
            conn.putheader('Cookie', self.cookie)
            conn.putheader('Origin', self.origin)
            conn.putheader('X-CSRF-Token', self.csrf)
            conn.putheader('Content-Type', 'multipart/form-data; boundary=x')
            conn.putheader('Content-Length', str(20 * 1024 * 1024 + 1))
            conn.endheaders()
            response = conn.getresponse()
            body = json.loads(response.read())
            self.assertEqual(response.status, 413)
            self.assertEqual(body['error']['code'], 'too_large')
        finally:
            conn.close()


if __name__ == '__main__':
    unittest.main()
