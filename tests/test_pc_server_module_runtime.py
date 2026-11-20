import http.client
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
import socket


class ServerModuleRuntimeTests(unittest.TestCase):
    def test_authenticated_api_errors_under_python_m(self):
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as directory:
            work = Path(directory)
            db = work / 'manager.db'
            # Use the repository's normal schema initialization without starting another API.
            from manager.storage import Storage
            storage = Storage(str(db))
            with storage.connection() as conn:
                conn.execute("INSERT INTO meter_readings (timestamp, device_name, value, stage, image_path, inspection_id) VALUES (?, ?, ?, ?, ?, ?)", ('2026-11-19T09:00:00', 'A', 12, 'done', 'image.png', 'I-1'))
            folders = [work / name for name in ('incoming', 'images', 'overlays')]
            for folder in folders:
                folder.mkdir()
            key_file = work / 'internal-key'
            key_file.write_text('test-internal-key', encoding='utf-8')
            launch_file = work / 'launch-key'
            launch_file.touch()
            env = os.environ.copy()
            env['PYTHONPATH'] = str(root) + os.pathsep + env.get('PYTHONPATH', '')
            with socket.socket() as sock:
                sock.bind(('127.0.0.1', 0))
                port = sock.getsockname()[1]
            process = subprocess.Popen(
                [sys.executable, '-m', 'pc_api.server', '--db', str(db),
                 '--incoming-dir', str(folders[0]), '--images-dir', str(folders[1]),
                 '--overlays-dir', str(folders[2]), '--internal-key-file', str(key_file),
                 '--launch-key-out', str(launch_file), '--port', str(port)],
                cwd=root, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
            )
            self.addCleanup(self._stop, process)
            launch_key = None
            for _ in range(100):
                if process.poll() is not None:
                    self.fail(f'server exited early: {process.stderr.read().decode(errors="replace")}')
                if launch_file.exists():
                    launch_key = launch_file.read_text(encoding='utf-8')
                    if launch_key:
                        break
                time.sleep(0.05)
            self.assertTrue(launch_key, 'server did not write launch key')
            conn = http.client.HTTPConnection('127.0.0.1', port, timeout=2)
            try:
                conn.request('POST', '/api/v1/session',
                             body=json.dumps({'launch_key': launch_key}),
                             headers={'Host': f'127.0.0.1:{port}',
                                      'Content-Type': 'application/json',
                                      'Origin': f'http://127.0.0.1:{port}'})
                response = conn.getresponse()
                session = json.loads(response.read())
                self.assertEqual(response.status, 200)
                cookie = response.getheader('Set-Cookie').split(';', 1)[0]
            finally:
                conn.close()
            for path, expected in (
                ('/api/v1/inspections/no-such-inspection', 404),
                ('/api/v1/inspections?cursor=ABCDEFGHIJKLMNOPQRSTUV', 410),
            ):
                conn = http.client.HTTPConnection('127.0.0.1', port, timeout=2)
                try:
                    conn.request('GET', path, headers={'Host': f'127.0.0.1:{port}',
                                                       'Cookie': cookie})
                    response = conn.getresponse()
                    payload = json.loads(response.read())
                    self.assertEqual(response.status, expected, (path, payload))
                finally:
                    conn.close()

            conn = http.client.HTTPConnection('127.0.0.1', port, timeout=2)
            try:
                conn.request('POST', '/api/v1/inspections/I-1/csv',
                             body=json.dumps({'date_from': '2026-02-30'}),
                             headers={'Cookie': cookie, 'Content-Type': 'application/json',
                                      'Origin': f'http://127.0.0.1:{port}',
                                      'X-CSRF-Token': session['csrf_token']})
                response = conn.getresponse()
                payload = response.read()
                self.assertEqual(response.status, 422, payload)
            finally:
                conn.close()

    @staticmethod
    def _stop(process):
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
        process.stderr.close()


if __name__ == '__main__':
    unittest.main()

