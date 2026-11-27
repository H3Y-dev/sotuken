"""Read-only PC API. Run python -m pc_api.server --help for configuration."""
import argparse
from contextlib import closing, contextmanager
from datetime import date
import hashlib
import hmac
import http.client
from http.server import BaseHTTPRequestHandler
import json
import math
import os
import re
from pathlib import Path, PureWindowsPath
import secrets
import sqlite3
import sys
import threading
import time
from urllib.parse import parse_qs, urlsplit, unquote, quote

from manager.export import filter_readings
from manager.storage import MeterReading
from pc_api.owner import InternalServer, OwnerLock, OwnerConflict
from pc_api.session import (
    SessionStore,
    build_clear_session_cookie,
    build_session_cookie,
    parse_session_cookie,
)


class APIError(Exception):
    def __init__(self, status, code):
        self.status, self.code = status, code


# Same columns, in the same order as Storage.get_all_readings(include_raw=False);
# raw_data_json is never selected. tests/test_pc_api_server.py compares the two.
READING_COLUMNS = (
    'id timestamp device_name value stage image_path image_sha256 reading_id status input_method '
    'confidence failure_stage failure_code failure_detail pipeline_version log_path overlay_path '
    'device_id device_id_source device_id_issue captured_at received_at image_rel '
    'inspection_id inspection_name route_id').split()
SELECT_READINGS = 'SELECT ' + ', '.join(READING_COLUMNS) + ' FROM meter_readings'


class ReadOnlyStorage:
    """Own read path: mode=ro + query_only, no Storage constructor, no DDL."""

    def __init__(self, path):
        self.path = Path(path).resolve()

    def _get_connection(self):
        conn = sqlite3.connect(self.path.as_uri() + '?mode=ro', uri=True, timeout=.25)
        conn.execute('PRAGMA query_only=ON')
        conn.execute('PRAGMA busy_timeout=250')
        return conn

    def _query(self, suffix, params=()):
        with closing(self._get_connection()) as conn:
            rows = conn.execute(SELECT_READINGS + suffix, params).fetchall()
        return [MeterReading(**dict(zip(READING_COLUMNS, row)), raw_data=None) for row in rows]

    def readings(self):
        return self._query(' ORDER BY id DESC')

    def reading(self, row_id):
        rows = self._query(' WHERE id = ?', (row_id,))
        return rows[0] if rows else None


class _DeviceReadStorage:
    """Read-only adapter exposing connection() without running Storage DDL."""

    def __init__(self, ro_storage):
        self._ro = ro_storage

    @contextmanager
    def connection(self):
        with closing(self._ro._get_connection()) as conn:
            yield conn


class _DeviceWriteStorage:
    """Read-write adapter exposing connection() without running Storage DDL."""

    def __init__(self, path):
        self.path = Path(path)

    @contextmanager
    def connection(self):
        conn = sqlite3.connect(self.path, timeout=.25)
        conn.execute('PRAGMA busy_timeout=250')
        try:
            with conn:
                yield conn
        finally:
            conn.close()


def _no_duplicate_keys(pairs):
    obj = {}
    for key, value in pairs:
        if key in obj:
            raise ValueError(f'Duplicate JSON key: {key}')
        obj[key] = value
    return obj


def opened_path(handle):
    """Resolve the opened object, not just the name checked before opening."""
    if os.name == 'nt':
        import ctypes
        import msvcrt
        from ctypes import wintypes
        fn = ctypes.WinDLL('kernel32', use_last_error=True).GetFinalPathNameByHandleW
        fn.argtypes = [wintypes.HANDLE, wintypes.LPWSTR, wintypes.DWORD, wintypes.DWORD]
        fn.restype = wintypes.DWORD
        buf = ctypes.create_unicode_buffer(32768)
        size = fn(msvcrt.get_osfhandle(handle.fileno()), buf, len(buf), 0)
        if not size or size >= len(buf):
            raise OSError('Cannot resolve handle')
        name = buf.value
        if name.startswith('\\\\?\\UNC\\'):
            raise OSError('UNC')
        return Path(name.removeprefix('\\\\?\\')).resolve()
    return Path('/proc/self/fd/' + str(handle.fileno())).resolve(strict=True)


def _is_json_content_type(header_value):
    if not header_value:
        return False
    parts = [p.strip() for p in header_value.split(';')]
    if parts[0].lower() != 'application/json':
        return False
    for param in parts[1:]:
        if not param:
            continue
        k, sep, v = param.partition('=')
        if sep and k.strip().lower() == 'charset':
            if v.strip().strip('"').lower() not in ('utf-8', 'utf8'):
                return False
    return True


class PCAPI:
    def __init__(self, db_path='manager.db', *, incoming_dir=None, image_dirs=(), static_dir=None,
                 owner_port=8767, internal_key='', port=8766, clock=time.monotonic,
                 images_dir=None, overlays_dir=None, reader_func=None):
        self.storage = ReadOnlyStorage(db_path)
        self.incoming_dir = Path(incoming_dir).resolve() if incoming_dir is not None and str(incoming_dir).strip() else None
        self.image_dirs = tuple(Path(p).resolve() for p in image_dirs if str(p).strip())
        # An empty allowlist would silently 404 every image; refuse instead.
        if not self.image_dirs or len(self.image_dirs) != len(tuple(image_dirs)):
            raise ValueError('image_dirs must be non-empty paths (incoming, images, overlays).')
        if any(root == root.parent for root in self.image_dirs):
            raise ValueError('A drive/filesystem root is not allowed as an image root.')
        self.images_dir = (Path(images_dir).resolve() if images_dir is not None
                           else self._default_image_root('images'))
        self.overlays_dir = (Path(overlays_dir).resolve() if overlays_dir is not None
                             else self._default_image_root('overlays'))
        self.reader_func = reader_func
        self.static_dir = Path(static_dir).resolve() if static_dir else None
        self.owner_port, self.internal_key, self.port = owner_port, internal_key, port
        self.sessions = SessionStore(clock=clock)
        self.image_key = secrets.token_bytes(32)
        # Separate role namespace: API and owner may share a DB, two APIs may not.
        self.lock = OwnerLock(self.storage.path, str(self.storage.path) + '.pc-api')
        self.httpd = self.thread = None

    def _default_image_root(self, name):
        for root in self.image_dirs:
            if root.name == name:
                return root
        return self.image_dirs[0]

    def _require_same_origin(self, headers):
        if headers.get_all('Origin', []) != [f'http://127.0.0.1:{self.port}']:
            raise APIError(403, 'forbidden_origin')

    def _require_json_content_type(self, headers):
        if not _is_json_content_type(headers.get('Content-Type')):
            raise APIError(400, 'invalid_request')

    def authenticate_session(self, headers, method, *, require_json=True):
        """Validate session cookie, and for mutating methods also Origin, CSRF, and JSON Content-Type."""
        if 'X-Sotuken-Token' in headers:
            raise APIError(401, 'unauthenticated')
        session_id = parse_session_cookie(headers.get_all('Cookie', []))
        csrf_token = self.sessions.get_session_csrf(session_id)
        if csrf_token is None:
            raise APIError(401, 'unauthenticated')
        if method not in ('GET', 'HEAD'):
            self._require_same_origin(headers)
            csrf_headers = headers.get_all('X-CSRF-Token', [])
            if len(csrf_headers) != 1 or not self.sessions.verify_csrf(session_id, csrf_headers[0]):
                raise APIError(403, 'forbidden_origin')
            if require_json and method in ('POST', 'PUT', 'PATCH', 'DELETE'):
                self._require_json_content_type(headers)
        return session_id, csrf_token

    def image_id(self, row, kind):
        # '<db id>-<o|v>-<hmac>': opaque to clients, lets the server read just one row.
        tag = hmac.new(self.image_key, f'{row.id}:{kind}'.encode(), hashlib.sha256).hexdigest()
        return f'{row.id}-{"o" if kind == "original" else "v"}-{tag}'

    def image_row(self, key):
        """Return (row, kind, stored path) for a valid image id, else None."""
        parts = key.split('-')
        if len(parts) != 3 or not (parts[0].isascii() and parts[0].isdecimal()) or parts[1] not in ('o', 'v'):
            return None
        row = self.storage.reading(int(parts[0]))
        if row is None:
            return None
        kind = 'original' if parts[1] == 'o' else 'overlay'
        stored = row.image_path if kind == 'original' else row.overlay_path
        if not stored or not secrets.compare_digest(key.encode(), self.image_id(row, kind).encode()):
            return None
        return stored

    def dto(self, row):
        fields = ('reading_id device_name device_id captured_at timestamp received_at value '
                  'status stage confidence failure_stage inspection_id inspection_name route_id').split()
        result = {key: getattr(row, key, None) for key in fields}
        for key, value in result.items():
            if isinstance(value, float) and not math.isfinite(value):
                result[key] = None
        return dict(result, id=str(row.id), unit=None,
                    image_id=self.image_id(row, 'original') if row.image_path else None,
                    overlay_image_id=self.image_id(row, 'overlay') if row.overlay_path else None)

    def owner(self, method, path):
        try:
            conn = http.client.HTTPConnection('127.0.0.1', self.owner_port, timeout=1)
            try:
                conn.request(method, path, headers={'X-Internal-Token': self.internal_key})
                response = conn.getresponse()
                body = json.loads(response.read(1024 * 1024))
                if response.status == 409:
                    raise APIError(409, 'owner_conflict')
                if response.status != 200:
                    raise APIError(503, 'owner_unavailable')
                return body
            finally:
                conn.close()
        except (OSError, ValueError, http.client.HTTPException):
            raise APIError(503, 'owner_unavailable') from None

    def allowed(self, path, roots):
        return any(path.is_relative_to(root) and path != root for root in roots)

    def file(self, path, roots):
        try:
            name = str(path)
            win = PureWindowsPath(name)
            if ('..' in Path(name).parts or '..' in win.parts or name.startswith(('\\\\', '//'))
                    or ':' in name[2:] or (win.drive and not win.is_absolute())):
                raise OSError('Unsafe path')
            candidates = [Path(path)]
            if not Path(path).is_absolute():
                candidates.extend(root / Path(name).name for root in roots)
            matches = {}
            for index, candidate in enumerate(candidates):
                try:
                    resolved = candidate.resolve(strict=True)
                except (OSError, ValueError, RuntimeError):
                    continue
                if not self.allowed(resolved, roots):
                    continue
                with resolved.open('rb') as handle:
                    actual = opened_path(handle)
                    if actual == resolved and self.allowed(actual, roots):
                        data = handle.read()
                        if index == 0:
                            return data
                        matches[resolved] = data
            if len(matches) == 1:
                return next(iter(matches.values()))
            raise OSError('Not found')
        except (OSError, ValueError, RuntimeError):
            raise APIError(404, 'not_found') from None

    def dispatch(self, method, target, body=None, session_id=None):
        url = urlsplit(target)
        path = url.path
        if not path.startswith('/api/'):
            if method != 'GET' or url.query:
                raise APIError(404, 'not_found')
            relative = unquote(path).lstrip('/') or 'index.html'
            if relative == 'index.html':
                data = (self.file(self.static_dir / relative, (self.static_dir,))
                        if self.static_dir and (self.static_dir / relative).exists()
                        else b'<!doctype html><html><head></head><body>PC API ready</body></html>')
                return 200, data, 'text/html; charset=utf-8'
            if not self.static_dir:
                raise APIError(404, 'not_found')
            types = {'.js':'text/javascript', '.css':'text/css', '.png':'image/png', '.svg':'image/svg+xml', '.ico':'image/x-icon', '.woff2':'font/woff2'}
            suffix = Path(relative).suffix.lower()
            if suffix not in types:
                raise APIError(404, 'not_found')
            return 200, self.file(self.static_dir / relative, (self.static_dir,)), types[suffix]
        if path == '/api/v1/pairing' and method in ('GET', 'POST', 'DELETE'):
            if url.query:
                raise APIError(400, 'invalid_request')
            body = self.owner(method, '/internal/pairing')
            return (204, None, None) if method == 'DELETE' else (200, body, None)
        if path == '/api/v1/inspections' or path.startswith('/api/v1/inspections/'):
            from pc_api.inspection_routes import dispatch_inspection
            return dispatch_inspection(self, method, url, session_id=session_id, body=body)
        if path == '/api/v1/devices' or path.startswith('/api/v1/devices/'):
            if url.query:
                raise APIError(400, 'invalid_request')
            from pc_api.device_routes import dispatch_devices
            storage = _DeviceReadStorage(self.storage) if method == 'GET' else _DeviceWriteStorage(self.storage.path)
            return dispatch_devices(storage, method, path, body)
        if path == '/api/v1/routes' or path.startswith('/api/v1/routes/'):
            if url.query:
                raise APIError(400, 'invalid_request')
            from pc_api.route_routes import dispatch_routes
            storage = _DeviceReadStorage(self.storage) if method == 'GET' else _DeviceWriteStorage(self.storage.path)
            return dispatch_routes(storage, method, path, body)
        if path == '/api/v1/manual-readings':
            if url.query or method != 'POST':
                raise APIError(400, 'invalid_request')
            from pc_api.manual_routes import dispatch_manual_reading
            return dispatch_manual_reading(self, body)
        if method != 'GET':
            raise APIError(400, 'invalid_request')
        if path in ('/api/v1/runtime', '/api/v1/usb/status'):
            if url.query:
                raise APIError(400, 'invalid_request')
            body = self.owner('GET', '/internal/status')
            metadata = {k: body[k] for k in ('owner_instance_id', 'observed_at')}
            if path.endswith('/runtime'):
                return 200, dict(metadata, receiver_running=body['receiver_running'], receiver_url=body['receiver_url']), None
            usb = dict(enabled=False, running=False, adb_found=False, devices=[], pulled_total=0,
                       last_error=None, interval=5, cycles=0)
            usb.update(body.get('usb') or {})
            return 200, dict(usb, **metadata), None
        if path == '/api/v1/readings':
            query = parse_qs(url.query, keep_blank_values=True)
            if set(query) - {'device_name', 'date_from', 'date_to', 'inspection_id'} or any(len(v) != 1 for v in query.values()):
                raise APIError(400, 'invalid_request')
            query = {k:v[0] for k,v in query.items()}
            try:
                for key in ('date_from', 'date_to'):
                    if key in query:
                        if len(query[key]) != 10:
                            raise ValueError()
                        query[key] = date.fromisoformat(query[key])
                if (len(query.get('device_name', '')) > 256 or len(query.get('inspection_id', '')) > 128
                        or (query.get('date_from') and query.get('date_to') and query['date_from'] > query['date_to'])):
                    raise ValueError()
            except ValueError:
                raise APIError(422, 'validation_failed') from None
            try:
                rows = filter_readings(self.storage.readings(), **query)
            except (ValueError, TypeError):
                raise APIError(503, 'data_invalid') from None
            if len(rows) > 10000:
                raise APIError(422, 'validation_failed')
            return 200, dict(items=[self.dto(r) for r in rows], total=len(rows)), None
        if url.query:
            raise APIError(400, 'invalid_request')
        if path.startswith('/api/v1/readings/'):
            key = path.removeprefix('/api/v1/readings/')
            if key.isascii() and key.isdecimal():
                row = self.storage.reading(int(key))
                if row is not None:
                    return 200, self.dto(row), None
        if path.startswith('/api/v1/images/'):
            stored = self.image_row(path.removeprefix('/api/v1/images/'))
            if stored:
                suffix = Path(stored).suffix.lower()
                if suffix not in ('.png', '.jpg', '.jpeg'):
                    raise APIError(404, 'not_found')
                return 200, self.file(stored, self.image_dirs), 'image/png' if suffix == '.png' else 'image/jpeg'
        raise APIError(404, 'not_found')

    def start(self):
        if self.httpd:
            raise OwnerConflict('API already started')
        self.lock.acquire()
        api = self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def handle_api(self):
                set_cookie = None
                body_read = 0
                try:
                    if (self.headers.get_all('Host', []) != [f'127.0.0.1:{api.port}']
                            or any(h in self.headers for h in ('Forwarded', 'X-Forwarded-Host', 'X-Forwarded-For', 'X-Forwarded-Proto'))
                            or ('Origin' in self.headers and self.headers.get_all('Origin') != [f'http://127.0.0.1:{api.port}'])):
                        raise APIError(403, 'forbidden_origin')
                    parsed_url = urlsplit(self.path)
                    length = self.headers.get('Content-Length', '0')
                    if 'Transfer-Encoding' in self.headers or not length.isdecimal():
                        raise APIError(400, 'invalid_request')
                    is_device_write = (
                        (parsed_url.path == '/api/v1/devices' and self.command == 'POST')
                        or (parsed_url.path.startswith('/api/v1/devices/id-') and self.command == 'PUT')
                    )
                    is_csv_write = self.command == 'POST' and bool(re.fullmatch(r'/api/v1/inspections/[^/]+/csv(?:/save)?', parsed_url.path))
                    is_route_write = (
                        (parsed_url.path == '/api/v1/routes' and self.command == 'POST')
                        or (parsed_url.path.startswith('/api/v1/routes/') and self.command == 'PUT')
                    )
                    is_manual_upload = (
                        parsed_url.path == '/api/v1/manual-readings' and self.command == 'POST')
                    max_body_bytes = (20 * 1024 * 1024 if is_manual_upload
                                      else 65536 if is_route_write else 16384 if is_device_write
                                      else 4096 if is_csv_write else 1024)
                    if int(length) > max_body_bytes:
                        raise APIError(413, 'too_large')
                    def read_json_body():
                        try:
                            nonlocal body_read
                            raw = self.rfile.read(int(length))
                            body_read = len(raw)
                            return json.loads(
                                raw.decode('utf-8'),
                                object_pairs_hook=_no_duplicate_keys,
                            )
                        except (ValueError, UnicodeError):
                            raise APIError(400, 'invalid_request') from None

                    if parsed_url.path == '/api/v1/session':
                        if 'X-Sotuken-Token' in self.headers:
                            raise APIError(401, 'unauthenticated')
                        if parsed_url.query:
                            raise APIError(400, 'invalid_request')
                        if self.command == 'POST':
                            api._require_same_origin(self.headers)
                            api._require_json_content_type(self.headers)
                            payload = read_json_body()
                            if not isinstance(payload, dict) or set(payload) != {'launch_key'} or not isinstance(payload['launch_key'], str):
                                raise APIError(400, 'invalid_request')
                            exchanged = api.sessions.exchange_launch_key(payload['launch_key'])
                            if exchanged is None:
                                raise APIError(401, 'unauthenticated')
                            session_id, csrf_token = exchanged
                            set_cookie = build_session_cookie(session_id)
                            status, body, mime = 200, {'csrf_token': csrf_token}, None
                        elif self.command in ('GET', 'DELETE'):
                            session_id, csrf_token = api.authenticate_session(self.headers, self.command)
                            if self.command == 'DELETE' or int(length):
                                if read_json_body() != {}:
                                    raise APIError(400, 'invalid_request')
                            if self.command == 'GET':
                                status, body, mime = 200, {'csrf_token': csrf_token}, None
                            else:
                                api.sessions.revoke_session(session_id)
                                from pc_api.inspection_pages import discard_session_pages
                                discard_session_pages(session_id)
                                set_cookie = build_clear_session_cookie()
                                status, body, mime = 204, None, None
                        else:
                            api.authenticate_session(self.headers, self.command)
                            raise APIError(400, 'invalid_request')
                    else:
                        request_body = None
                        session_id = None
                        if parsed_url.path.startswith('/api/'):
                            session_id, _ = api.authenticate_session(
                                self.headers, self.command, require_json=not is_manual_upload)
                            if is_manual_upload:
                                content_type = self.headers.get('Content-Type', '')
                                if not content_type.lower().startswith('multipart/form-data'):
                                    raise APIError(400, 'invalid_request')
                                raw = self.rfile.read(int(length))
                                body_read = len(raw)
                                request_body = (content_type, raw)
                            elif is_device_write or is_csv_write or is_route_write:
                                request_body = read_json_body()
                            elif self.command in ('POST', 'PUT', 'PATCH', 'DELETE') or int(length):
                                if read_json_body() != {}:
                                    raise APIError(400, 'invalid_request')
                        elif int(length):
                            if read_json_body() != {}:
                                raise APIError(400, 'invalid_request')
                        status, body, mime = api.dispatch(
                            self.command, self.path, body=request_body, session_id=session_id
                        )
                except APIError as exc:
                    status, body, mime = exc.status, {'error': {'code':exc.code, 'message':exc.code, 'request_id':secrets.token_hex(8)}}, None
                except sqlite3.Error as exc:
                    msg = str(exc).lower()
                    code = 'db_busy' if 'locked' in msg or 'busy' in msg else 'data_invalid'
                    status, body, mime = 503, {'error':{'code':code, 'message':code, 'request_id':secrets.token_hex(8)}}, None
                except Exception:
                    # Unexpected: no detail to the client (no paths, keys, or messages).
                    status, body, mime = 500, {'error':{'code':'internal_error', 'message':'internal_error', 'request_id':secrets.token_hex(8)}}, None
                if status >= 400:
                    try:
                        lengths = self.headers.get_all('Content-Length', [])
                        if len(lengths) == 1 and not self.headers.get('Transfer-Encoding'):
                            remaining = int(lengths[0]) - body_read
                            if 0 < remaining <= 1024 * 1024:
                                deadline = time.monotonic() + 1.0
                                while remaining > 0:
                                    timeout = deadline - time.monotonic()
                                    if timeout <= 0:
                                        break
                                    self.connection.settimeout(timeout)
                                    try:
                                        chunk = self.rfile.read1(min(65536, remaining))
                                    except OSError:
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
                self.connection.settimeout(None)
                csv_filename = None
                if mime and mime.startswith('text/csv') and status == 200:
                    body, csv_filename = body
                data = b'' if body is None else body if isinstance(body, bytes) else json.dumps(body, ensure_ascii=False, allow_nan=False).encode('utf-8')
                self.send_response(status)
                self.send_header('Content-Length', str(len(data)))
                self.send_header('Content-Type', mime or 'application/json; charset=utf-8')
                if mime and mime.startswith('text/csv') and status == 200:
                    self.send_header('Content-Disposition', f"attachment; filename=\"inspection.csv\"; filename*=UTF-8''{quote(csv_filename)}")
                self.send_header('Cache-Control', 'no-store')
                self.send_header('X-Content-Type-Options', 'nosniff')
                self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; img-src 'self' blob:; object-src 'none'; frame-ancestors 'none'; base-uri 'none'")
                if set_cookie:
                    self.send_header('Set-Cookie', set_cookie)
                if status == 503:
                    self.send_header('Retry-After', '1')
                self.end_headers()
                if self.command != 'HEAD':
                    self.wfile.write(data)
            do_GET = do_POST = do_DELETE = do_OPTIONS = do_PUT = handle_api
            do_HEAD = do_PATCH = do_TRACE = do_CONNECT = handle_api
        try:
            self.httpd = InternalServer(('127.0.0.1', self.port), Handler)
            self.port = self.httpd.server_address[1]
            self.thread = threading.Thread(target=lambda: self.httpd.serve_forever(poll_interval=.05))
            self.thread.start()
        except BaseException:
            self.stop()
            raise

    def stop(self):
        if self.httpd:
            if self.thread:
                self.httpd.shutdown()
                self.thread.join()
            self.httpd.server_close()
        self.httpd = self.thread = None
        self.sessions.clear()
        self.lock.release()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db', default='manager.db')
    # Image allowlist roots: required so the API can never start with every image 404.
    parser.add_argument('--incoming-dir', required=True, help='Receiver incoming folder')
    parser.add_argument('--images-dir', required=True, help='Stored original images folder')
    parser.add_argument('--overlays-dir', required=True, help='Stored overlay images folder')
    parser.add_argument('--static-dir')
    parser.add_argument('--port', type=int, default=8766, help='Loopback port; Host/Origin must match it')
    parser.add_argument('--owner-port', type=int, default=8767, help='Owner internal port')
    parser.add_argument('--internal-key-file', required=True, help='Private UTF-8 file supplied by the owner launcher')
    parser.add_argument('--launch-key-out', help='Existing private UTF-8 file to write the initial one-time launch key')
    parser.add_argument('--print-url', action='store_true', help='Print the launch URL with key even when stdout is not a tty')
    args = parser.parse_args()
    if not Path(args.db).is_file():
        parser.error(f'--db file not found: {args.db} (the API never creates the DB)')
    if args.launch_key_out:
        launch_key_out = Path(args.launch_key_out)
        if launch_key_out.is_symlink() or not launch_key_out.is_file():
            parser.error(f'--launch-key-out must be an existing regular file: {args.launch_key_out}')
    try:
        api = PCAPI(args.db, incoming_dir=args.incoming_dir,
                    image_dirs=[args.incoming_dir, args.images_dir, args.overlays_dir],
                    images_dir=args.images_dir, overlays_dir=args.overlays_dir,
                    static_dir=args.static_dir, owner_port=args.owner_port, port=args.port,
                    internal_key=Path(args.internal_key_file).read_text(encoding='utf-8').strip())
    except ValueError as exc:
        parser.error(str(exc))
    if args.launch_key_out:
        launch_key = api.sessions.issue_launch_key()
        Path(args.launch_key_out).write_text(launch_key, encoding='utf-8')
        api.start()
    else:
        api.start()
        launch_key = api.sessions.issue_launch_key()
        if args.print_url or sys.stdout.isatty():
            print(f'http://127.0.0.1:{api.port}/#k={launch_key}', flush=True)
        else:
            print('起動URLは対話端末でのみ表示します。--print-url で明示表示', flush=True)
    try:
        api.thread.join()
    except KeyboardInterrupt:
        pass
    finally:
        api.stop()


if __name__ == '__main__':
    # Route modules import pc_api.server; keep one module identity under -m.
    sys.modules['pc_api.server'] = sys.modules[__name__]
    main()
