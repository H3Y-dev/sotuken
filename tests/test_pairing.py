import concurrent.futures
from contextlib import chdir
import http.client
import io
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from manager.receiver import ReceiverServer, load_or_create_pc_config, pairing_qr_png
from manager.qr_label import parse_payload


class PairingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.server = ReceiverServer(('127.0.0.1', 0), 'permanent-secret', self.tmp.name,
                                     receiver_id='81c569ee-8214-4ddb-b0ae-ae0ae605f850', quiet=True)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = f'http://127.0.0.1:{self.server.server_port}'

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.tmp.cleanup()

    def request(self, token, raw=None, path='/pair', method='POST', headers=None):
        conn = http.client.HTTPConnection('127.0.0.1', self.server.server_port, timeout=3)
        body = raw if raw is not None else json.dumps({'token': token})
        conn.request(method, path, body, headers or {'Content-Type': 'application/json'})
        resp = conn.getresponse()
        result = resp.status, json.loads(resp.read())
        conn.close()
        return result

    def invite(self):
        return self.server.start_pairing(self.url)

    def test_exchange_once(self):
        invite = self.invite()
        status, data = self.request(invite['token'])
        self.assertEqual(status, 200)
        self.assertEqual(data, dict(receiver_id=self.server.receiver_id, pc_name=self.server.pc_name,
                                    token='permanent-secret', url=self.url))
        self.assertEqual(self.request(invite['token'])[0], 403)
        self.assertIsNone(self.server.pairing_status())

    def test_concurrent_exchange_only_one_succeeds(self):
        invite = self.invite()
        with concurrent.futures.ThreadPoolExecutor(2) as pool:
            results = list(pool.map(self.request, [invite['token']] * 2))
        self.assertEqual(sorted(r[0] for r in results), [200, 403])

    def test_expiration_uses_monotonic(self):
        with patch('manager.receiver.time.monotonic', return_value=100):
            invite = self.invite()
        with patch('manager.receiver.time.monotonic', return_value=400):
            self.assertEqual(self.request(invite['token'])[0], 403)

    def test_wrong_token_and_attempt_limit(self):
        invite = self.invite()
        for _ in range(5):
            self.assertEqual(self.request('wrong')[0], 403)
        self.assertEqual(self.request(invite['token'])[0], 403)

    def test_unicode_token_is_rejected_without_crashing(self):
        self.invite()
        self.assertEqual(self.request('\ud800')[0], 403)

    def test_partial_body_times_out_without_consuming_invite(self):
        invite = self.invite()
        conn = http.client.HTTPConnection('127.0.0.1', self.server.server_port, timeout=3)
        with patch('manager.receiver.PAIR_TIMEOUT', 0.1):
            conn.putrequest('POST', '/pair')
            conn.putheader('Content-Type', 'application/json')
            conn.putheader('Content-Length', '100')
            conn.endheaders()
            conn.send(b'{')
            resp = conn.getresponse()
            self.assertEqual(resp.status, 408)
            resp.read()
        conn.close()
        self.assertEqual(self.request(invite['token'])[0], 200)

    def test_private_ip_restriction_applies_to_pair(self):
        invite = self.invite()
        self.server.check_client_ip = lambda _: False
        self.assertEqual(self.request(invite['token'])[0], 403)
        self.server.check_client_ip = lambda _: True
        self.assertEqual(self.request(invite['token'])[0], 200)

    def test_slow_trickle_cannot_extend_read_deadline(self):
        invite = self.invite()
        conn = http.client.HTTPConnection('127.0.0.1', self.server.server_port, timeout=2)
        stop = threading.Event()
        def trickle():
            try:
                while not stop.wait(0.03):
                    conn.send(b' ')
            except OSError:
                pass
        with patch('manager.receiver.PAIR_TIMEOUT', 0.15):
            conn.putrequest('POST', '/pair')
            conn.putheader('Content-Type', 'application/json')
            conn.putheader('Content-Length', '1000')
            conn.endheaders()
            sender = threading.Thread(target=trickle, daemon=True)
            sender.start()
            try:
                resp = conn.getresponse()
                self.assertEqual(resp.status, 408)
                resp.read()
            finally:
                stop.set()
                sender.join()
                conn.close()
        self.assertEqual(self.request(invite['token'])[0], 200)

    def test_logs_do_not_contain_credentials_or_request_query(self):
        invite = self.invite()
        self.server.quiet = False
        with patch('manager.receiver.sys.stderr', new_callable=io.StringIO) as output:
            self.assertEqual(self.request(invite['token'])[0], 200)
            self.request('', path='/unknown?token=' + invite['token'], method='GET')
        for secret in (invite['token'], self.server.token, 'SOTUKEN-PAIR:'):
            self.assertNotIn(secret, output.getvalue())

    def test_one_wrong_attempt_preserves_valid_invite(self):
        invite = self.invite()
        self.assertEqual(self.request('wrong')[0], 403)
        self.assertEqual(self.request(invite['token'])[0], 200)

    def test_cancel_replace_and_restart_invalidate(self):
        old = self.invite()
        current = self.invite()
        self.assertEqual(self.request(old['token'])[0], 403)
        self.server.cancel_pairing()
        self.assertEqual(self.request(current['token'])[0], 403)
        current = self.invite()
        restarted = ReceiverServer(('127.0.0.1', 0), 'permanent-secret', self.tmp.name,
                                   receiver_id=self.server.receiver_id, quiet=True)
        try:
            self.assertIsNone(restarted.exchange_pairing(current['token']))
        finally:
            restarted.server_close()

    def test_small_strict_json_and_health_does_not_disclose(self):
        self.invite()
        for body, expected in [('x' * 2049, 413), ('[]', 400), ('{"token":4}', 400), ('{', 400)]:
            self.assertEqual(self.request('', raw=body)[0], expected)
        status, data = self.request('', path='/health', method='GET',
                                    headers={'X-Sotuken-Token': 'permanent-secret'})
        self.assertEqual(status, 200)
        self.assertNotIn('token', data)
        self.assertNotIn('secret', json.dumps(data))

    def test_payload_and_png_are_distinct_from_device_qr(self):
        invite = self.invite()
        payload = self.server.pairing_payload()
        self.assertTrue(payload.startswith('SOTUKEN-PAIR:'))
        self.assertEqual(json.loads(payload.split(':', 1)[1]), invite)
        self.assertEqual(invite['v'], 1)
        self.assertEqual(invite['kind'], 'receiver-pair')
        self.assertIs(type(invite['expires_at']), int)
        self.assertGreaterEqual(len(invite['token']), 43)
        self.assertNotIn('permanent-secret', payload)
        self.assertTrue(pairing_qr_png(payload).startswith(b'\x89PNG\r\n\x1a\n'))
        self.assertIsNone(parse_payload(payload))
        self.assertIsNone(parse_payload(payload.split(':', 1)[1]))

    def test_invalid_origin_is_rejected(self):
        for url in ('https://192.168.1.2:8765', 'http://8.8.8.8:8765',
                    'http://192.168.1.2:8765/upload', 'http://192.168.1.2:8765?token=x',
                    'http://user@192.168.1.2:8765', 'http://192.168.1.2'):
            with self.subTest(url=url), self.assertRaises(ValueError):
                self.server.start_pairing(url)

    def test_app_register_rerender_cancel_and_url_refresh(self):
        from streamlit.testing.v1 import AppTest
        from streamlit import cache_data
        cache_data.clear()
        self.addCleanup(cache_data.clear)
        app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / 'app.py'), default_timeout=30)
        info = dict(running=True, server=self.server, token=self.server.token, url=self.url)
        with chdir(self.tmp.name), patch('manager.receiver.init_receiver_for_app', return_value=info):
            app.run()
            self.assertEqual(len(app.exception), 0)
            self.assertIsNone(self.server.pairing_status())
            next(b for b in app.button if b.label == 'スマホを登録').click().run()
            self.assertEqual(len(app.exception), 0)
            first = self.server.pairing_status()['payload']
            app.run()
            self.assertEqual(self.server.pairing_status()['payload'], first)
            self.assertTrue(any('残り' in c.value for c in app.caption))
            next(b for b in app.button if b.label == '登録を中止').click().run()
            self.assertIsNone(self.server.pairing_status())
            next(b for b in app.button if b.label == 'スマホを登録').click().run()
            info['url'] = 'http://192.168.1.99:8765'
            app.run()
            self.assertEqual(len(app.exception), 0)
            self.assertIsNone(self.server.pairing_status())
            self.assertTrue(any(info['url'] in m.value for m in app.markdown))


class ConfigTests(unittest.TestCase):
    def test_id_persists_and_existing_token_is_preserved(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'config.json'
            path.write_text('{"port":8765,"token":"existing"}', encoding='utf-8')
            first = load_or_create_pc_config(str(path))
            self.assertEqual(first['token'], 'existing')
            self.assertEqual(load_or_create_pc_config(str(path)), first)
            self.assertEqual(len(first['receiver_id']), 36)

    def test_corruption_is_backed_up_without_generating_token(self):
        for text in ('{bad', '[]', '{}', '{"token":null}'):
            with self.subTest(text=text), tempfile.TemporaryDirectory() as folder:
                path = Path(folder) / 'config.json'
                path.write_text(text, encoding='utf-8')
                with patch('manager.receiver.secrets.token_hex') as generate:
                    with self.assertRaises(ValueError):
                        load_or_create_pc_config(str(path))
                    generate.assert_not_called()
                self.assertEqual(path.read_text(encoding='utf-8'), text)
                backups = list(Path(folder).glob('config.json.corrupt-*'))
                self.assertEqual(len(backups), 1)
                self.assertEqual(backups[0].read_text(encoding='utf-8'), text)

    def test_atomic_save_failure_preserves_original(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'config.json'
            original = '{"port":8765,"token":"existing"}'
            path.write_text(original, encoding='utf-8')
            with patch('manager.receiver.os.replace', side_effect=OSError('disk full')):
                with self.assertRaises(OSError):
                    load_or_create_pc_config(str(path))
            self.assertEqual(path.read_text(encoding='utf-8'), original)
            self.assertEqual(list(Path(folder).glob('*.tmp')), [])
