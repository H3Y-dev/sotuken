import http.client
import json
from pathlib import Path
import socket
import tempfile
import unittest
from unittest.mock import Mock, patch

from manager.storage import Storage
from pc_api.launcher import VerificationLauncher, _check_watch_inbox_pid


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


class LauncherTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.db = self.root / 'manager.db'
        Storage(str(self.db))
        self.incoming = self.root / 'incoming'
        self.images = self.root / 'images'
        self.overlays = self.root / 'overlays'
        self.static = self.root / 'static'
        for d in (self.incoming, self.images, self.overlays, self.static):
            d.mkdir()
        (self.static / 'index.html').write_text('<!doctype html><html><head></head><body>OK</body></html>', encoding='utf-8')
        (self.static / 'app.js').write_text('console.log(1);', encoding='utf-8')

    def test_launcher_starts_api_and_cleans_up_key_file_and_stops_in_order(self):
        receiver = Mock()
        receiver.pairing_status.return_value = None
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
                static_dir=self.static,
                port=port,
                owner_port=0,
            )
            launcher.start()
            self.addCleanup(launcher.stop)

            self.assertIsNotNone(launcher.api_proc)
            self.assertIsNone(launcher.api_proc.poll())

            conn = http.client.HTTPConnection('127.0.0.1', port, timeout=3)
            try:
                conn.request('GET', '/', headers={'Host': f'127.0.0.1:{port}'})
                res = conn.getresponse()
                html = res.read().decode('utf-8')
                self.assertEqual(res.status, 200)
                self.assertIn('<meta name="pc-token" content="', html)
                token = html.split('<meta name="pc-token" content="', 1)[1].split('"', 1)[0]

                conn.request(
                    'GET',
                    '/api/v1/runtime',
                    headers={'Host': f'127.0.0.1:{port}', 'X-PC-Token': token},
                )
                rt_res = conn.getresponse()
                rt_body = json.loads(rt_res.read())
                self.assertEqual(rt_res.status, 200)
                self.assertTrue(rt_body['receiver_running'])
                self.assertEqual(rt_body['owner_instance_id'], launcher.owner.instance_id)
            finally:
                conn.close()

            # Stopping API process does not stop owner.
            launcher.api_proc.terminate()
            launcher.api_proc.wait(timeout=5)
            self.assertIsNotNone(launcher.owner.httpd)

            launcher.stop()
            self.assertIsNone(launcher.owner)
            self.assertIsNone(launcher.api_proc)

    def test_missing_db_or_dead_watch_inbox_refused(self):
        launcher = VerificationLauncher(db_path=self.root / 'missing.db')
        with self.assertRaises(FileNotFoundError):
            launcher.start()
        with self.assertRaises((ValueError, RuntimeError)):
            _check_watch_inbox_pid(99999999)


if __name__ == '__main__':
    unittest.main()
