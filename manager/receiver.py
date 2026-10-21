"""
スマホ撮影画像 受信口モジュール（段階1: PC側の受信口）。
Wi-Fi経由で送信される計測画像およびサイドカーJSONを受信し、incoming/ フォルダへ書き込みます。
標準ライブラリ（http.server.ThreadingHTTPServer, hashlib, base64, json, ipaddress, secrets）のみで構成されます。
"""
import argparse
import base64
import hashlib
import http.server
import ipaddress
import json
import os
import re
import secrets
import socket
import sys
import threading
from typing import Any, Callable, Dict, Optional, Tuple

# 既定値
DEFAULT_PORT = 8765
MAX_BODY_SIZE = 30 * 1024 * 1024  # 30 MB

# ファイル名検査パターン
# 形: YYYYMMDDTHHMMSS_<local_id>.<拡張子>、英数と _ - . のみ、拡張子は jpg/jpeg/png
FILE_NAME_PATTERN = re.compile(
    r"^(\d{8}T\d{6})_([A-Za-z0-9_.-]+)\.(jpg|jpeg|png)$",
    re.IGNORECASE,
)
ALLOWED_CHARS_PATTERN = re.compile(r"^[A-Za-z0-9_.-]+$")


def get_default_config_path() -> str:
    """pc_config.json の既定パスを返す（manager/pc_config.json）。"""
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "pc_config.json")


def get_default_incoming_dir() -> str:
    """incoming/ ディレクトリの既定パスを返す（リポジトリ直下の incoming/）。"""
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(repo_root, "incoming")


def load_or_create_pc_config(config_path: Optional[str] = None) -> Dict[str, Any]:
    """
    PC受信口の設定を読み込む。存在しない、または項目が欠けている場合は生成・保存する。
    合言葉（token）は secrets による乱数で初回生成される。
    """
    if config_path is None:
        config_path = get_default_config_path()

    config: Dict[str, Any] = {}
    if os.path.exists(config_path):
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    config = data
        except Exception:
            config = {}

    updated = False
    if "port" not in config or not isinstance(config["port"], int):
        config["port"] = DEFAULT_PORT
        updated = True

    if "token" not in config or not isinstance(config["token"], str) or not config["token"].strip():
        config["token"] = secrets.token_hex(16)
        updated = True

    if updated:
        os.makedirs(os.path.dirname(os.path.abspath(config_path)), exist_ok=True)
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2, ensure_ascii=False)

    return config


def is_private_client_ip(client_ip: str) -> bool:
    """
    接続元IPがプライベートIPv4（10/8、172.16/12、192.168/16）または127.0.0.1かを判定する。
    """
    try:
        ip = ipaddress.ip_address(client_ip)
        if not isinstance(ip, ipaddress.IPv4Address):
            return False
        if ip.is_loopback:
            return True
        return ip.is_private
    except ValueError:
        return False


def get_lan_ipv4() -> str:
    """
    自PCのLAN内IPv4アドレスを取得する。
    スマホ側へ提示する送信先URL（http://<LAN_IP>:<PORT>）の生成に使用する。
    """
    for target in [("10.255.255.255", 1), ("8.8.8.8", 80)]:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(target)
            ip = s.getsockname()[0]
            s.close()
            if ip and not ip.startswith("127.") and not ip.startswith("169.254."):
                return ip
        except Exception:
            pass

    try:
        hostname = socket.gethostname()
        for ip in socket.gethostbyname_ex(hostname)[2]:
            if not ip.startswith("127.") and not ip.startswith("169.254."):
                return ip
        return "127.0.0.1"
    except Exception:
        return "127.0.0.1"


def decode_base64url(s: str) -> bytes:
    """
    Base64URL文字列（パディングの有無を許容）をバイト列へデコードする。
    """
    clean_s = s.strip()
    rem = len(clean_s) % 4
    if rem > 0:
        clean_s += "=" * (4 - rem)
    return base64.urlsafe_b64decode(clean_s.encode("ascii"))


class ReceiverHandler(http.server.BaseHTTPRequestHandler):
    """スマホからの HTTP 要求を処理するハンドラ。"""

    server: "ReceiverServer"

    def log_message(self, format: str, *args: Any) -> None:
        if getattr(self.server, "quiet", False):
            return
        sys.stderr.write(f"[受信口] {self.address_string()} - {format % args}\n")

    def _send_json(self, status_code: int, data: Dict[str, Any]) -> None:
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _check_ip_allowed(self) -> bool:
        check_fn = getattr(self.server, "check_client_ip", is_private_client_ip)
        client_ip = self.client_address[0]
        if not check_fn(client_ip):
            self._send_json(403, {"error": f"接続元IP（{client_ip}）が許可されていません（プライベートIPv4または127.0.0.1のみ）"})
            return False
        return True

    def do_GET(self) -> None:
        if not self._check_ip_allowed():
            return

        if self.path == "/health":
            self._send_json(200, {
                "ok": True,
                "service": "sotuken-receiver",
                "version": 1,
            })
            return

        self._send_json(404, {"error": f"パスが見つかりません: {self.path}"})

    def do_POST(self) -> None:
        if not self._check_ip_allowed():
            return

        if self.path != "/upload":
            self._send_json(404, {"error": f"パスが見つかりません: {self.path}"})
            return

        # 1. 合言葉（Token）の検査
        req_token = self.headers.get("X-Sotuken-Token")
        if not req_token or not secrets.compare_digest(req_token, self.server.token):
            self._send_json(401, {"error": "合言葉（X-Sotuken-Token）が一致しないか未指定です"})
            return

        # 2. Content-Length の検査
        content_length_str = self.headers.get("Content-Length")
        if not content_length_str:
            self._send_json(400, {"error": "Content-Length ヘッダーが必要です"})
            return

        try:
            content_length = int(content_length_str)
            if content_length < 0:
                raise ValueError("負の値")
        except ValueError:
            self._send_json(400, {"error": f"不正なContent-Lengthです: {content_length_str}"})
            return

        if content_length > MAX_BODY_SIZE:
            self._send_json(400, {"error": f"ファイルサイズが上限（{MAX_BODY_SIZE // (1024 * 1024)}MB）を超えています: {content_length} bytes"})
            return

        # 3. ファイル名の検査
        file_name = self.headers.get("X-File-Name")
        if not file_name:
            self._send_json(400, {"error": "X-File-Name ヘッダーが必要です"})
            return

        file_name = file_name.strip()
        if not ALLOWED_CHARS_PATTERN.match(file_name):
            self._send_json(400, {"error": "ファイル名に使用できない文字が含まれています（英数字および . _ - のみ許可）"})
            return

        match = FILE_NAME_PATTERN.match(file_name)
        if not match:
            self._send_json(400, {"error": "ファイル名形式が不正です（YYYYMMDDTHHMMSS_<local_id>.<拡張子> かつ拡張子は jpg/jpeg/png である必要があります）"})
            return

        name_local_id = match.group(2)
        ext = match.group(3).lower()
        base_name = file_name[:-(len(ext) + 1)]

        # 4. サイドカーJSONの検査
        sidecar_b64 = self.headers.get("X-Sidecar-Json")
        if not sidecar_b64:
            self._send_json(400, {"error": "X-Sidecar-Json ヘッダーが必要です"})
            return

        try:
            sidecar_bytes = decode_base64url(sidecar_b64)
            sidecar_text = sidecar_bytes.decode("utf-8")
            sidecar_data = json.loads(sidecar_text)
        except Exception as exc:
            self._send_json(400, {"error": f"サイドカーJSONの解析に失敗しました: {exc}"})
            return

        if not isinstance(sidecar_data, dict):
            self._send_json(400, {"error": "サイドカーJSONの形式が不正です（JSONオブジェクトである必要があります）"})
            return

        sidecar_local_id = sidecar_data.get("local_id")
        if sidecar_local_id is None or str(sidecar_local_id).strip() == "":
            self._send_json(400, {"error": "サイドカーJSONに local_id が含まれていません"})
            return

        sidecar_local_id_str = str(sidecar_local_id).strip()
        if sidecar_local_id_str != name_local_id and sidecar_local_id_str != base_name:
            self._send_json(400, {"error": f"サイドカーの local_id ({sidecar_local_id_str}) がファイル名 ({name_local_id}) と一致しません"})
            return

        # 5. SHA-256 チェックサムの検査および画像本文の読み取り
        header_sha256 = self.headers.get("X-Image-Sha256")
        if not header_sha256:
            self._send_json(400, {"error": "X-Image-Sha256 ヘッダーが必要です"})
            return

        body = self.rfile.read(content_length)
        if len(body) != content_length:
            self._send_json(400, {"error": f"受信バイト数（{len(body)}）が Content-Length（{content_length}）と一致しません"})
            return

        actual_sha256 = hashlib.sha256(body).hexdigest().lower()
        if actual_sha256 != header_sha256.strip().lower():
            self._send_json(400, {"error": f"画像本文のSHA-256がヘッダーと一致しません (受信: {actual_sha256}, 期待: {header_sha256})"})
            return

        # 6. 重複検査（正式な画像ファイルが既に存在するか）
        incoming_dir = self.server.incoming_dir
        os.makedirs(incoming_dir, exist_ok=True)
        final_image_path = os.path.join(incoming_dir, file_name)

        if os.path.exists(final_image_path):
            self._send_json(200, {
                "stored": file_name,
                "duplicate": True,
            })
            return

        # 7. incoming/ への書き込み
        # 規約: サイドカーJSONを <name>.json.part で書いて <base>.json へリネーム
        #       画像を <name>.part で書いて正式名へリネーム
        part_json_path = os.path.join(incoming_dir, f"{file_name}.json.part")
        final_json_path = os.path.join(incoming_dir, f"{base_name}.json")
        part_image_path = os.path.join(incoming_dir, f"{file_name}.part")

        try:
            with open(part_json_path, "wb") as f:
                f.write(sidecar_bytes)
            os.replace(part_json_path, final_json_path)

            with open(part_image_path, "wb") as f:
                f.write(body)
            os.replace(part_image_path, final_image_path)
        except OSError as exc:
            for p in (part_json_path, part_image_path):
                if os.path.exists(p):
                    try:
                        os.remove(p)
                    except OSError:
                        pass
            self._send_json(500, {"error": f"ファイルの保存に失敗しました: {exc}"})
            return

        self._send_json(200, {
            "stored": file_name,
        })


class ReceiverServer(http.server.ThreadingHTTPServer):
    """
    スマホ画像受信口HTTPサーバー。
    """
    allow_reuse_address = True

    def __init__(
        self,
        server_address: Tuple[str, int],
        token: str,
        incoming_dir: str,
        check_client_ip: Optional[Callable[[str], bool]] = None,
        quiet: bool = False,
        handler_class: Any = ReceiverHandler,
    ):
        super().__init__(server_address, handler_class)
        self.token = token
        self.incoming_dir = os.path.abspath(incoming_dir)
        os.makedirs(self.incoming_dir, exist_ok=True)
        self.check_client_ip = check_client_ip or is_private_client_ip
        self.quiet = quiet
        self.daemon_threads = True


def init_receiver_for_app(
    config_path: Optional[str] = None,
    incoming_dir: Optional[str] = None,
) -> Dict[str, Any]:
    """
    app.py 用の初期化関数。
    設定を読み込み、ポートが空いていれば別スレッドでサーバーを起動する。
    ポートが使用中などの例外時はクラッシュさせず、エラー情報を辞書で返す。
    """
    config = load_or_create_pc_config(config_path)
    port = int(config.get("port", DEFAULT_PORT))
    token = str(config.get("token", ""))
    lan_ip = get_lan_ipv4()
    send_url = f"http://{lan_ip}:{port}"

    if incoming_dir is None:
        incoming_dir = get_default_incoming_dir()

    try:
        server = ReceiverServer(
            ("0.0.0.0", port),
            token=token,
            incoming_dir=incoming_dir,
        )
        thread = threading.Thread(
            target=server.serve_forever,
            name="SotukenReceiverThread",
            daemon=True,
        )
        thread.start()
        return {
            "running": True,
            "port": port,
            "token": token,
            "lan_ip": lan_ip,
            "url": send_url,
            "server": server,
            "thread": thread,
            "error": None,
        }
    except Exception as exc:
        return {
            "running": False,
            "port": port,
            "token": token,
            "lan_ip": lan_ip,
            "url": send_url,
            "server": None,
            "thread": None,
            "error": f"ポート {port} が使用中または起動できませんでした（{exc}）",
        }


def main() -> None:
    parser = argparse.ArgumentParser(description="スマホ撮影画像 受信口サーバー")
    parser.add_argument("--port", type=int, default=None, help="待ち受けポート番号（デフォルト: pc_config.json または 8765）")
    parser.add_argument("--incoming", type=str, default=None, help="保存先ディレクトリ（デフォルト: incoming/）")
    parser.add_argument("--config", type=str, default=None, help="設定ファイルパス（デフォルト: manager/pc_config.json）")
    args = parser.parse_args()

    config = load_or_create_pc_config(args.config)
    port = args.port if args.port is not None else int(config.get("port", DEFAULT_PORT))
    token = str(config.get("token", ""))

    incoming_dir = args.incoming if args.incoming is not None else get_default_incoming_dir()
    incoming_dir = os.path.abspath(incoming_dir)

    lan_ip = get_lan_ipv4()
    print(f"[受信口] 待ち受け開始: 0.0.0.0:{port} (保存先: {incoming_dir})")
    print(f"[受信口] スマホの送信先: http://{lan_ip}:{port}")
    print(f"[受信口] 合言葉 (Token): {token}")
    print("[受信口] 停止するには Ctrl+C を押してください。")

    server = ReceiverServer(("0.0.0.0", port), token=token, incoming_dir=incoming_dir)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[受信口] 停止しています...")
    finally:
        server.shutdown()
        server.server_close()
        print("[受信口] 終了しました。")


if __name__ == "__main__":
    main()
