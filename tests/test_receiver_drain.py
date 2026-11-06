import http.client
import socket
import tempfile
import threading
import time
import unittest

from manager.receiver import ReceiverServer


class ReceiverDrainTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.server = ReceiverServer(('127.0.0.1', 0), 'secret', self.tmp.name, quiet=True)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.tmp.cleanup()

    def connect(self):
        return http.client.HTTPConnection('127.0.0.1', self.server.server_port, timeout=3)

    def test_repeated_early_errors_receive_response(self):
        body = b'x' * (256 * 1024)
        for path, status in (('/upload', 400), ('/pair', 413)):
            for attempt in range(50):
                with self.subTest(path=path, attempt=attempt):
                    conn = self.connect()
                    try:
                        conn.request('POST', path, body, {'X-Sotuken-Token': 'secret'})
                        response = conn.getresponse()
                        self.assertEqual(status, response.status)
                        self.assertTrue(response.read())
                    finally:
                        conn.close()

    def test_delayed_body_can_finish_after_error_response(self):
        conn = self.connect()
        try:
            conn.putrequest('POST', '/pair')
            conn.putheader('Content-Length', str(256 * 1024))
            conn.endheaders()
            sock = conn.sock
            response = conn.getresponse()
            self.assertEqual(413, response.status)
            time.sleep(0.05)
            sock.sendall(b'x' * (256 * 1024))
            self.assertTrue(response.read())
        finally:
            conn.close()

    def test_slow_trickle_cannot_extend_drain_deadline(self):
        with socket.create_connection(('127.0.0.1', self.server.server_port), timeout=3) as sock:
            sock.sendall(b'POST /pair HTTP/1.1\r\nHost: x\r\nContent-Length: 262144\r\n\r\n')
            response = http.client.HTTPResponse(sock)
            response.begin()
            self.assertEqual(413, response.status)
            self.assertTrue(response.read())
            started = time.monotonic()
            closed = False
            while time.monotonic() - started < 2:
                time.sleep(0.05)
                try:
                    sock.sendall(b'x')
                except OSError:
                    closed = True
                    break
            self.assertTrue(closed, 'trickling must not keep the drain alive')
            response.close()

    def test_shared_error_paths_drain_unread_body(self):
        cases = [('GET', '/health', {}, 401),
                 ('GET', '/routes', {}, 401),
                 ('GET', '/routes/missing', {'X-Sotuken-Token': 'secret'}, 404),
                 ('POST', '/inspections/test/manifest', {'X-Sotuken-Token': 'secret'}, 400),
                 ('POST', '/upload', {}, 401)]
        for method, path, headers, status in cases:
            with self.subTest(path=path):
                conn = self.connect()
                try:
                    conn.request(method, path, b'x' * (256 * 1024), headers)
                    response = conn.getresponse()
                    self.assertEqual(status, response.status)
                    self.assertTrue(response.read())
                finally:
                    conn.close()

    def test_oversized_body_closes_without_waiting_for_body(self):
        with socket.create_connection(('127.0.0.1', self.server.server_port), timeout=3) as sock:
            started = time.monotonic()
            sock.sendall(b'POST /pair HTTP/1.1\r\nHost: x\r\nContent-Length: 2097152\r\n\r\n')
            try:
                sock.sendall(b'x' * (2 * 1024 * 1024))
                while sock.recv(4096):
                    pass
            except (ConnectionResetError, ConnectionAbortedError):
                pass
            self.assertLess(time.monotonic() - started, 2)
        conn = self.connect()
        try:
            conn.request('GET', '/health', headers={'X-Sotuken-Token': 'secret'})
            self.assertEqual(200, conn.getresponse().status)
        finally:
            conn.close()
