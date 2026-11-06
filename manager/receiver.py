"""
スマホ撮影画像 受信口モジュール（段階1: PC側の受信口）。
Wi-Fi経由で送信される計測画像およびサイドカーJSONを受信し、incoming/ フォルダへ書き込みます。
HTTP受信は標準ライブラリ、ペアリングQRの画像生成は既存のqrcodeを使います。
"""
import argparse
import base64
import hashlib
import http.server
import ipaddress
import io
import json
import math
import os
import re
import secrets
import socket
import shutil
import sys
import threading
import tempfile
import time
import uuid
import urllib.error
import urllib.request
from urllib.parse import urlsplit
from typing import Any, Callable, Dict, Optional, Tuple

from manager.sidecar import normalize_captured_at, normalize_inspection

# 既定値
DEFAULT_PORT = 8765
MAX_BODY_SIZE = 30 * 1024 * 1024  # 30 MB
MAX_PAIR_BODY_SIZE = 2048
PAIR_TIMEOUT = 3.0
PAIR_LIFETIME = 300
MAX_PAIR_FAILURES = 5
UPLOAD_TIMEOUT = 60.0  # /upload の本文全体を読み切る期限（秒）。画像用に/pairより十分長い。
MAX_CONCURRENT_UPLOADS = 4  # 同時に本文を受信できる数。超過は503+Retry-After
UPLOAD_RETRY_AFTER = 5

# サイドカーJSONの文字列長上限（manager/sidecar.py の SidecarMetadata の項目に対応）
SIDECAR_STRING_LIMITS = {
    "local_id": 128, "captured_at": 64, "device_name": 256, "operator_note": 2000,
    "device_id": 128, "device_id_source": 16, "device_id_issue": 32,
}
SIDECAR_NUMBER_KEYS = ("operator_value", "scale_min", "scale_max")

# ファイル名検査パターン
# 形: YYYYMMDDTHHMMSS_<local_id>.<拡張子>、英数と _ - . のみ、拡張子は jpg/jpeg/png
FILE_NAME_PATTERN = re.compile(
    r"^(\d{8}T\d{6})_([A-Za-z0-9_.-]+)\.(jpg|jpeg|png)$",
    re.IGNORECASE,
)
ALLOWED_CHARS_PATTERN = re.compile(r"^[A-Za-z0-9_.-]+$")

# プロセス内キャッシュ（app.py / run_pc.py で共有）
_receiver_lock = threading.Lock()
_cached_receiver_info: Optional[Dict[str, Any]] = None


def get_default_config_path() -> str:
    """pc_config.json の既定パスを返す（manager/pc_config.json）。"""
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "pc_config.json")


def get_default_incoming_dir() -> str:
    """incoming/ ディレクトリの既定パスを返す（リポジトリ直下の incoming/）。"""
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(repo_root, "incoming")


def load_or_create_pc_config(config_path: Optional[str] = None) -> Dict[str, Any]:
    """
    PC受信口の設定を読み込む。初回生成と旧設定へのreceiver_id追加を原子的に保存する。
    既存設定が壊れている場合は退避コピーを残し、合言葉を再生成せずエラーにする。
    """
    if config_path is None:
        config_path = get_default_config_path()

    config: Dict[str, Any] = {}
    existing = os.path.exists(config_path)
    if existing:
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                if not isinstance(data, dict) or not isinstance(data.get("token"), str) or not data["token"].strip():
                    raise ValueError("token がないか不正です")
                if "receiver_id" in data:
                    uuid.UUID(data["receiver_id"])
                config = data
        except (ValueError, TypeError, AttributeError) as exc:
            backup = f"{config_path}.corrupt-{uuid.uuid4().hex}"
            shutil.copy2(config_path, backup)
            raise ValueError(f"受信設定が破損しています。原本を保持し退避しました: {backup}") from exc

    updated = False
    if "receiver_id" not in config:
        config["receiver_id"] = str(uuid.uuid4())
        updated = True
    if "port" not in config or not isinstance(config["port"], int):
        config["port"] = DEFAULT_PORT
        updated = True

    if "token" not in config or not isinstance(config["token"], str) or not config["token"].strip():
        config["token"] = secrets.token_hex(16)
        updated = True

    if updated:
        os.makedirs(os.path.dirname(os.path.abspath(config_path)), exist_ok=True)
        fd, temporary = tempfile.mkstemp(dir=os.path.dirname(os.path.abspath(config_path)),
                                         prefix=f".{os.path.basename(config_path)}-", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(config, f, indent=2, ensure_ascii=False)
                f.flush()
                os.fsync(f.fileno())
            os.replace(temporary, config_path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    return config


def pairing_qr_png(payload: str) -> bytes:
    """ペアリング専用ペイロードをPNGにする（秘密はファイルに保存しない）。"""
    import qrcode
    output = io.BytesIO()
    qrcode.make(payload).save(output, format="PNG")
    return output.getvalue()


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


def validate_sidecar_metadata(data: Dict[str, Any]) -> Optional[str]:
    """
    受信したサイドカーJSON（辞書）を検証し、不正なら理由の文字列、問題なければ None を返す。
    manager/sidecar.py の SidecarMetadata の項目に合わせる。項目の省略・null は従来どおり許可し、
    未知のキーも許容する（互換性維持）。local_id の存在とファイル名との一致は呼び出し側で検査する。
    注意: 画像のSHA-256は転送の破損検出用で、送信者の認証の代わりにはならない（認証は合言葉で行う）。
    """
    # 巡回項目は任意。不正でも写真は拒否せず、保存する値だけを正規化する。
    if "inspection_id" in data or "inspection_name" in data:
        data["inspection_id"], data["inspection_name"] = normalize_inspection(
            data.get("inspection_id"), data.get("inspection_name"))
    if "route_id" in data:
        data["route_id"] = normalize_inspection(data.get("route_id"), None)[0]
    for key, limit in SIDECAR_STRING_LIMITS.items():
        value = data.get(key)
        if value is None:
            continue
        if key == "local_id" and isinstance(value, (int, float)) and not isinstance(value, bool):
            value = str(value)  # 既存の str(local_id) 照合と互換
        if not isinstance(value, str):
            return f"{key} は文字列である必要があります"
        if len(value) > limit:
            return f"{key} が長すぎます（上限{limit}文字）"
    for key in SIDECAR_NUMBER_KEYS:
        value = data.get(key)
        if value is None:
            continue
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return f"{key} は数値である必要があります"
        try:
            finite = math.isfinite(value)
        except OverflowError:
            finite = False
        if not finite:
            return f"{key} は有限の数値である必要があります（NaN/Infinity は不可）"
    captured_at = data.get("captured_at")
    if captured_at is not None and normalize_captured_at(captured_at) is None:
        return "captured_at がISO 8601形式ではありません"
    return None


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
        # 要求行には任意のクエリや秘密が含まれ得るため記録しない。
        sys.stderr.write(f"[受信口] {self.address_string()} - HTTP要求\n")

    def _read_body_chunk(self, size: int) -> bytes:
        chunk = self.rfile.read1(size)
        self._body_bytes_read = getattr(self, "_body_bytes_read", 0) + len(chunk)
        return chunk

    def _drain_request_body(self) -> None:
        """応答後の未読本文を最大1MB・1秒だけ読み捨て、TCP RSTを防ぐ。"""
        try:
            lengths = self.headers.get_all("Content-Length", [])
            if len(lengths) != 1 or self.headers.get("Transfer-Encoding"):
                return
            remaining = int(lengths[0]) - getattr(self, "_body_bytes_read", 0)
            if not 0 < remaining <= 1024 * 1024:
                return
            deadline = time.monotonic() + 1.0
            while remaining > 0:
                timeout = deadline - time.monotonic()
                if timeout <= 0:
                    break
                self.connection.settimeout(timeout)
                try:
                    chunk = self.rfile.read1(min(65536, remaining))
                except OSError:
                    # 本文のタイムアウト後はBufferedReaderを再利用できない。
                    timeout = deadline - time.monotonic()
                    if timeout <= 0:
                        break
                    self.connection.settimeout(timeout)
                    chunk = self.connection.recv(min(65536, remaining))
                if not chunk:
                    break
                remaining -= len(chunk)
        except (ValueError, OSError):
            pass

    def _send_json(self, status_code: int, data: Dict[str, Any],
                   extra_headers: Optional[Dict[str, str]] = None) -> None:
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for name, value in (extra_headers or {}).items():
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(body)
        if status_code >= 400:
            self.close_connection = True
            self.wfile.flush()
            try:
                self.connection.shutdown(socket.SHUT_WR)
            except OSError:
                return
            self._drain_request_body()

    def _check_ip_allowed(self) -> bool:
        check_fn = getattr(self.server, "check_client_ip", is_private_client_ip)
        client_ip = self.client_address[0]
        if not check_fn(client_ip):
            self._send_json(403, {"error": f"接続元IP（{client_ip}）が許可されていません（プライベートIPv4または127.0.0.1のみ）"})
            return False
        return True

    def _check_token(self) -> bool:
        req_token = self.headers.get("X-Sotuken-Token")
        if not req_token or not secrets.compare_digest(req_token, self.server.token):
            self._send_json(401, {"error": "合言葉（X-Sotuken-Token）が一致しないか未指定です"})
            return False

        return True

    def do_GET(self) -> None:
        if not self._check_ip_allowed():
            return

        if self.path == "/routes" or self.path.startswith("/routes/"):
            if not self._check_token():
                return
            from manager.storage import Storage
            from manager.routes import list_routes, get_route
            storage = Storage(self.server.db_path)
            result = list_routes(storage) if self.path == "/routes" else get_route(storage, self.path[len('/routes/'):])
            self._send_json(200 if result is not None else 404, result or {"error": "ルートがありません"})
            return

        if self.path == "/health":
            if self.server.token and not self._check_token():
                return
            self._send_json(200, {
                "ok": True,
                "service": "sotuken-receiver",
                "version": 1,
            })
            return

        self._send_json(404, {"error": f"パスが見つかりません: {self.path}"})

    def _pair(self) -> None:
        self.close_connection = True
        self.connection.settimeout(PAIR_TIMEOUT)
        try:
            if self.headers.get("Transfer-Encoding") or len(self.headers.get_all("Content-Length", [])) != 1:
                raise ValueError
            size = int(self.headers.get("Content-Length", ""))
            if size > MAX_PAIR_BODY_SIZE:
                self._send_json(413, {"error": "登録要求が大きすぎます"})
                return
            if size <= 0 or self.headers.get_content_type() != "application/json":
                raise ValueError
            deadline = time.monotonic() + PAIR_TIMEOUT
            body = bytearray()
            while len(body) < size:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError
                self.connection.settimeout(remaining)
                chunk = self._read_body_chunk(size - len(body))
                if not chunk:
                    raise ValueError
                body.extend(chunk)
            data = json.loads(body.decode("utf-8"))
            if not isinstance(data, dict) or set(data) != {"token"} or not isinstance(data["token"], str):
                raise ValueError
        except (ValueError, UnicodeError):
            self._send_json(400, {"error": "登録要求のJSONが不正です"})
            return
        except (TimeoutError, OSError):
            self._send_json(408, {"error": "登録要求の読み取りがタイムアウトしました"})
            return
        result = self.server.exchange_pairing(data["token"])
        if result is None:
            self._send_json(403, {"error": "招待が無効です。PCでQRを作り直してください"})
            return
        self._send_json(200, result)

    def _manifest(self, inspection_id):
        self.close_connection = True
        try:
            if self.headers.get('Transfer-Encoding') or len(self.headers.get_all('Content-Length', [])) != 1:
                raise ValueError('Content-Lengthが必要です')
            size = int(self.headers.get('Content-Length', ''))
            if size > MAX_BODY_SIZE:
                self._send_json(413, {'error': 'manifestが大きすぎます'})
                return
            if size <= 0 or self.headers.get_content_type() != 'application/json':
                raise ValueError('JSONが必要です')
            deadline = time.monotonic() + self.server.upload_timeout
            body = bytearray()
            while len(body) < size:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError
                self.connection.settimeout(remaining)
                chunk = self._read_body_chunk(min(65536, size - len(body)))
                if not chunk:
                    raise ValueError('本文が不足しています')
                body.extend(chunk)
            data = json.loads(body.decode('utf-8'))
            from manager.storage import Storage
            from manager.routes import save_manifest
            result = save_manifest(Storage(self.server.db_path), inspection_id, data, self.server.incoming_dir)
        except (ValueError, UnicodeError, RecursionError):
            self._send_json(400, {'error': 'manifestのJSONが不正です'})
            return
        except (TimeoutError, OSError):
            self._send_json(408, {'error': 'manifestの読み取りがタイムアウトしました'})
            return
        self._send_json(200, result)

    def do_POST(self) -> None:
        if not self._check_ip_allowed():
            return

        match = re.fullmatch(r"/inspections/([A-Za-z0-9._-]{1,64})/manifest", self.path)
        if match:
            if self._check_token():
                self._manifest(match.group(1))
            return

        if self.path == "/pair":
            self._pair()
            return

        if self.path != "/upload":
            self._send_json(404, {"error": f"パスが見つかりません: {self.path}"})
            return

        # 1. 合言葉（Token）の検査
        if not self._check_token():
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
            self._send_json(413, {"error": f"ファイルサイズが上限（{MAX_BODY_SIZE // (1024 * 1024)}MB）を超えています: {content_length} bytes"})
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

        reason = validate_sidecar_metadata(sidecar_data)
        if reason is not None:
            self._send_json(400, {"error": f"サイドカーJSONが不正です: {reason}"})
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

        # 同時受信数の上限。超過は一時エラー(503)として返し、スマホ側の保持・再送に任せる。
        if not self.server.upload_slots.acquire(blocking=False):
            self.close_connection = True
            self._send_json(503, {"error": "同時受信数の上限に達しています。少し待って再送してください"},
                            {"Retry-After": str(UPLOAD_RETRY_AFTER)})
            return
        try:
            # 本文全体の期限。低速送信や途中停止で受信スレッドを占有させない。
            # 本文はメモリ上で受け取りディスクへは完了後にだけ書くため、タイムアウト時に.partは残らない。
            self.close_connection = True
            deadline = time.monotonic() + self.server.upload_timeout
            body_buffer = bytearray()
            try:
                while len(body_buffer) < content_length:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise TimeoutError
                    self.connection.settimeout(remaining)
                    chunk = self._read_body_chunk(min(65536, content_length - len(body_buffer)))
                    if not chunk:
                        break
                    body_buffer.extend(chunk)
            except (TimeoutError, OSError):
                self._send_json(408, {"error": "画像本文の読み取りがタイムアウトしました。再送してください"})
                return
        finally:
            self.server.upload_slots.release()
        body = bytes(body_buffer)
        if len(body) != content_length:
            self._send_json(400, {"error": f"受信バイト数（{len(body)}）が Content-Length（{content_length}）と一致しません"})
            return

        actual_sha256 = hashlib.sha256(body).hexdigest().lower()
        if actual_sha256 != header_sha256.strip().lower():
            self._send_json(400, {"error": f"画像本文のSHA-256がヘッダーと一致しません (受信: {actual_sha256}, 期待: {header_sha256})"})
            return

        # 重複確認から保存までを保護し、異なる内容の同時到着でも上書きしない。
        with self.server.upload_lock:
            # 6. 重複検査（正式な画像ファイルが既に存在するか）
            incoming_dir = self.server.incoming_dir
            os.makedirs(incoming_dir, exist_ok=True)
            final_image_path = os.path.join(incoming_dir, file_name)

            if os.path.exists(final_image_path):
                try:
                    with open(final_image_path, "rb") as existing:
                        existing_sha256 = hashlib.sha256(existing.read()).hexdigest()
                except OSError as exc:
                    self._send_json(500, {"error": f"既存画像の確認に失敗しました: {exc}"})
                    return
                if existing_sha256 != actual_sha256:
                    self._send_json(409, {"error": "同名の画像が異なる内容で既に保存されています"})
                    return
                self._send_json(200, {
                    "stored": file_name,
                    "duplicate": True,
                })
                return

            # 7. incoming/ への書き込み
            # 一時ファイルを同期してから、JSON、画像の順で正式名へ置き換える。
            part_id = uuid.uuid4().hex[:12]
            part_json_path = os.path.join(incoming_dir, f"{file_name}.{part_id}.json.part")
            final_json_path = os.path.join(incoming_dir, f"{base_name}.json")
            part_image_path = os.path.join(incoming_dir, f"{file_name}.{part_id}.part")

            try:
                with open(part_json_path, "wb") as f:
                    f.write(sidecar_bytes)
                    f.flush()
                    os.fsync(f.fileno())
                os.replace(part_json_path, final_json_path)

                with open(part_image_path, "wb") as f:
                    f.write(body)
                    f.flush()
                    os.fsync(f.fileno())
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
    # Windows では SO_REUSEADDR が同一ポートへの複数バインドを許容してしまうため False にする
    allow_reuse_address = sys.platform != "win32"

    def __init__(
        self,
        server_address: Tuple[str, int],
        token: str,
        incoming_dir: str,
        check_client_ip: Optional[Callable[[str], bool]] = None,
        quiet: bool = False,
        handler_class: Any = ReceiverHandler,
        receiver_id: Optional[str] = None,
        max_concurrent_uploads: int = MAX_CONCURRENT_UPLOADS,
        upload_timeout: float = UPLOAD_TIMEOUT,
        db_path: str = "manager.db",
    ):
        self.pair_lock = threading.Lock()
        self._invitation = None
        super().__init__(server_address, handler_class)
        self.upload_lock = threading.Lock()
        self.upload_slots = threading.BoundedSemaphore(max_concurrent_uploads)
        self.upload_timeout = upload_timeout
        self.db_path = os.path.abspath(db_path)
        self.token = token
        self.receiver_id = receiver_id or str(uuid.uuid4())
        self.pc_name = "".join(c for c in socket.gethostname() if c.isprintable())[:64] or "PC"
        self.incoming_dir = os.path.abspath(incoming_dir)
        os.makedirs(self.incoming_dir, exist_ok=True)
        self.check_client_ip = check_client_ip or is_private_client_ip
        self.quiet = quiet
        self.daemon_threads = True

    def start_pairing(self, url: str) -> Dict[str, Any]:
        origin = urlsplit(url)
        if (origin.scheme != "http" or not origin.hostname or not is_private_client_ip(origin.hostname)
                or origin.port is None or not 1 <= origin.port <= 65535 or origin.username is not None
                or origin.password is not None or origin.path or origin.query or origin.fragment):
            raise ValueError("登録URLはプライベートIPv4とポートを持つHTTP originにしてください")
        with self.pair_lock:
            payload = dict(v=1, kind="receiver-pair", url=url, token=secrets.token_urlsafe(32),
                           receiver_id=self.receiver_id, pc_name=self.pc_name,
                           expires_at=int(time.time()) + PAIR_LIFETIME)
            self._invitation = dict(payload=payload, deadline=time.monotonic() + PAIR_LIFETIME, failures=0)
            return dict(payload)

    def cancel_pairing(self) -> None:
        with self.pair_lock:
            self._invitation = None

    def pairing_status(self) -> Optional[Dict[str, Any]]:
        with self.pair_lock:
            invite = self._invitation
            if invite is None or time.monotonic() >= invite["deadline"]:
                self._invitation = None
                return None
            return dict(payload=dict(invite["payload"]), remaining=max(1, int(invite["deadline"] - time.monotonic())))

    def pairing_payload(self) -> Optional[str]:
        status = self.pairing_status()
        if status is None:
            return None
        return "SOTUKEN-PAIR:" + json.dumps(status["payload"], ensure_ascii=False, separators=(",", ":"))

    def exchange_pairing(self, token: str) -> Optional[Dict[str, Any]]:
        with self.pair_lock:
            invite = self._invitation
            if invite is None:
                return None
            if time.monotonic() >= invite["deadline"]:
                self._invitation = None
                return None
            if not token.isascii() or not secrets.compare_digest(token, invite["payload"]["token"]):
                invite["failures"] += 1
                if invite["failures"] >= MAX_PAIR_FAILURES:
                    self._invitation = None
                return None
            self._invitation = None  # 応答送信前に消費し、応答喪失でも再交換させない。
            return dict(receiver_id=self.receiver_id, pc_name=self.pc_name,
                        token=self.token, url=invite["payload"]["url"])

    def server_close(self) -> None:
        self.cancel_pairing()
        super().server_close()


def is_receiver_healthy(port: int, timeout: float = 1.0, token: str = "") -> bool:
    """
    ローカルホスト（127.0.0.1:{port}/health）に問い合わせ、
    sotuken-receiver が正常に応答するかを判定する。
    """
    url = f"http://127.0.0.1:{port}/health"
    req = urllib.request.Request(url, headers={"X-Sotuken-Token": token}, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.status == 200:
                body = json.loads(resp.read().decode("utf-8"))
                return bool(body.get("ok") is True and body.get("service") == "sotuken-receiver")
    except Exception:
        pass
    return False


def shutdown_receiver_for_app() -> None:
    """
    テスト用: init_receiver_for_app で起動・キャッシュされたサーバーを安全に停止し、
    キャッシュをクリアする。
    """
    global _cached_receiver_info
    with _receiver_lock:
        if _cached_receiver_info is not None:
            server = _cached_receiver_info.get("server")
            if server is not None:
                try:
                    server.shutdown()
                    server.server_close()
                except Exception:
                    pass
            thread = _cached_receiver_info.get("thread")
            if thread is not None and thread.is_alive():
                thread.join(timeout=2.0)
            _cached_receiver_info = None


def init_receiver_for_app(
    config_path: Optional[str] = None,
    incoming_dir: Optional[str] = None,
    port: Optional[int] = None,
) -> Dict[str, Any]:
    """
    app.py 用の初期化関数。
    設定を読み込み、ポートが空いていれば別スレッドでサーバーを起動する。
    同一プロセス内では1回だけ起動し、モジュール変数にキャッシュして再利用する。
    ポートが使用中などの例外時は、/health への問い合わせで別プロセスでの稼働を確認し、
    クラッシュさせずに適切な情報を辞書で返す。
    """
    global _cached_receiver_info

    with _receiver_lock:
        if _cached_receiver_info is not None:
            _cached_receiver_info["lan_ip"] = get_lan_ipv4()
            _cached_receiver_info["url"] = f"http://{_cached_receiver_info['lan_ip']}:{_cached_receiver_info['port']}"
            return _cached_receiver_info

        config = load_or_create_pc_config(config_path)
        actual_port = port if port is not None else int(config.get("port", DEFAULT_PORT))
        token = str(config.get("token", ""))
        lan_ip = get_lan_ipv4()
        send_url = f"http://{lan_ip}:{actual_port}"

        if incoming_dir is None:
            incoming_dir = get_default_incoming_dir()

        # ポート指定がある場合、すでに別プロセスで受信口が動いていれば検知
        if actual_port != 0 and is_receiver_healthy(actual_port, token=token):
            _cached_receiver_info = {
                "running": True,
                "port": actual_port,
                "token": token,
                "lan_ip": lan_ip,
                "url": send_url,
                "server": None,
                "thread": None,
                "error": None,
                "external_process": True,
            }
            return _cached_receiver_info

        try:
            server = ReceiverServer(
                ("0.0.0.0", actual_port),
                token=token,
                incoming_dir=incoming_dir,
                receiver_id=config.get("receiver_id"),
            )
            bound_port = server.server_address[1]
            if bound_port != actual_port:
                actual_port = bound_port
                send_url = f"http://{lan_ip}:{actual_port}"

            thread = threading.Thread(
                target=server.serve_forever,
                name="SotukenReceiverThread",
                daemon=True,
            )
            thread.start()
            _cached_receiver_info = {
                "running": True,
                "port": actual_port,
                "token": token,
                "lan_ip": lan_ip,
                "url": send_url,
                "server": server,
                "thread": thread,
                "error": None,
                "external_process": False,
            }
            return _cached_receiver_info
        except Exception as exc:
            if is_receiver_healthy(actual_port, token=token):
                _cached_receiver_info = {
                    "running": True,
                    "port": actual_port,
                    "token": token,
                    "lan_ip": lan_ip,
                    "url": send_url,
                    "server": None,
                    "thread": None,
                    "error": None,
                    "external_process": True,
                }
                return _cached_receiver_info

            return {
                "running": False,
                "port": actual_port,
                "token": token,
                "lan_ip": lan_ip,
                "url": send_url,
                "server": None,
                "thread": None,
                "error": f"ポート {actual_port} が使用中または起動できませんでした（{exc}）",
                "external_process": False,
            }


def main() -> None:
    parser = argparse.ArgumentParser(description="スマホ撮影画像 受信口サーバー")
    parser.add_argument("--port", type=int, default=None, help="待ち受けポート番号（デフォルト: pc_config.json または 8765）")
    parser.add_argument("--incoming", type=str, default=None, help="保存先ディレクトリ（デフォルト: incoming/）")
    parser.add_argument("--config", type=str, default=None, help="設定ファイルパス（デフォルト: manager/pc_config.json）")
    parser.add_argument("--db", default="manager.db", help="画面と共有するSQLite DBのパス")
    args = parser.parse_args()

    config = load_or_create_pc_config(args.config)
    port = args.port if args.port is not None else int(config.get("port", DEFAULT_PORT))
    token = str(config.get("token", ""))

    incoming_dir = args.incoming if args.incoming is not None else get_default_incoming_dir()
    incoming_dir = os.path.abspath(incoming_dir)

    lan_ip = get_lan_ipv4()
    print(f"[受信口] 待ち受け開始: 0.0.0.0:{port} (保存先: {incoming_dir})")
    print(f"[受信口] スマホの送信先: http://{lan_ip}:{port}")
    print("[受信口] 停止するには Ctrl+C を押してください。")

    server = ReceiverServer(("0.0.0.0", port), token=token, incoming_dir=incoming_dir,
                            receiver_id=config["receiver_id"], db_path=args.db)
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
