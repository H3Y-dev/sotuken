"""
受信口の負荷対策（本文読取の期限・同時受信数の上限）とサイドカーJSONの検証のテスト。
"""
import base64
import hashlib
import json
import os
import select
import socket
import sys
import tempfile
import threading
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from manager.receiver import ReceiverServer, validate_sidecar_metadata

TOKEN = "limits-token"
NAME = "20261021T153000_lim.png"


def build_head(sidecar, body, name=NAME, length=None):
    sidecar_b64 = base64.urlsafe_b64encode(
        json.dumps(sidecar, ensure_ascii=False).encode("utf-8")).decode("ascii").rstrip("=")
    return (
        "POST /upload HTTP/1.1\r\nHost: x\r\n"
        f"X-Sotuken-Token: {TOKEN}\r\nX-File-Name: {name}\r\nX-Sidecar-Json: {sidecar_b64}\r\n"
        f"X-Image-Sha256: {hashlib.sha256(body).hexdigest()}\r\n"
        f"Content-Length: {len(body) if length is None else length}\r\n\r\n"
    ).encode("ascii")


def read_status(sock):
    sock.settimeout(5)
    data = b""
    while b"\r\n" not in data:
        chunk = sock.recv(4096)
        if not chunk:
            break
        data += chunk
    return int(data.split(b" ")[1]) if data else None, data


class ReceiverLimitsBase(unittest.TestCase):
    max_uploads = 4
    timeout = 60.0

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.incoming = os.path.join(self.tmp.name, "incoming")
        self.server = ReceiverServer(("127.0.0.1", 0), token=TOKEN, incoming_dir=self.incoming, quiet=True,
                                     max_concurrent_uploads=self.max_uploads, upload_timeout=self.timeout)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=3)
        self.tmp.cleanup()

    def connect(self):
        return socket.create_connection(("127.0.0.1", self.port), timeout=5)

    def upload(self, sidecar, body=b"image-bytes", name=NAME):
        with self.connect() as sock:
            sock.sendall(build_head(sidecar, body, name) + body)
            return read_status(sock)[0]


class TestUploadTimeout(ReceiverLimitsBase):
    timeout = 0.5

    def test_slow_body_gets_408_and_leaves_no_files(self):
        body = b"x" * 1000
        with self.connect() as sock:
            sock.sendall(build_head({"local_id": "lim"}, body) + body[:100])
            started = time.monotonic()
            status, _ = read_status(sock)
        self.assertEqual(408, status)
        self.assertLess(time.monotonic() - started, 4)
        self.assertEqual([], os.listdir(self.incoming))

    def test_trickling_body_hits_overall_deadline(self):
        body = b"x" * 1000
        with self.connect() as sock:
            sock.sendall(build_head({"local_id": "lim"}, body))
            for _ in range(30):  # 1バイトずつ送って個別の読取では止まらない状況
                if select.select([sock], [], [], 0.1)[0]:
                    break  # 応答が来たら送信をやめる（閉じた接続へ送るとRSTで応答が消える）
                sock.sendall(b"x")
            status, _ = read_status(sock)
        self.assertEqual(408, status)
        self.assertEqual([], os.listdir(self.incoming))

    def test_slot_released_after_timeout(self):
        body = b"x" * 10
        with self.connect() as sock:
            sock.sendall(build_head({"local_id": "lim"}, body))
            self.assertEqual(408, read_status(sock)[0])
        self.assertEqual(200, self.upload({"local_id": "lim"}))


class TestConcurrentLimit(ReceiverLimitsBase):
    max_uploads = 2
    timeout = 10.0

    def test_over_limit_returns_503_with_retry_after_then_recovers(self):
        body = b"y" * 100
        held = []
        try:
            for _ in range(2):
                sock = self.connect()
                held.append(sock)
                sock.sendall(build_head({"local_id": "lim"}, body) + body[:10])
            time.sleep(0.3)  # 2件が本文待ちで枠を占有するのを待つ
            with self.connect() as third:
                third.sendall(build_head({"local_id": "lim"}, body) + body)
                status, raw = read_status(third)
                rest = third.recv(4096)
            self.assertEqual(503, status)
            self.assertIn(b"retry-after: 5", (raw + rest).lower())
        finally:
            for sock in held:
                sock.close()
        deadline = time.monotonic() + 5
        status = None
        while time.monotonic() < deadline:  # 切断された2件の枠が戻るのを待つ
            status = self.upload({"local_id": "lim"})
            if status == 200:
                break
            time.sleep(0.1)
        self.assertEqual(200, status)

    def test_normal_uploads_within_limit(self):
        self.assertEqual(200, self.upload({"local_id": "lim", "operator_value": 1.5}))
        self.assertTrue(os.path.exists(os.path.join(self.incoming, NAME)))


class TestSidecarValidation(ReceiverLimitsBase):
    def test_invalid_metadata_returns_400(self):
        cases = [
            {"local_id": "lim", "operator_value": "1.5"},
            {"local_id": "lim", "operator_value": True},
            {"local_id": "lim", "scale_min": [1]},
            {"local_id": "lim", "device_name": 123},
            {"local_id": "lim", "device_name": "あ" * 257},
            {"local_id": "lim", "operator_note": "n" * 2001},
            {"local_id": "lim", "captured_at": "yesterday"},
            {"local_id": "lim", "captured_at": 12345},
        ]
        for sidecar in cases:
            with self.subTest(sidecar=sidecar):
                self.assertEqual(400, self.upload(sidecar))
        self.assertEqual([], os.listdir(self.incoming))

    def test_nan_and_infinity_are_rejected(self):
        body = b"image-bytes"
        for literal in ("NaN", "Infinity", "-Infinity", "1e999"):
            raw = ('{"local_id":"lim","operator_value":%s}' % literal).encode("utf-8")
            head = build_head({"local_id": "lim"}, body).decode("ascii").split("\r\n")
            head = [h for h in head if not h.startswith("X-Sidecar-Json")]
            head.insert(1, "X-Sidecar-Json: " + base64.urlsafe_b64encode(raw).decode("ascii").rstrip("="))
            with self.subTest(literal=literal), self.connect() as sock:
                sock.sendall("\r\n".join(head).encode("ascii") + body)
                self.assertEqual(400, read_status(sock)[0])
        self.assertEqual([], os.listdir(self.incoming))

    def test_compatible_payloads_are_accepted(self):
        full = {
            "local_id": "lim", "captured_at": "2026-10-21T15:30:00+09:00", "device_name": "Gauge",
            "operator_value": 15.5, "operator_note": "memo", "scale_min": 0, "scale_max": 100,
            "device_id": "dev-1", "device_id_source": "qr", "device_id_issue": None, "unknown_key": {"a": 1},
        }
        self.assertEqual(200, self.upload(full))

    def test_optional_fields_may_be_omitted_or_null(self):
        self.assertEqual(200, self.upload({"local_id": "lim", "operator_value": None, "captured_at": None}))

    def test_validate_function_reason(self):
        self.assertIsNone(validate_sidecar_metadata({"local_id": "a"}))
        self.assertIn("operator_value", validate_sidecar_metadata({"operator_value": float("nan")}))


if __name__ == "__main__":
    unittest.main()
