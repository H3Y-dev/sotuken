"""
PC側受信口（manager/receiver.py）の単体テスト。
一時フォルダと空きポート（ポート0）で本物のサーバーを起動し、
プロトコル仕様（GET /health, POST /upload, 認証, 検査, 重複排除, 403）を検証します。
"""
import base64
import hashlib
import json
import os
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from manager.receiver import (
    DEFAULT_PORT,
    ReceiverServer,
    decode_base64url,
    init_receiver_for_app,
    is_private_client_ip,
    is_receiver_healthy,
    load_or_create_pc_config,
    shutdown_receiver_for_app,
)


class TestReceiverServer(unittest.TestCase):
    """本物の ReceiverServer を一時ポートで稼働させてテストする"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.incoming_dir = os.path.join(self.tmp.name, "incoming")
        os.makedirs(self.incoming_dir, exist_ok=True)
        self.token = "test-secret-token-12345"

        # ポート0でバインドすることでOSからエフェメラルポートを割り当ててもらう
        self.server = ReceiverServer(
            ("127.0.0.1", 0),
            token=self.token,
            incoming_dir=self.incoming_dir,
            quiet=True,
        )
        self.port = self.server.server_address[1]

        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=3)
        self.tmp.cleanup()

    def _request(self, method="GET", path="/health", headers=None, body=None):
        url = f"http://127.0.0.1:{self.port}{path}"
        req = urllib.request.Request(url, data=body, headers=headers or {}, method=method)
        try:
            with urllib.request.urlopen(req) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                return resp.status, data
        except urllib.error.HTTPError as e:
            raw = e.read().decode("utf-8")
            try:
                data = json.loads(raw)
            except Exception:
                data = {"error": raw}
            return e.code, data

    def _make_upload_headers(self, file_name, sidecar_obj, body_bytes, token=None):
        sha256 = hashlib.sha256(body_bytes).hexdigest()
        sidecar_json_str = json.dumps(sidecar_obj, ensure_ascii=False)
        sidecar_b64 = base64.urlsafe_b64encode(sidecar_json_str.encode("utf-8")).decode("ascii").rstrip("=")
        return {
            "X-Sotuken-Token": token if token is not None else self.token,
            "X-File-Name": file_name,
            "X-Sidecar-Json": sidecar_b64,
            "X-Image-Sha256": sha256,
            "Content-Length": str(len(body_bytes)),
        }

    def test_health_check_returns_ok(self):
        """GET /health で 200 {"ok":true,"service":"sotuken-receiver","version":1} が返ること。"""
        status, data = self._request("GET", "/health")
        self.assertEqual(200, status)
        self.assertEqual(True, data.get("ok"))
        self.assertEqual("sotuken-receiver", data.get("service"))
        self.assertEqual(1, data.get("version"))

    def test_unknown_path_returns_404(self):
        """未知のパスへのアクセスは 404 が返ること。"""
        status, _ = self._request("GET", "/unknown")
        self.assertEqual(404, status)
        status, _ = self._request("POST", "/unknown")
        self.assertEqual(404, status)

    def test_successful_upload_writes_json_then_image(self):
        """
        正常なアップロードでサイドカーJSONと画像が incoming/ に置かれ、
        200 {"stored": "<ファイル名>"} が返ること。
        """
        file_name = "20261021T153000_loc-001.png"
        body = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR...fake-image"
        sidecar = {
            "local_id": "loc-001",
            "device_name": "圧力計A",
            "operator_value": 15.5,
        }
        headers = self._make_upload_headers(file_name, sidecar, body)

        status, data = self._request("POST", "/upload", headers=headers, body=body)
        self.assertEqual(200, status)
        self.assertEqual(file_name, data.get("stored"))
        self.assertNotIn("duplicate", data)

        # ファイルが実際に保存されていることを確認
        final_image = os.path.join(self.incoming_dir, file_name)
        final_json = os.path.join(self.incoming_dir, "20261021T153000_loc-001.json")
        self.assertTrue(os.path.isfile(final_image))
        self.assertTrue(os.path.isfile(final_json))

        # 中身の検証
        with open(final_image, "rb") as f:
            self.assertEqual(body, f.read())
        with open(final_json, "r", encoding="utf-8") as f:
            saved_sidecar = json.load(f)
            self.assertEqual("loc-001", saved_sidecar.get("local_id"))
            self.assertEqual(15.5, saved_sidecar.get("operator_value"))

        # .part ファイルが残っていないこと
        all_files = os.listdir(self.incoming_dir)
        for name in all_files:
            self.assertFalse(name.endswith(".part"))

    def test_duplicate_upload_returns_200_duplicate(self):
        """既に同じ名前の画像ファイルが存在する場合、200 duplicate: true が返ること。"""
        file_name = "20261021T153000_dup-01.jpg"
        body = b"\xff\xd8\xff\xe0...fake-jpeg"
        sidecar = {"local_id": "dup-01"}
        headers = self._make_upload_headers(file_name, sidecar, body)

        # 1回目のアップロード
        status1, data1 = self._request("POST", "/upload", headers=headers, body=body)
        self.assertEqual(200, status1)
        self.assertEqual(file_name, data1.get("stored"))

        # 2回目のアップロード（同名再送）
        status2, data2 = self._request("POST", "/upload", headers=headers, body=body)
        self.assertEqual(200, status2)
        self.assertEqual(file_name, data2.get("stored"))
        self.assertTrue(data2.get("duplicate"))

    def test_wrong_token_returns_401(self):
        """合言葉（X-Sotuken-Token）が違う、または未指定の場合は 401 が返ること。"""
        file_name = "20261021T153000_tok-01.png"
        body = b"img"
        sidecar = {"local_id": "tok-01"}

        # 不正なトークン
        headers_wrong = self._make_upload_headers(file_name, sidecar, body, token="wrong-token")
        status, _ = self._request("POST", "/upload", headers=headers_wrong, body=body)
        self.assertEqual(401, status)

        # トークンなし
        headers_no_token = self._make_upload_headers(file_name, sidecar, body)
        del headers_no_token["X-Sotuken-Token"]
        status, _ = self._request("POST", "/upload", headers=headers_no_token, body=body)
        self.assertEqual(401, status)

    def test_sha256_mismatch_returns_400(self):
        """X-Image-Sha256 が本文のSHA-256と一致しない場合 400 が返ること。"""
        file_name = "20261021T153000_sha-01.png"
        body = b"actual-body"
        sidecar = {"local_id": "sha-01"}
        headers = self._make_upload_headers(file_name, sidecar, body)
        headers["X-Image-Sha256"] = "0000000000000000000000000000000000000000000000000000000000000000"

        status, _ = self._request("POST", "/upload", headers=headers, body=body)
        self.assertEqual(400, status)

    def test_invalid_file_name_returns_400(self):
        """
        ファイル名の形式（YYYYMMDDTHHMMSS_<local_id>.<拡張子>）や
        使用可能文字（[A-Za-z0-9_.-]）、許可拡張子（jpg/jpeg/png）を満たさない場合 400 が返ること。
        """
        body = b"dummy"
        sidecar = {"local_id": "test"}

        # パストラバーサル
        headers = self._make_upload_headers("20261021T153000_test.png", sidecar, body)
        headers["X-File-Name"] = "../20261021T153000_test.png"
        status, _ = self._request("POST", "/upload", headers=headers, body=body)
        self.assertEqual(400, status)

        # 許可されない拡張子（.gif）
        headers = self._make_upload_headers("20261021T153000_test.gif", sidecar, body)
        status, _ = self._request("POST", "/upload", headers=headers, body=body)
        self.assertEqual(400, status)

        # 不正な文字（スペースや記号）
        headers = self._make_upload_headers("20261021T153000_te st.png", sidecar, body)
        status, _ = self._request("POST", "/upload", headers=headers, body=body)
        self.assertEqual(400, status)

        # タイムスタンプ欠損
        headers = self._make_upload_headers("loc-001.png", sidecar, body)
        status, _ = self._request("POST", "/upload", headers=headers, body=body)
        self.assertEqual(400, status)

    def test_sidecar_validation_returns_400(self):
        """
        サイドカーJSONが不正な形式、または local_id がファイル名と不一致の場合 400 が返ること。
        """
        file_name = "20261021T153000_loc-01.png"
        body = b"dummy"

        # local_id の不一致
        sidecar_mismatch = {"local_id": "loc-OTHER"}
        headers = self._make_upload_headers(file_name, sidecar_mismatch, body)
        status, _ = self._request("POST", "/upload", headers=headers, body=body)
        self.assertEqual(400, status)

        # JSONデコード不能
        headers = self._make_upload_headers(file_name, {"local_id": "loc-01"}, body)
        headers["X-Sidecar-Json"] = "!!!not-valid-base64url!!!"
        status, _ = self._request("POST", "/upload", headers=headers, body=body)
        self.assertEqual(400, status)

        # JSONに local_id がない
        sidecar_no_id = {"device_name": "Gauge"}
        headers = self._make_upload_headers(file_name, sidecar_no_id, body)
        status, _ = self._request("POST", "/upload", headers=headers, body=body)
        self.assertEqual(400, status)

    def test_content_length_oversize_returns_400(self):
        """30MB を超える Content-Length は 400 で拒否されること。"""
        file_name = "20261021T153000_loc-01.png"
        headers = self._make_upload_headers(file_name, {"local_id": "loc-01"}, b"small")
        headers["Content-Length"] = str(31 * 1024 * 1024)  # 31MB

        status, _ = self._request("POST", "/upload", headers=headers, body=b"small")
        self.assertEqual(400, status)

    def test_non_private_ip_returns_403(self):
        """
        判定関数（check_client_ip）を差し替えて、プライベートIP以外からの接続を模擬したとき
        GET /health および POST /upload の両方で 403 Forbidden が返ること。
        """
        # 判定関数を偽物（常にFalse）に差し替える
        self.server.check_client_ip = lambda ip: False

        # GET /health
        status, data = self._request("GET", "/health")
        self.assertEqual(403, status)
        self.assertIn("許可されていません", data.get("error", ""))

        # POST /upload
        file_name = "20261021T153000_loc-01.png"
        body = b"img"
        headers = self._make_upload_headers(file_name, {"local_id": "loc-01"}, body)
        status, data = self._request("POST", "/upload", headers=headers, body=body)
        self.assertEqual(403, status)
        self.assertIn("許可されていません", data.get("error", ""))


class TestReceiverHelpers(unittest.TestCase):
    """補助関数（is_private_client_ip, load_or_create_pc_config, decode_base64url）の単体テスト"""

    def test_is_private_client_ip(self):
        # プライベートIPv4およびループバック
        self.assertTrue(is_private_client_ip("127.0.0.1"))
        self.assertTrue(is_private_client_ip("10.0.0.1"))
        self.assertTrue(is_private_client_ip("10.255.255.255"))
        self.assertTrue(is_private_client_ip("172.16.0.1"))
        self.assertTrue(is_private_client_ip("172.31.255.255"))
        self.assertTrue(is_private_client_ip("192.168.0.1"))
        self.assertTrue(is_private_client_ip("192.168.1.100"))

        # パブリックIP
        self.assertFalse(is_private_client_ip("8.8.8.8"))
        self.assertFalse(is_private_client_ip("1.1.1.1"))
        self.assertFalse(is_private_client_ip("172.32.0.1"))

        # IPv6や不正文字列
        self.assertFalse(is_private_client_ip("::1"))
        self.assertFalse(is_private_client_ip("2001:db8::1"))
        self.assertFalse(is_private_client_ip("not-an-ip"))

    def test_decode_base64url(self):
        original = b'{"hello": "world", "local_id": "123"}'
        # パディングなしの base64url
        encoded_unpadded = base64.urlsafe_b64encode(original).decode("ascii").rstrip("=")
        decoded = decode_base64url(encoded_unpadded)
        self.assertEqual(original, decoded)

        # パディングありの base64url
        encoded_padded = base64.urlsafe_b64encode(original).decode("ascii")
        decoded_pad = decode_base64url(encoded_padded)
        self.assertEqual(original, decoded_pad)

    def test_load_or_create_pc_config(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            cfg_path = os.path.join(tmp_dir, "pc_config.json")
            # 初回生成
            cfg1 = load_or_create_pc_config(cfg_path)
            self.assertTrue(os.path.isfile(cfg_path))
            self.assertEqual(DEFAULT_PORT, cfg1["port"])
            self.assertTrue(len(cfg1["token"]) >= 16)

            # 2回目読み込み（合言葉とポートが保持されること）
            cfg2 = load_or_create_pc_config(cfg_path)
            self.assertEqual(cfg1["token"], cfg2["token"])
            self.assertEqual(cfg1["port"], cfg2["port"])




class TestInitReceiverForApp(unittest.TestCase):
    """init_receiver_for_app のプロセス内1回起動と重複防止のテスト"""

    def setUp(self):
        shutdown_receiver_for_app()
        self.tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        shutdown_receiver_for_app()
        self.tmp.cleanup()

    def _get_free_port(self) -> int:
        import socket
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", 0))
            return s.getsockname()[1]

    def test_single_instance_on_multiple_inits(self):
        """同じプロセスで init_receiver_for_app を2回呼んでも、サーバーが1つであること。"""
        port = self._get_free_port()
        info1 = init_receiver_for_app(port=port, incoming_dir=self.tmp.name)
        self.assertTrue(info1["running"])
        self.assertFalse(info1.get("external_process", False))
        server1 = info1["server"]
        self.assertIsNotNone(server1)

        # 2回目の呼び出し
        info2 = init_receiver_for_app(port=port, incoming_dir=self.tmp.name)
        self.assertTrue(info2["running"])
        self.assertIs(info1, info2)
        self.assertIs(info1["server"], info2["server"])
        self.assertIs(info1["thread"], info2["thread"])

        # /health にアクセスして疎通を確認
        url = f"http://127.0.0.1:{info1['port']}/health"
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=2.0) as resp:
            self.assertEqual(200, resp.status)
            data = json.loads(resp.read().decode("utf-8"))
            self.assertEqual(True, data.get("ok"))
            self.assertEqual("sotuken-receiver", data.get("service"))

    def test_external_process_detection(self):
        """別サーバーが起動中のとき、/health 判定により external_process=True として検出されること。"""
        port = self._get_free_port()
        # 外部プロセスを模擬した独立サーバー
        ext_server = ReceiverServer(
            ("127.0.0.1", port),
            token="external-token",
            incoming_dir=self.tmp.name,
            quiet=True,
        )
        ext_thread = threading.Thread(target=ext_server.serve_forever, daemon=True)
        ext_thread.start()

        try:
            info = init_receiver_for_app(port=port, incoming_dir=self.tmp.name)
            self.assertTrue(info["running"])
            self.assertTrue(info.get("external_process"))
            self.assertIsNone(info["server"])
        finally:
            ext_server.shutdown()
            ext_server.server_close()
            ext_thread.join(timeout=2.0)


if __name__ == "__main__":
    unittest.main()
