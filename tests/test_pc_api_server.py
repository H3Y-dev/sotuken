import http.client
from contextlib import contextmanager
import json
import os
from pathlib import Path
import socket
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, patch

from manager.export import filter_readings
from manager.manager import MeterManager
from manager.storage import Storage
from pc_api import server
from pc_api.owner import Owner, OwnerConflict
from pc_api.server import PCAPI


class ServerTests(unittest.TestCase):
    @contextmanager
    def connection(self):
        conn = sqlite3.connect(self.db)
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.images = self.root / 'images'
        self.images.mkdir()
        self.picture = self.images / 'photo.png'
        self.picture.write_bytes(b'\x89PNG\r\n\x1a\nexample')
        self.db = self.root / 'manager.db'
        store = Storage(str(self.db))
        for i, (name, captured, inspection) in enumerate([
            ('A', '2026-11-11T23:30:00-02:00', 'one'),
            ('B', '2026-11-12T10:00:00+09:00', 'two'),
            ('A', '2026-11-13T00:00:00+00:00', 'one')]):
            # Populate the actual existing schema, including its defaults.
            with self.connection() as conn:
                conn.execute('INSERT INTO meter_readings (timestamp, device_name, value, stage, image_path, captured_at, inspection_id) VALUES (?, ?, ?, ?, ?, ?, ?)',
                             (captured, name, i + .5, 'done', str(self.picture), captured, inspection))
        self.expected = store.get_all_readings(include_raw=False)
        self.api = PCAPI(self.db, image_dirs=[self.images], port=0)
        self.api.start()
        self.addCleanup(self.api.stop)

    def request(self, path='/api/v1/readings', method='GET', headers=None, body=None, auth=True):
        conn = http.client.HTTPConnection('127.0.0.1', self.api.port, timeout=3)
        try:
            headers = dict(headers or {})
            if auth:
                headers.setdefault('X-PC-Token', self.api.token)
            conn.request(method, path, body=body, headers=headers)
            response = conn.getresponse()
            data = response.read()
            mime = response.getheader('Content-Type')
            return response.status, json.loads(data) if data and 'application/json' in mime else data, dict(response.getheaders())
        finally:
            conn.close()

    def test_authentication(self):
        for headers in ({}, {'X-PC-Token':'wrong'}, {'X-Sotuken-Token':self.api.token},
                        {'X-PC-Token':self.api.token, 'X-Sotuken-Token':'phone'}):
            status, body, _ = self.request(headers=headers, auth=False)
            self.assertEqual(status, 401)
            self.assertEqual(body['error']['code'], 'unauthenticated')
            self.assertTrue(body['error']['request_id'])

    def test_origin_host_forwarding(self):
        for headers in ({'Host':'localhost:8766'}, {'Origin':'null'}, {'Origin':'https://evil.example'},
                        {'Forwarded':'host=evil'}, {'X-Forwarded-Host':'evil'}):
            self.assertEqual(self.request(headers=headers)[0], 403)
        self.assertEqual(self.request(headers={'Origin':f'http://127.0.0.1:{self.api.port}'})[0], 200)
        self.assertEqual(self.request('/', headers={'Host':'evil'}, auth=False)[0], 403)

    def test_unsupported_methods_authenticate(self):
        for method in ('HEAD', 'OPTIONS', 'PUT', 'PATCH', 'TRACE'):
            self.assertEqual(self.request(method=method,auth=False)[0],401)
            self.assertEqual(self.request(method=method)[0],400)

    def test_filter_parity_and_order(self):
        from datetime import date
        for query, kwargs in [('', {}), ('?device_name=A', {'device_name':'A'}),
                              ('?inspection_id=one', {'inspection_id':'one'}),
                              ('?date_from=2026-11-12&date_to=2026-11-12', {'date_from':date(2026,11,12), 'date_to':date(2026,11,12)}),
                              ('?device_name=A&inspection_id=one&date_to=2026-11-12', {'device_name':'A','inspection_id':'one','date_to':date(2026,11,12)})]:
            expected = filter_readings(self.expected, **kwargs)
            status, body, headers = self.request('/api/v1/readings' + query)
            self.assertEqual(status, 200)
            self.assertEqual(body['total'], len(expected))
            self.assertEqual([(r['id'], r['value']) for r in body['items']], [(str(r.id),r.value) for r in expected])
            self.assertNotIn('raw_data', str(body))
            self.assertNotIn(str(self.root), str(body))
            self.assertNotIn('Access-Control-Allow-Origin', headers)
            self.assertEqual(headers['Cache-Control'], 'no-store')

    def test_validation(self):
        for query, code in [('?sort=x',400), ('?device_name=A&device_name=B',400),
                            ('?date_from=bad',422), ('?date_from=2026-11-13&date_to=2026-11-12',422),
                            ('?device_name=' + 'a'*257,422), ('?inspection_id=' + 'a'*129,422)]:
            self.assertEqual(self.request('/api/v1/readings' + query)[0], code)

    def test_limit(self):
        row = self.expected[0]
        with patch.object(self.api.storage, 'readings', return_value=[row]*10001):
            self.assertEqual(self.request()[0], 422)
        with patch.object(self.api.storage, 'readings', return_value=[row]*10000):
            self.assertEqual(self.request()[1]['total'],10000)

    def test_invalid_timestamp_and_nonfinite(self):
        with self.connection() as conn:
            conn.execute("UPDATE meter_readings SET captured_at='broken' WHERE id=1")
        status, body, _ = self.request()
        self.assertEqual(status,503)
        self.assertEqual(body['error']['code'],'data_invalid')
        row = self.expected[0]
        row.value, row.confidence = float('inf'), float('nan')
        self.assertIsNone(self.api.dto(row)['value'])
        self.assertIsNone(self.api.dto(row)['confidence'])

    def test_detail_and_missing(self):
        self.assertEqual(self.request('/api/v1/readings/1')[1]['id'], '1')
        for key in ('999', 'no', '../1'):
            self.assertEqual(self.request('/api/v1/readings/' + key)[0],404)

    def image_request(self, stored):
        with self.connection() as conn:
            conn.execute('UPDATE meter_readings SET image_path=? WHERE id=1', (str(stored),))
        image_id = self.request('/api/v1/readings/1')[1]['image_id']
        return self.request('/api/v1/images/' + image_id)

    def test_images_and_escape(self):
        self.assertEqual(self.image_request(self.picture)[1],self.picture.read_bytes())
        outside = self.root / 'outside.png'
        outside.write_bytes(b'outside')
        for stored in (outside, self.images / '..' / 'outside.png', self.images/'missing.png',
                       '\\\\server\\share\\file.png', str(self.picture) + ':ads', self.images/'photo.txt'):
            self.assertEqual(self.image_request(stored)[0],404)
        self.assertEqual(self.request('/api/v1/images/' + str(self.picture))[0],404)
        with self.connection() as conn:
            conn.execute('UPDATE meter_readings SET overlay_path=? WHERE id=2', (str(self.picture),))
        row = self.request('/api/v1/readings/2')[1]
        self.assertNotEqual(row['image_id'], row['overlay_image_id'])
        self.assertEqual(self.request('/api/v1/images/' + row['overlay_image_id'])[0],200)

    def test_link_escape(self):
        outside = self.root / 'outside'
        outside.mkdir()
        (outside/'photo.png').write_bytes(b'outside')
        link = self.images/'linked'
        try:
            link.symlink_to(outside, target_is_directory=True)
        except OSError:
            if os.name != 'nt':
                self.skipTest('Symlink not permitted')
            result = subprocess.run(['cmd','/c','mklink','/J',str(link),str(outside)], capture_output=True)
            if result.returncode:
                self.skipTest('Neither symlink nor junction permitted')
        self.addCleanup(lambda: os.rmdir(link))
        self.assertEqual(self.image_request(link/'photo.png')[0],404)

    def test_opened_handle_rechecked(self):
        with patch('pc_api.server.opened_path', return_value=self.root/'outside.png'):
            self.assertEqual(self.image_request(self.picture)[0],404)

    def test_db_read_only_and_busy(self):
        with self.api.storage._get_connection() as conn:
            self.assertEqual(conn.execute('PRAGMA query_only').fetchone()[0],1)
            self.assertEqual(conn.execute('PRAGMA busy_timeout').fetchone()[0],250)
            self.assertEqual(conn.execute('PRAGMA journal_mode').fetchone()[0],'delete')
            with self.assertRaises(sqlite3.OperationalError):
                conn.execute('DELETE FROM meter_readings')
        conn.close()
        with self.connection() as writer:
            writer.execute('BEGIN EXCLUSIVE')
            status, body, headers = self.request()
            self.assertEqual(status,503)
            self.assertEqual(body['error']['code'],'db_busy')
            self.assertEqual(headers['Retry-After'],'1')

    def test_duplicate_api(self):
        other = PCAPI(self.db, image_dirs=[self.images], port=0)
        with self.assertRaises(OwnerConflict):
            other.start()
        other = PCAPI(self.root/'other.db', image_dirs=[self.images], port=self.api.port)
        with self.assertRaises(OSError):
            other.start()
        other.lock.acquire()
        other.lock.release()
        self.api.stop()
        replacement = PCAPI(self.db, image_dirs=[self.images], port=0)
        replacement.start()
        replacement.stop()

    def test_static_and_token(self):
        status, body, headers = self.request('/',auth=False)
        self.assertEqual(status,200)
        self.assertIn(self.api.token.encode(),body)
        self.assertNotIn(b'X-Internal',body)
        self.assertIn("frame-ancestors 'none'",headers['Content-Security-Policy'])
        static = self.root/'dist'
        static.mkdir()
        (static/'index.html').write_bytes(b'<html><head></head><body>React</body></html>')
        (static/'app.js').write_bytes(b'console.log(1)')
        self.api.static_dir = static
        self.assertIn(b'React',self.request('/')[1])
        self.assertEqual(self.request('/app.js',auth=False)[1],b'console.log(1)')
        self.assertEqual(self.request('/%2e%2e/manager.db',auth=False)[0],404)

    def test_owner_unavailable(self):
        with socket.socket() as sock:
            sock.bind(('127.0.0.1',0))
            self.api.owner_port = sock.getsockname()[1]
        for path in ('runtime','pairing','usb/status'):
            status, body, _ = self.request('/api/v1/' + path)
            self.assertEqual(status,503)
            self.assertEqual(body['error']['code'],'owner_unavailable')

    def assertPairingShape(self, body, active):
        # Design section 3: Pairing type.
        self.assertEqual(set(body), {'active','payload','expires_at','remaining_seconds','owner_instance_id','observed_at'})
        self.assertIs(body['active'], active)
        self.assertIsInstance(body['remaining_seconds'], int)
        self.assertIsInstance(body['owner_instance_id'], str)
        self.assertIsInstance(body['observed_at'], str)
        if active:
            self.assertIsInstance(body['payload'], str)
            self.assertIsInstance(body['expires_at'], int)
        else:
            self.assertIsNone(body['payload'])
            self.assertIsNone(body['expires_at'])
            self.assertEqual(body['remaining_seconds'], 0)

    def test_owner_relay(self):
        receiver = Mock()
        receiver.pairing_status.return_value = None
        info = dict(running=True, server=receiver, thread=None, url='http://192.168.1.2:8765', external_process=False)
        with patch('pc_api.owner.init_receiver_for_app',return_value=info):
            owner = Owner(self.db, self.root/'incoming',port=0)
            owner.start()
            try:
                self.api.owner_port, self.api.internal_key = owner.port, owner.internal_key
                runtime = self.request('/api/v1/runtime')[1]
                self.assertTrue(runtime['receiver_running'])
                self.assertEqual(runtime['owner_instance_id'],owner.instance_id)
                self.assertFalse(self.request('/api/v1/usb/status')[1]['enabled'])
                status, inactive, _ = self.request('/api/v1/pairing','POST',body='{}')
                self.assertEqual(status,200)
                self.assertPairingShape(inactive, active=False)
                receiver.start_pairing.assert_called_once_with(info['url'])
                receiver.pairing_status.return_value = {'payload':{'url':info['url'],'expires_at':123},'remaining':10}
                receiver.pairing_payload.return_value = 'SOTUKEN-PAIR:sample'
                active = self.request('/api/v1/pairing')[1]
                self.assertPairingShape(active, active=True)
                self.assertEqual((active['payload'], active['expires_at'], active['remaining_seconds']),
                                 ('SOTUKEN-PAIR:sample', 123, 10))
                self.assertEqual(self.request('/api/v1/pairing','POST',body='{}')[0],409)
                self.assertEqual(self.request('/api/v1/pairing','POST',body='{"url":"evil"}')[0],400)
                self.assertEqual(self.request('/api/v1/pairing','DELETE')[0],204)
                receiver.cancel_pairing.assert_called()
                owner.usb = Mock()
                owner.usb.status.return_value = {'running':True,'devices':['test']}
                self.assertTrue(self.request('/api/v1/usb/status')[1]['enabled'])
                self.assertEqual(self.request('/api/v1/usb/status')[1]['devices'],['test'])
            finally:
                owner.stop()

    def raw(self, *lines):
        """Send hand-written HTTP lines (http.client cannot repeat Host) and return the status code."""
        with socket.create_connection(('127.0.0.1', self.api.port), timeout=3) as sock:
            sock.sendall(('\r\n'.join(lines) + '\r\n\r\n').encode())
            sock.shutdown(socket.SHUT_WR)
            data = b''
            while chunk := sock.recv(4096):
                data += chunk
        return int(data.split(b' ', 2)[1])

    def test_host_variants_and_proxy_headers(self):
        host = f'Host: 127.0.0.1:{self.api.port}'
        token = f'X-PC-Token: {self.api.token}'
        get = 'GET /api/v1/readings HTTP/1.1'
        self.assertEqual(self.raw(get, host, token, 'Connection: close'), 200)
        self.assertEqual(self.raw(get, host, host, token, 'Connection: close'), 403)
        self.assertEqual(self.raw(get, host, 'Host: evil.example', token, 'Connection: close'), 403)
        self.assertEqual(self.raw(get, 'Host: 127.0.0.1', token, 'Connection: close'), 403)
        self.assertEqual(self.request(headers={'Host':'127.0.0.1'})[0], 403)
        self.assertEqual(self.request(headers={'Host':f'127.0.0.1:{self.api.port + 1}'})[0], 403)
        for name, value in (('X-Forwarded-For','10.0.0.1'), ('X-Forwarded-Proto','https')):
            self.assertEqual(self.request(headers={name: value})[0], 403)
        self.assertEqual(self.request('/', headers={'X-Forwarded-For':'10.0.0.1'}, auth=False)[0], 403)

    def test_storage_constructor_never_called(self):
        with patch.object(Storage, '__init__', return_value=None) as init:
            self.assertEqual(self.request()[0], 200)
            self.assertEqual(self.request('/api/v1/readings/1')[0], 200)
            self.assertEqual(self.image_request(self.picture)[0], 200)
        init.assert_not_called()

    def test_row_reads_do_not_load_all_readings(self):
        with self.connection() as conn:
            conn.execute('UPDATE meter_readings SET overlay_path=? WHERE id=1', (str(self.picture),))
        with patch.object(self.api.storage, 'readings', side_effect=AssertionError('full scan')):
            row = self.request('/api/v1/readings/1')
            self.assertEqual(row[0], 200)
            self.assertEqual(self.request('/api/v1/images/' + row[1]['image_id'])[0], 200)
            self.assertEqual(self.request('/api/v1/images/' + row[1]['overlay_image_id'])[0], 200)
            for key in ('999-o-' + 'a' * 64, '1-o-bad', '1-x-' + 'a' * 64, '1-v', '-1-o-a'):
                self.assertEqual(self.request('/api/v1/images/' + key)[0], 404)
        # A signature for one row/kind must not open another row or kind.
        first = row[1]['image_id'].split('-')
        self.assertEqual(self.request('/api/v1/images/' + '-'.join(['2', first[1], first[2]]))[0], 404)
        self.assertEqual(self.request('/api/v1/images/' + '-'.join([first[0], 'v', first[2]]))[0], 404)

    def test_mapper_matches_streamlit_history(self):
        with self.connection() as conn:
            conn.execute("INSERT INTO meter_readings (timestamp, device_name, value, stage, image_path, status, confidence, "
                         "device_id, inspection_name, route_id, reading_id, received_at, raw_data_json) "
                         "VALUES ('2026-11-12T09:00:00', '名前あり', NULL, 'failed', 'missing.png', 'failed', 0.25, "
                         "'D1', '点検', 'R1', 'rid', '2026-11-12T09:00:05', '{\"secret\": 1}')")
        history = MeterManager(str(self.db)).get_history(include_raw=False)
        mine = self.api.storage.readings()
        self.assertEqual([vars(r) for r in mine], [vars(r) for r in history])
        self.assertEqual(len(mine), 4)
        self.assertEqual([r.id for r in mine], [4, 3, 2, 1])
        self.assertTrue(all(r.raw_data is None for r in mine))
        for query, kwargs in [('', {}), ('?device_name=%E5%90%8D%E5%89%8D%E3%81%82%E3%82%8A', {'device_name':'名前あり'})]:
            expected = filter_readings(history, **kwargs)
            body = self.request('/api/v1/readings' + query)[1]
            self.assertEqual([(i['id'], i['value']) for i in body['items']], [(str(r.id), r.value) for r in expected])
            self.assertEqual(body['total'], len(expected))
        self.assertIsNone(self.request('/api/v1/readings/4')[1]['value'])

    def test_unexpected_error_is_500_without_details(self):
        with patch.object(self.api, 'dispatch', side_effect=RuntimeError('secret C:\\private\\key')):
            status, body, headers = self.request()
        self.assertEqual(status, 500)
        self.assertEqual(body['error']['code'], 'internal_error')
        self.assertNotIn('secret', json.dumps(body))
        self.assertNotIn('Retry-After', headers)

    def test_image_roots_are_required(self):
        for roots in ((), ('',), (self.images, ''), (Path(self.images.anchor),)):
            with self.assertRaises(ValueError):
                PCAPI(self.db, image_dirs=roots, port=0)
        with patch.object(sys, 'argv', ['pc_api.server', '--db', str(self.db), '--internal-key-file', 'k']), \
                patch('sys.stderr'), self.assertRaises(SystemExit) as stopped:
            server.main()  # --incoming-dir/--images-dir/--overlays-dir missing
        self.assertEqual(stopped.exception.code, 2)
        args = ['--incoming-dir', 'a', '--images-dir', 'b', '--overlays-dir', 'c', '--internal-key-file', 'k']
        with patch.object(sys, 'argv', ['pc_api.server', '--db', str(self.root / 'none.db')] + args), \
                patch('sys.stderr'), self.assertRaises(SystemExit) as stopped:
            server.main()
        self.assertEqual(stopped.exception.code, 2)
        self.assertFalse((self.root / 'none.db').exists())

    def test_api_reads_during_ingest(self):
        # Phase 1: the writer holds the DB (journal_mode=delete) -> 503 db_busy, then a retry sees the row.
        committed, release = threading.Event(), threading.Event()

        def hold():
            writer = sqlite3.connect(self.db, timeout=5, isolation_level=None)
            try:
                writer.execute('BEGIN EXCLUSIVE')
                writer.execute("INSERT INTO meter_readings (timestamp, device_name, value, stage, image_path) "
                               "VALUES ('2026-11-14T00:00:00', 'held', 9, 'done', 'x.png')")
                committed.set()
                release.wait(5)
                writer.execute('COMMIT')
            finally:
                writer.close()
        holder = threading.Thread(target=hold)
        holder.start()
        self.assertTrue(committed.wait(5))
        status, body, headers = self.request()
        self.assertEqual((status, body['error']['code'], headers['Retry-After']), (503, 'db_busy', '1'))
        release.set()
        holder.join()
        for _ in range(20):
            status, body, _ = self.request()
            if status == 200:
                break
            self.assertEqual(status, 503)
            time.sleep(.05)
        self.assertEqual((status, body['total']), (200, 4))
        self.assertEqual(body['items'][0]['device_name'], 'held')

        # Phase 2: a burst of separately committed inserts while polling. Every answer is a
        # consistent 200 (ids 1..max, no gap) or 503 db_busy; after the burst nothing is missing.
        count, done, outcomes = 150, threading.Event(), []

        def ingest():
            writer = sqlite3.connect(self.db, timeout=10)
            try:
                for n in range(count):
                    with writer:
                        writer.execute("INSERT INTO meter_readings (timestamp, device_name, value, stage, image_path) "
                                       "VALUES ('2026-11-15T00:00:00', 'burst', ?, 'done', 'x.png')", (n,))
                    time.sleep(.01)  # ingest takes ~10 s per photo; this is still far faster
            finally:
                writer.close()
                done.set()
        thread = threading.Thread(target=ingest)
        thread.start()
        try:
            while not done.is_set():
                status, body, _ = self.request()
                outcomes.append(status)
                if status == 200:
                    ids = sorted(int(item['id']) for item in body['items'])
                    self.assertEqual(ids, list(range(1, len(ids) + 1)))
                else:
                    self.assertEqual((status, body['error']['code']), (503, 'db_busy'))
        finally:
            thread.join()
        for _ in range(20):
            status, body, _ = self.request()
            if status == 200:
                break
            time.sleep(.05)
        self.assertEqual(status, 200)
        self.assertEqual(sorted(int(i['id']) for i in body['items']), list(range(1, 4 + count + 1)))
        print(f'[ingest] polls={len(outcomes)} 200={outcomes.count(200)} 503={outcomes.count(503)}', file=sys.stderr)


if __name__ == '__main__':
    unittest.main()
