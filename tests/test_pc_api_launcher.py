import http.client
import io
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

from manager.storage import Storage
from pc_api.launcher import (
    VerificationLauncher,
    _check_watch_inbox_pid,
    _write_private_key_file,
    main as launcher_main,
)


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

    def test_watch_inbox_pid_none_warns_to_stderr(self):
        buf = io.StringIO()
        with patch('sys.stderr', buf):
            _check_watch_inbox_pid(None)
        self.assertIn('watch_inbox の確認を省略しました（--watch-inbox-pid 未指定）', buf.getvalue())

    def test_watch_inbox_pid_requires_manager_watch_inbox_cmdline(self):
        if os.name == 'nt':
            with self.assertRaises(ValueError):
                _check_watch_inbox_pid(os.getpid())
            with patch('pc_api.launcher.subprocess.run') as run_mock:
                run_mock.side_effect = [
                    subprocess.CompletedProcess(['tasklist'], 0, stdout=f'python.exe {os.getpid()} Console 1 10,000 K\n'),
                    subprocess.CompletedProcess(['powershell'], 0, stdout='python -m manager.watch_inbox --dir incoming\n'),
                ]
                _check_watch_inbox_pid(os.getpid())
        else:
            with patch('pc_api.launcher.os.kill'), patch('pc_api.launcher.Path.read_bytes', return_value=b'python\x00other.py\x00'):
                with self.assertRaises(ValueError):
                    _check_watch_inbox_pid(12345)
            with patch('pc_api.launcher.os.kill'), patch('pc_api.launcher.Path.read_bytes', return_value=b'python\x00-m\x00manager.watch_inbox\x00'):
                _check_watch_inbox_pid(12345)

    def test_main_streamlit_isolates_and_restores_sys_argv(self):
        seen_argvs = []
        fake_launcher = Mock()
        fake_launcher.db_path = self.db.resolve()

        def fake_run_pc_main():
            seen_argvs.append(list(sys.argv))

        orig_argv = ['launcher.py', '--db', str(self.db), '--port', '9999', '--usb-pull']
        previous_cwd = Path.cwd()
        try:
            os.chdir(self.root)
            with patch.object(sys, 'argv', list(orig_argv)), \
                 patch('pc_api.launcher.VerificationLauncher', return_value=fake_launcher), \
                 patch('run_pc.main', side_effect=fake_run_pc_main):
                rc = launcher_main(['--db', str(self.db), '--port', '9999', '--usb-pull'])
                self.assertEqual(rc, 0)
                self.assertEqual(sys.argv, orig_argv)
                rc2 = launcher_main(['--db', str(self.db), '--port', '9999'])
                self.assertEqual(rc2, 0)
                self.assertEqual(sys.argv, orig_argv)
        finally:
            os.chdir(previous_cwd)

        self.assertEqual(seen_argvs, [['launcher.py', '--usb-pull'], ['launcher.py']])
        self.assertEqual(fake_launcher.stop.call_count, 2)

    def test_start_refuses_port_already_in_use(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.bind(('127.0.0.1', 0))
        sock.listen(1)
        self.addCleanup(sock.close)
        used_port = sock.getsockname()[1]

        launcher = VerificationLauncher(
            db_path=self.db,
            incoming_dir=self.incoming,
            images_dir=self.images,
            overlays_dir=self.overlays,
            static_dir=self.static,
            port=used_port,
            owner_port=0,
        )
        with self.assertRaises(RuntimeError):
            launcher.start()

    def test_no_streamlit_returns_nonzero_child_exit_code(self):
        fake_launcher = Mock()
        fake_launcher.api_proc.poll.return_value = 3
        fake_launcher.api_proc.returncode = 3
        with patch('pc_api.launcher.VerificationLauncher', return_value=fake_launcher):
            rc = launcher_main(['--db', str(self.db), '--no-streamlit'])
        self.assertEqual(rc, 3)
        fake_launcher.stop.assert_called_once()

    def test_write_private_key_file_removes_key_on_icacls_failure_or_missing_username(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            key_dir = Path(tmpdir)
            with patch('pc_api.launcher.os.name', 'nt'), \
                 patch.dict(os.environ, {}, clear=True):
                with self.assertRaises(RuntimeError):
                    _write_private_key_file(key_dir, 'secret-key')
                self.assertFalse((key_dir / 'owner-key.txt').exists())

            with patch('pc_api.launcher.os.name', 'nt'), \
                 patch.dict(os.environ, {'USERNAME': 'tester'}, clear=False), \
                 patch('pc_api.launcher.subprocess.run', return_value=subprocess.CompletedProcess(['icacls'], 5)):
                with self.assertRaises(RuntimeError):
                    _write_private_key_file(key_dir, 'secret-key')
                self.assertFalse((key_dir / 'owner-key.txt').exists())


if __name__ == '__main__':
    unittest.main()
