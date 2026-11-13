"""Run with ``python -m pc_api.owner [--usb-pull]`` from the data directory.

The internal key is available to an in-process launcher as ``internal_key``;
it is deliberately never printed or served to the browser.
"""
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import secrets
import socket
import sys
import tempfile
import threading
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer

from manager.receiver import init_receiver_for_app, get_default_incoming_dir
from manager.usb_pull_service import init_usb_pull_for_app


class OwnerConflict(RuntimeError):
    pass


class InternalServer(HTTPServer):
    allow_reuse_address = False
    request_queue_size = 64

    def server_bind(self):
        if os.name == 'nt':
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()

    def get_request(self):
        connection, address = super().get_request()
        connection.settimeout(1.0)
        return connection, address


class OwnerLock:
    """OS byte lock, released automatically on process death (including Windows)."""
    def __init__(self, db_path, incoming):
        key = '\0'.join(os.path.normcase(str(Path(p).resolve())) for p in (db_path, incoming))
        digest = hashlib.sha256(key.encode('utf-8')).hexdigest()
        self.path = Path(tempfile.gettempdir()) / ('sotuken-owner-' + digest + '.lock')
        self.file = None

    def acquire(self):
        handle = self.path.open('a+b')
        try:
            handle.seek(0, 2)
            if not handle.tell():
                handle.write(b'0')
                handle.flush()
            handle.seek(0)
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            handle.close()
            raise OwnerConflict('Another owner holds this DB/incoming.') from exc
        self.file = handle

    def release(self):
        if self.file is not None:
            self.file.close()
            self.file = None


class Owner:
    def __init__(self, db_path='manager.db', incoming=None, *, usb=False, port=8767):
        self.db_path = Path(db_path).resolve()
        self.incoming = Path(incoming or get_default_incoming_dir()).resolve()
        self.lock = OwnerLock(self.db_path, self.incoming)
        self.usb_enabled = usb
        self.port = port
        self.httpd = self.thread = self.usb = self.receiver_info = None
        self.internal_key = secrets.token_hex(32)
        self.instance_id = secrets.token_hex(16)
        self.operation_lock = threading.Lock()

    def start(self):
        if self.httpd is not None:
            raise OwnerConflict('Owner already started.')
        self.lock.acquire()
        try:
            # Bind before services: a conflicting management listener causes no startup.
            owner = self

            class Handler(BaseHTTPRequestHandler):
                def log_message(self, *args):
                    pass

                def handle_request(self):
                    code, body = 403, {'error': 'forbidden'}
                    hosts = self.headers.get_all('Host', [])
                    keys = self.headers.get_all('X-Internal-Token', [])
                    if (ipaddress.ip_address(self.client_address[0]).is_loopback
                            and hosts == [f'127.0.0.1:{owner.port}']
                            and 'Origin' not in self.headers
                            and not any(h in self.headers for h in ('Forwarded', 'X-Forwarded-Host', 'X-Forwarded-For', 'X-Forwarded-Proto'))):
                        if (len(keys) != 1 or not keys[0].isascii()
                                or not secrets.compare_digest(keys[0], owner.internal_key)
                                or 'X-Sotuken-Token' in self.headers):
                            code, body = 401, {'error': 'unauthenticated'}
                        else:
                            try:
                                code, body = owner.dispatch(self.command, self.path)
                            except Exception:
                                code, body = 503, {'error': 'owner_unavailable'}
                    body.update(owner_instance_id=owner.instance_id,
                                observed_at=datetime.now(timezone.utc).isoformat())
                    data = json.dumps(body, ensure_ascii=False).encode('utf-8')
                    self.send_response(code)
                    self.send_header('Content-Type', 'application/json; charset=utf-8')
                    self.send_header('Content-Length', str(len(data)))
                    self.send_header('Cache-Control', 'no-store')
                    self.send_header('X-Content-Type-Options', 'nosniff')
                    self.end_headers()
                    self.wfile.write(data)

                do_GET = do_POST = do_DELETE = handle_request

            self.httpd = InternalServer(('127.0.0.1', self.port), Handler)
            self.httpd.timeout = 0.2
            self.port = self.httpd.server_address[1]
            info = init_receiver_for_app(incoming_dir=str(self.incoming))
            if not info.get('running') or info.get('external_process') or info.get('server') is None:
                raise OwnerConflict('Stop the existing run_pc.py receiver, then restart via pc_api.owner.')
            self.receiver_info = info
            if self.usb_enabled:
                self.usb = init_usb_pull_for_app(incoming_dir=str(self.incoming))
            self.thread = threading.Thread(target=lambda: self.httpd.serve_forever(poll_interval=0.1),
                                           name='SotukenOwnerInternal')
            self.thread.start()
        except BaseException:
            self.stop()
            raise

    def dispatch(self, method, path):
        with self.operation_lock:
            info = init_receiver_for_app()  # Refresh current LAN URL using existing cache.
            server = self.receiver_info['server']
            if path == '/internal/status' and method == 'GET':
                return 200, dict(receiver_running=bool(info['running']), receiver_url=info['url'],
                                 usb={'enabled':self.usb is not None, **(self.usb.status() if self.usb else {})})
            if path != '/internal/pairing' or method not in ('GET', 'POST', 'DELETE'):
                return 404, {'error':'not_found'}
            status = server.pairing_status()
            if status and status['payload']['url'] != info['url']:
                server.cancel_pairing()
                status = None
            if method == 'DELETE':
                server.cancel_pairing()
                status = None
            elif method == 'POST':
                if status:
                    return 409, {'error':'pairing_active'}
                server.start_pairing(info['url'])
                status = server.pairing_status()
            payload = server.pairing_payload() if status else None
            return 200, dict(active=bool(status and payload), payload=payload,
                             expires_at=status['payload'].get('expires_at') if status and payload else None,
                             remaining_seconds=status['remaining'] if status and payload else 0)

    def stop(self):
        try:
            if self.httpd:
                if self.thread:
                    self.httpd.shutdown()
                    self.thread.join()
                self.httpd.server_close()
                self.httpd = self.thread = None
        finally:
            try:
                if self.usb:
                    # Existing stop defaults to 5s, which can expire during adb I/O.
                    self.usb.stop(timeout=None)
                    self.usb = None
            finally:
                try:
                    if self.receiver_info:
                        server = self.receiver_info['server']
                        server.shutdown()
                        server.server_close()
                        thread = self.receiver_info.get('thread')
                        if thread:
                            thread.join()
                        self.receiver_info = None
                finally:
                    self.lock.release()

    def run(self):
        import run_pc
        if self.db_path != (Path.cwd() / 'manager.db').resolve():
            raise ValueError('run_pc requires manager.db in the current data directory.')
        self.start()
        try:
            run_pc.main()
        finally:
            self.stop()


def main():
    # app.py uses a cwd-relative DB, so callers must select the data cwd explicitly.
    Owner(usb='--usb-pull' in sys.argv[1:]).run()


if __name__ == '__main__':
    main()
