"""Read-only PC API. Run python -m pc_api.server --help for configuration."""
import argparse
from contextlib import closing
from datetime import date
import hashlib
import hmac
import http.client
from http.server import BaseHTTPRequestHandler
import json
import math
import os
from pathlib import Path, PureWindowsPath
import re
import secrets
import sqlite3
import threading
from urllib.parse import parse_qs, urlsplit, unquote

from manager.export import filter_readings
from manager.storage import MeterReading
from pc_api.owner import InternalServer, OwnerLock, OwnerConflict


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


class PCAPI:
    def __init__(self, db_path='manager.db', *, image_dirs=(), static_dir=None,
                 owner_port=8767, internal_key='', port=8766):
        self.storage = ReadOnlyStorage(db_path)
        self.image_dirs = tuple(Path(p).resolve() for p in image_dirs if str(p).strip())
        # An empty allowlist would silently 404 every image; refuse instead.
        if not self.image_dirs or len(self.image_dirs) != len(tuple(image_dirs)):
            raise ValueError('image_dirs must be non-empty paths (incoming, images, overlays).')
        if any(root == root.parent for root in self.image_dirs):
            raise ValueError('A drive/filesystem root is not allowed as an image root.')
        self.static_dir = Path(static_dir).resolve() if static_dir else None
        self.owner_port, self.internal_key, self.port = owner_port, internal_key, port
        self.token = secrets.token_hex(32)
        self.image_key = secrets.token_bytes(32)
        # Separate role namespace: API and owner may share a DB, two APIs may not.
        self.lock = OwnerLock(self.storage.path, str(self.storage.path) + '.pc-api')
        self.httpd = self.thread = None

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
            resolved = Path(path).resolve(strict=True)
            if not self.allowed(resolved, roots):
                raise OSError('Outside roots')
            with resolved.open('rb') as handle:
                actual = opened_path(handle)
                if actual != resolved or not self.allowed(actual, roots):
                    raise OSError('Changed path')
                return handle.read()
        except (OSError, ValueError, RuntimeError):
            raise APIError(404, 'not_found') from None

    def dispatch(self, method, target):
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
                meta = f'<meta name="pc-token" content="{self.token}">'.encode()
                # Keep the doctype first and place credentials in the document head.
                head = re.search(br'<head(?:\s[^>]*)?>', data, re.IGNORECASE)
                if head:
                    data = data[:head.end()] + meta + data[head.end():]
                else:
                    data = b'<!doctype html><html><head>' + meta + b'</head><body>' + data + b'</body></html>'
                return 200, data, 'text/html; charset=utf-8'
            if not self.static_dir:
                raise APIError(404, 'not_found')
            types = {'.js':'text/javascript', '.css':'text/css', '.png':'image/png', '.svg':'image/svg+xml', '.ico':'image/x-icon'}
            suffix = Path(relative).suffix.lower()
            if suffix not in types:
                raise APIError(404, 'not_found')
            return 200, self.file(self.static_dir / relative, (self.static_dir,)), types[suffix]
        if path == '/api/v1/pairing' and method in ('GET', 'POST', 'DELETE'):
            if url.query:
                raise APIError(400, 'invalid_request')
            body = self.owner(method, '/internal/pairing')
            return (204, None, None) if method == 'DELETE' else (200, body, None)
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
                try:
                    if (self.headers.get_all('Host', []) != [f'127.0.0.1:{api.port}']
                            or any(h in self.headers for h in ('Forwarded', 'X-Forwarded-Host', 'X-Forwarded-For', 'X-Forwarded-Proto'))
                            or ('Origin' in self.headers and self.headers.get_all('Origin') != [f'http://127.0.0.1:{api.port}'])):
                        raise APIError(403, 'forbidden_origin')
                    if urlsplit(self.path).path.startswith('/api/'):
                        tokens = self.headers.get_all('X-PC-Token', [])
                        if (len(tokens) != 1 or not tokens[0].isascii() or not secrets.compare_digest(tokens[0], api.token)
                                or 'X-Sotuken-Token' in self.headers):
                            raise APIError(401, 'unauthenticated')
                    length = self.headers.get('Content-Length', '0')
                    if 'Transfer-Encoding' in self.headers or not length.isdecimal():
                        raise APIError(400, 'invalid_request')
                    if int(length) > 1024:
                        raise APIError(413, 'too_large')
                    if int(length):
                        try:
                            if json.loads(self.rfile.read(int(length))) != {}:
                                raise ValueError()
                        except (ValueError, UnicodeError):
                            raise APIError(400, 'invalid_request') from None
                    status, body, mime = api.dispatch(self.command, self.path)
                except APIError as exc:
                    status, body, mime = exc.status, {'error': {'code':exc.code, 'message':exc.code, 'request_id':secrets.token_hex(8)}}, None
                except sqlite3.Error as exc:
                    code = 'db_busy' if 'locked' in str(exc) or 'busy' in str(exc) else 'data_invalid'
                    status, body, mime = 503, {'error':{'code':code, 'message':code, 'request_id':secrets.token_hex(8)}}, None
                except Exception:
                    # Unexpected: no detail to the client (no paths, keys, or messages).
                    status, body, mime = 500, {'error':{'code':'internal_error', 'message':'internal_error', 'request_id':secrets.token_hex(8)}}, None
                data = b'' if body is None else body if isinstance(body, bytes) else json.dumps(body, ensure_ascii=False, allow_nan=False).encode('utf-8')
                self.send_response(status)
                self.send_header('Content-Length', str(len(data)))
                self.send_header('Content-Type', mime or 'application/json; charset=utf-8')
                self.send_header('Cache-Control', 'no-store')
                self.send_header('X-Content-Type-Options', 'nosniff')
                self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; img-src 'self' blob:; object-src 'none'; frame-ancestors 'none'; base-uri 'none'")
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
    args = parser.parse_args()
    if not Path(args.db).is_file():
        parser.error(f'--db file not found: {args.db} (the API never creates the DB)')
    try:
        api = PCAPI(args.db, image_dirs=[args.incoming_dir, args.images_dir, args.overlays_dir],
                    static_dir=args.static_dir, owner_port=args.owner_port, port=args.port,
                    internal_key=Path(args.internal_key_file).read_text(encoding='utf-8').strip())
    except ValueError as exc:
        parser.error(str(exc))
    api.start()
    try:
        api.thread.join()
    except KeyboardInterrupt:
        pass
    finally:
        api.stop()


if __name__ == '__main__':
    main()
