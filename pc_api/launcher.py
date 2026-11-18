"""Verification launcher wiring Owner (P1) and standalone PCAPI (P2).

Starts the loopback Owner process with a private temporary internal-key file,
launches `python -m pc_api.server` serving the bundled React static files
without requiring Node.js, removes the temporary key file once P2 is ready,
and shuts down P2 before P1 on exit.
"""

import argparse
from contextlib import contextmanager
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time

from pc_api.owner import Owner

DEFAULT_STATIC_DIR = Path(__file__).resolve().parent / 'static'


def _write_private_key_file(directory: Path, key: str) -> Path:
    key_path = directory / 'owner-key.txt'
    fd = os.open(str(key_path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        os.write(fd, key.encode('utf-8'))
    finally:
        os.close(fd)
    if os.name == 'nt':
        user = os.environ.get('USERNAME')
        if not user:
            key_path.unlink(missing_ok=True)
            raise RuntimeError('USERNAME is not set; cannot restrict key file ACL.')
        try:
            res = subprocess.run(
                ['icacls', str(key_path), '/inheritance:r', '/grant:r', f'{user}:(R,W)'],
                capture_output=True,
                check=False,
            )
        except OSError as exc:
            key_path.unlink(missing_ok=True)
            raise RuntimeError(f'icacls failed while securing key file: {exc}') from exc
        if res.returncode != 0:
            key_path.unlink(missing_ok=True)
            raise RuntimeError(f'icacls failed with exit code {res.returncode}.')
    return key_path


def _ensure_port_available(port: int) -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        if os.name == 'nt':
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        try:
            sock.bind(('127.0.0.1', port))
        except OSError as exc:
            raise RuntimeError(f'Port 127.0.0.1:{port} is already in use.') from exc


def _wait_tcp(port: int, proc: subprocess.Popen, timeout: float = 10.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            raise RuntimeError(f'pc_api.server exited prematurely with code {proc.returncode}')
        try:
            with socket.create_connection(('127.0.0.1', port), timeout=0.2):
                return
        except OSError:
            time.sleep(0.05)
    raise TimeoutError(f'Timed out waiting for pc_api.server on 127.0.0.1:{port}')


def _check_watch_inbox_pid(pid: int | None) -> None:
    if pid is None:
        print('watch_inbox の確認を省略しました（--watch-inbox-pid 未指定）', file=sys.stderr)
        return
    if pid <= 0:
        raise ValueError(f'Invalid --watch-inbox-pid: {pid}')
    if os.name == 'nt':
        res = subprocess.run(
            ['tasklist', '/FI', f'PID eq {pid}', '/NH'],
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='replace',
            check=False,
        )
        if str(pid) not in res.stdout:
            raise RuntimeError(f'Recorded watch_inbox PID {pid} is not running.')
        cmd_res = subprocess.run(
            [
                'powershell',
                '-NoProfile',
                '-Command',
                f"(Get-CimInstance Win32_Process -Filter 'ProcessId={int(pid)}').CommandLine",
            ],
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='replace',
            check=False,
        )
        cmdline = cmd_res.stdout.strip() if cmd_res.returncode == 0 else ''
    else:
        try:
            os.kill(pid, 0)
        except OSError as exc:
            raise RuntimeError(f'Recorded watch_inbox PID {pid} is not running.') from exc
        try:
            cmdline = Path(f'/proc/{int(pid)}/cmdline').read_bytes().replace(b'\x00', b' ').decode('utf-8', errors='replace')
        except OSError:
            cmdline = ''
    if 'manager.watch_inbox' not in cmdline:
        raise ValueError(f'PID {pid} is not manager.watch_inbox (cmdline: {cmdline!r})')


class VerificationLauncher:
    def __init__(
        self,
        *,
        db_path='manager.db',
        incoming_dir='incoming',
        images_dir='images',
        overlays_dir='overlays',
        static_dir=DEFAULT_STATIC_DIR,
        port=8766,
        owner_port=8767,
        usb=False,
        watch_inbox_pid=None,
    ):
        self.db_path = Path(db_path).resolve()
        self.incoming_dir = Path(incoming_dir).resolve()
        self.images_dir = Path(images_dir).resolve()
        self.overlays_dir = Path(overlays_dir).resolve()
        self.static_dir = Path(static_dir).resolve() if static_dir else None
        self.port = int(port)
        self.owner_port = int(owner_port)
        self.usb = bool(usb)
        self.watch_inbox_pid = watch_inbox_pid
        self.owner: Owner | None = None
        self.api_proc: subprocess.Popen | None = None

    def start(self) -> None:
        if not self.db_path.is_file():
            raise FileNotFoundError(f'DB file not found: {self.db_path}')
        _check_watch_inbox_pid(self.watch_inbox_pid)
        _ensure_port_available(self.port)
        self.owner = Owner(
            db_path=self.db_path,
            incoming=self.incoming_dir,
            usb=self.usb,
            port=self.owner_port,
        )
        self.owner.start()
        try:
            with tempfile.TemporaryDirectory(prefix='sotuken-key-') as key_dir:
                key_file = _write_private_key_file(Path(key_dir), self.owner.internal_key)
                cmd = [
                    sys.executable,
                    '-m',
                    'pc_api.server',
                    '--db',
                    str(self.db_path),
                    '--incoming-dir',
                    str(self.incoming_dir),
                    '--images-dir',
                    str(self.images_dir),
                    '--overlays-dir',
                    str(self.overlays_dir),
                    '--port',
                    str(self.port),
                    '--owner-port',
                    str(self.owner.port),
                    '--internal-key-file',
                    str(key_file),
                ]
                if self.static_dir and self.static_dir.is_dir():
                    cmd.extend(['--static-dir', str(self.static_dir)])
                env = os.environ.copy()
                repo_root = str(Path(__file__).resolve().parent.parent)
                existing_pp = env.get('PYTHONPATH', '')
                env['PYTHONPATH'] = f'{repo_root}{os.pathsep}{existing_pp}' if existing_pp else repo_root
                self.api_proc = subprocess.Popen(cmd, cwd=str(self.db_path.parent), env=env)
                _wait_tcp(self.port, self.api_proc)
        except BaseException:
            self.stop()
            raise

    def stop(self) -> None:
        try:
            if self.api_proc is not None:
                if self.api_proc.poll() is None:
                    self.api_proc.terminate()
                    try:
                        self.api_proc.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        self.api_proc.kill()
                        self.api_proc.wait(timeout=5)
                self.api_proc = None
        finally:
            if self.owner is not None:
                self.owner.stop()
                self.owner = None


@contextmanager
def launch_verification(**kwargs):
    launcher = VerificationLauncher(**kwargs)
    launcher.start()
    try:
        yield launcher
    finally:
        launcher.stop()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db', default='manager.db')
    parser.add_argument('--incoming-dir', default='incoming')
    parser.add_argument('--images-dir', default='images')
    parser.add_argument('--overlays-dir', default='overlays')
    parser.add_argument('--static-dir', default=str(DEFAULT_STATIC_DIR))
    parser.add_argument('--port', type=int, default=8766)
    parser.add_argument('--owner-port', type=int, default=8767)
    parser.add_argument('--usb-pull', action='store_true')
    parser.add_argument('--no-streamlit', action='store_true')
    parser.add_argument('--watch-inbox-pid', type=int, default=None)
    args = parser.parse_args(argv)

    launcher = VerificationLauncher(
        db_path=args.db,
        incoming_dir=args.incoming_dir,
        images_dir=args.images_dir,
        overlays_dir=args.overlays_dir,
        static_dir=args.static_dir,
        port=args.port,
        owner_port=args.owner_port,
        usb=args.usb_pull,
        watch_inbox_pid=args.watch_inbox_pid,
    )
    exit_code = 0
    launcher.start()
    try:
        if args.no_streamlit:
            while launcher.api_proc and launcher.api_proc.poll() is None:
                time.sleep(0.5)
            if launcher.api_proc is not None and launcher.api_proc.returncode:
                exit_code = launcher.api_proc.returncode
        else:
            import run_pc
            if launcher.db_path != (Path.cwd() / 'manager.db').resolve():
                raise ValueError('run_pc requires manager.db in the current working directory.')
            saved_argv = sys.argv
            sys.argv = [sys.argv[0]] + (['--usb-pull'] if args.usb_pull else [])
            try:
                run_pc.main()
            finally:
                sys.argv = saved_argv
    except KeyboardInterrupt:
        pass
    finally:
        launcher.stop()
    return exit_code


if __name__ == '__main__':
    raise SystemExit(main())
