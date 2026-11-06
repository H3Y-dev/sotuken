import http.client
import json
from pathlib import Path
import tempfile
import threading
import unittest

from manager.receiver import ReceiverServer, MAX_BODY_SIZE
from manager.routes import save_route, get_manifest
from manager.storage import Storage
from tests import test_routes_manifest as fixtures


class RoutesReceiverTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = str(Path(self.tmp.name) / 'manager.db')
        self.storage = Storage(self.db_path)
        self.route = save_route(self.storage, '巡回', [dict(id='A', name='計器')])
        self.server = ReceiverServer(('127.0.0.1', 0), 'secret', str(Path(self.tmp.name) / 'incoming'),
                                     quiet=True, db_path=self.db_path, upload_timeout=.15)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.tmp.cleanup()

    def request(self, method, path, body=None, token='secret', headers=None):
        conn = http.client.HTTPConnection(*self.server.server_address, timeout=3)
        hdr = {'Content-Type': 'application/json'}
        if token is not None:
            hdr['X-Sotuken-Token'] = token
        hdr.update(headers or {})
        conn.request(method, path, body=body, headers=hdr)
        response = conn.getresponse()
        result = response.status, json.loads(response.read())
        conn.close()
        return result

    def test_routes_auth_list_detail_and_404(self):
        for path in ['/routes', '/routes/' + self.route['route_id']]:
            self.assertEqual(self.request('GET', path, token=None)[0], 401)
            self.assertEqual(self.request('GET', path, token='wrong')[0], 401)
        self.assertEqual(self.request('GET', '/routes')[1]['routes'][0]['count'], 1)
        self.assertEqual(self.request('GET', '/routes/' + self.route['route_id'])[1], self.route)
        self.assertEqual(self.request('GET', '/routes/no-such-route')[0], 404)

    def test_manifest_auth_invalid_and_resend(self):
        path = '/inspections/I-1/manifest'
        manifest = fixtures.RoutesManifestTest.manifest(self)
        body = json.dumps(manifest).encode()
        self.assertEqual(self.request('POST', path, body, token=None)[0], 401)
        for invalid in [b'{', b'[]', b'null', b'{}', b'\xff']:
            self.assertEqual(self.request('POST', path, invalid)[0], 400)
        self.assertEqual(self.request('POST', path, body), (200, dict(ok=True, matched=0, missing_photos=['a.jpg'])))
        manifest['photos'] = []
        self.assertEqual(self.request('POST', path, json.dumps(manifest).encode())[1]['matched'], 0)
        self.assertEqual(get_manifest(self.storage, 'I-1')['photos'], [])

    def test_manifest_size_and_deadline(self):
        path = '/inspections/I-1/manifest'
        self.assertEqual(self.request('POST', path, b'', headers={'Content-Length': str(MAX_BODY_SIZE + 1)})[0], 413)
        conn = http.client.HTTPConnection(*self.server.server_address, timeout=3)
        conn.putrequest('POST', path)
        for key, value in {'X-Sotuken-Token': 'secret', 'Content-Type': 'application/json', 'Content-Length': '100'}.items():
            conn.putheader(key, value)
        conn.endheaders()
        conn.send(b'{')
        response = conn.getresponse()
        self.assertEqual(response.status, 408)
        response.read()
        conn.close()
