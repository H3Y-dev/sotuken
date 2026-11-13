"""End-to-end browser verification & Section 6 latency measurement for React + PC API.

Runs the bundled static build (pc_api/static) without Node.js / Vite,
connects real Owner + ReceiverServer + PCAPI + SQLite + headless Chrome via CDP,
and outputs JSON metrics plus verification screenshots.
"""

import argparse
import base64
import hashlib
import http.client
import json
import os
from pathlib import Path
import socket
import sqlite3
import struct
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from manager.export import filter_readings, latest_per_device
from manager.ingest import ingest_result
from manager.manager import MeterManager
from manager.pipeline_caller import execute_pipeline
from manager.receiver import ReceiverServer
from manager.sidecar import load_sidecar
from manager.storage import Storage
from pc_api.launcher import _wait_tcp, _write_private_key_file
from pc_api.owner import Owner

DEFAULT_CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
DEFAULT_EDGE = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
FIXTURE_PNG = REPO_ROOT / "tests" / "fixtures" / "20260714_095649_644.png"
STATIC_DIR = REPO_ROOT / "pc_api" / "static"


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class CDPClient:
    def __init__(self, ws_url: str):
        rest = ws_url[5:]
        host_port, path = rest.split("/", 1)
        host, port = host_port.split(":")
        self.sock = socket.create_connection((host, int(port)), timeout=20)
        key = base64.b64encode(os.urandom(16)).decode()
        req = (
            f"GET /{path} HTTP/1.1\r\n"
            f"Host: {host_port}\r\n"
            f"Upgrade: websocket\r\n"
            f"Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            f"Sec-WebSocket-Version: 13\r\n\r\n"
        )
        self.sock.sendall(req.encode())
        buf = b""
        while b"\r\n\r\n" not in buf:
            buf += self.sock.recv(4096)
        self._extra = buf.split(b"\r\n\r\n", 1)[1]
        self._id = 0
        self.events: list[dict] = []

    def _recv_exact(self, n: int) -> bytes:
        out = bytearray()
        if self._extra:
            take = min(n, len(self._extra))
            out += self._extra[:take]
            self._extra = self._extra[take:]
        while len(out) < n:
            chunk = self.sock.recv(n - len(out))
            if not chunk:
                raise EOFError("WebSocket closed")
            out += chunk
        return bytes(out)

    def _recv_frame(self):
        b1, b2 = self._recv_exact(2)
        opcode = b1 & 0x0F
        masked = b2 & 0x80
        ln = b2 & 0x7F
        if ln == 126:
            ln = struct.unpack("!H", self._recv_exact(2))[0]
        elif ln == 127:
            ln = struct.unpack("!Q", self._recv_exact(8))[0]
        mask = self._recv_exact(4) if masked else b""
        payload = self._recv_exact(ln)
        if masked:
            payload = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
        return opcode, payload

    def _send_text(self, text: str):
        data = text.encode("utf-8")
        header = bytearray([0x81])
        ln = len(data)
        mask = os.urandom(4)
        if ln < 126:
            header.append(0x80 | ln)
        elif ln < 65536:
            header.append(0x80 | 126)
            header.extend(struct.pack("!H", ln))
        else:
            header.append(0x80 | 127)
            header.extend(struct.pack("!Q", ln))
        header.extend(mask)
        masked = bytes(b ^ mask[i % 4] for i, b in enumerate(data))
        self.sock.sendall(bytes(header) + masked)

    def call(self, method: str, params=None):
        self._id += 1
        mid = self._id
        self._send_text(json.dumps({"id": mid, "method": method, "params": params or {}}))
        while True:
            op, payload = self._recv_frame()
            if op == 8:
                raise EOFError("WebSocket close frame")
            if op == 9:
                continue
            msg = json.loads(payload.decode("utf-8"))
            if "id" in msg and msg["id"] == mid:
                if "error" in msg:
                    raise RuntimeError(msg["error"])
                return msg.get("result", {})
            self.events.append(msg)

    def eval(self, expr: str):
        res = self.call(
            "Runtime.evaluate",
            {"expression": expr, "returnByValue": True, "awaitPromise": True},
        )
        if "exceptionDetails" in res:
            raise RuntimeError(res["exceptionDetails"])
        return res.get("result", {}).get("value")

    def screenshot(self, path: Path, width=1366, height=900, full=True):
        self.call(
            "Emulation.setDeviceMetricsOverride",
            {"width": width, "height": height, "deviceScaleFactor": 1, "mobile": False},
        )
        time.sleep(0.15)
        if full:
            metrics = self.call("Page.getLayoutMetrics")
            ch = int(metrics["cssContentSize"]["height"])
            self.call(
                "Emulation.setDeviceMetricsOverride",
                {"width": width, "height": max(height, ch + 20), "deviceScaleFactor": 1, "mobile": False},
            )
            time.sleep(0.1)
        data = base64.b64decode(
            self.call("Page.captureScreenshot", {"format": "png", "fromSurface": True})["data"]
        )
        path.write_bytes(data)
        self.call(
            "Emulation.setDeviceMetricsOverride",
            {"width": width, "height": height, "deviceScaleFactor": 1, "mobile": False},
        )

    def close(self):
        self.sock.close()


class FakeUsbService:
    def __init__(self):
        self.lock = threading.Lock()
        self._status = {
            "running": True,
            "adb_found": True,
            "devices": ["emulator-5554"],
            "pulled_total": 0,
            "last_error": None,
            "interval": 5,
            "cycles": 1,
        }

    def set_state(self, **kwargs):
        with self.lock:
            self._status.update(kwargs)

    def status(self):
        with self.lock:
            return dict(self._status, devices=list(self._status["devices"]))

    def stop(self, timeout=None):
        with self.lock:
            self._status["running"] = False


def wait_until(pred, timeout=8.0, step=0.05, label="condition"):
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        last = pred()
        if last:
            return last
        time.sleep(step)
    raise TimeoutError(f"Timed out waiting for {label}; last={last}")


def _receiver_upload(port: int, token: str, filename: str, img_bytes: bytes, sidecar: dict):
    sidecar_b64 = base64.urlsafe_b64encode(
        json.dumps(sidecar, ensure_ascii=False).encode("utf-8")
    ).decode("ascii").rstrip("=")
    sha256_hex = hashlib.sha256(img_bytes).hexdigest()
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=15)
    try:
        conn.request(
            "POST",
            "/upload",
            body=img_bytes,
            headers={
                "X-Sotuken-Token": token,
                "X-File-Name": filename,
                "X-Sidecar-Json": sidecar_b64,
                "X-Image-Sha256": sha256_hex,
                "Content-Length": str(len(img_bytes)),
            },
        )
        resp = conn.getresponse()
        data = json.loads(resp.read().decode("utf-8"))
        return resp.status, data
    finally:
        conn.close()


def run_verification(screenshots_dir: Path | None = None) -> dict:
    browser_exe = Path(DEFAULT_CHROME)
    if not browser_exe.is_file():
        browser_exe = Path(DEFAULT_EDGE)
    if not browser_exe.is_file():
        raise FileNotFoundError("Chrome or Edge executable not found for headless verification.")
    if not (STATIC_DIR / "index.html").is_file():
        raise FileNotFoundError(f"Built static assets missing at {STATIC_DIR}")

    with tempfile.TemporaryDirectory(prefix="sotuken-react-e2e-", ignore_cleanup_errors=True) as tmp_str:
        root = Path(tmp_str)
        db_path = root / "manager.db"
        incoming = root / "incoming"
        images = root / "images"
        overlays = root / "overlays"
        profile_dir = root / "chrome-profile"
        for d in (incoming, images, overlays, profile_dir):
            d.mkdir()

        orig_a = images / "orig_a.png"
        ov_a = overlays / "ov_a.png"
        orig_a.write_bytes(FIXTURE_PNG.read_bytes())
        ov_a.write_bytes(FIXTURE_PNG.read_bytes())

        # 1. Fixed dataset covering Section 6.1 cases
        Storage(str(db_path))
        conn = sqlite3.connect(db_path)
        try:
            with conn:
                rows_seed = [
                    # Older reading for メーターA (-02:00 -> UTC 2026-11-12 01:30)
                    ("2026-11-11T23:30:00-02:00", "メーターA", 18.2, "ok", "done", str(orig_a), str(ov_a),
                     "2026-11-11T23:30:00-02:00", "2026-11-12T01:30:05+00:00", 0.94, None, "I-AM", "午前巡回", "R-1", "D-01", "rid-1"),
                    # Newer reading for メーターA (+09:00 -> UTC 2026-11-12 02:00)
                    ("2026-11-12T11:00:00+09:00", "メーターA", 19.6, "ok", "done", str(orig_a), str(ov_a),
                     "2026-11-12T11:00:00+09:00", "2026-11-12T11:00:05+09:00", 0.97, None, "I-AM", "午前巡回", "R-1", "D-01", "rid-2"),
                    # low_confidence without overlay
                    ("2026-11-12T11:05:00+09:00", "メーターB", 47.0, "low_confidence", "done", str(orig_a), None,
                     "2026-11-12T11:05:00+09:00", "2026-11-12T11:05:05+09:00", 0.55, None, "I-AM", "午前巡回", "R-1", "D-02", "rid-3"),
                    # failed with missing original image file
                    ("2026-11-12T11:10:00+09:00", "メーターC", None, "failed", "failed", str(images / "missing.png"), None,
                     "2026-11-12T11:10:00+09:00", "2026-11-12T11:10:04+09:00", 0.12, "ocr", "I-AM", "午前巡回", "R-1", "D-03", "rid-4"),
                    # unnamed device without inspection_id
                    ("2026-11-12T11:12:00+09:00", "", 30.1, "ok", "done", str(orig_a), None,
                     "2026-11-12T11:12:00+09:00", "2026-11-12T11:12:03+09:00", 0.88, None, None, None, None, None, "rid-5"),
                ]
                conn.executemany(
                    "INSERT INTO meter_readings "
                    "(timestamp, device_name, value, status, stage, image_path, overlay_path, "
                    "captured_at, received_at, confidence, failure_stage, inspection_id, inspection_name, route_id, device_id, reading_id) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    rows_seed,
                )
        finally:
            conn.close()

        # Baseline from Streamlit/Python export helpers
        py_history = MeterManager(str(db_path)).get_history(include_raw=False)
        py_latest = latest_per_device(py_history)
        py_filtered_am = latest_per_device(filter_readings(py_history, inspection_id="I-AM"))

        # 2. Start real ReceiverServer + Owner + standalone pc_api.server (Node-free!)
        rx_port = _free_port()
        rx_server = ReceiverServer(
            ("127.0.0.1", rx_port),
            token="verify-phone-token",
            incoming_dir=str(incoming),
            quiet=True,
        )
        rx_thread = threading.Thread(target=rx_server.serve_forever, daemon=True)
        rx_thread.start()

        rx_info = {
            "running": True,
            "server": rx_server,
            "thread": rx_thread,
            "url": f"http://127.0.0.1:{rx_port}",
            "token": "verify-phone-token",
            "external_process": False,
        }
        fake_usb = FakeUsbService()
        api_port = _free_port()
        cdp_port = _free_port()

        import pc_api.owner as owner_mod

        orig_init_rx = owner_mod.init_receiver_for_app
        owner_mod.init_receiver_for_app = lambda **kw: rx_info
        owner = Owner(db_path=db_path, incoming=incoming, usb=False, port=0)
        api_proc = None
        chrome_proc = None
        cdp = None

        try:
            owner.start()
            owner.usb = fake_usb

            with tempfile.TemporaryDirectory(prefix="sotuken-key-") as key_dir:
                key_file = _write_private_key_file(Path(key_dir), owner.internal_key)
                env = os.environ.copy()
                existing_pp = env.get("PYTHONPATH", "")
                env["PYTHONPATH"] = f"{REPO_ROOT}{os.pathsep}{existing_pp}" if existing_pp else str(REPO_ROOT)
                api_proc = subprocess.Popen(
                    [
                        sys.executable,
                        "-m",
                        "pc_api.server",
                        "--db",
                        str(db_path),
                        "--incoming-dir",
                        str(incoming),
                        "--images-dir",
                        str(images),
                        "--overlays-dir",
                        str(overlays),
                        "--static-dir",
                        str(STATIC_DIR),
                        "--port",
                        str(api_port),
                        "--owner-port",
                        str(owner.port),
                        "--internal-key-file",
                        str(key_file),
                    ],
                    cwd=str(root),
                    env=env,
                )
                _wait_tcp(api_port, api_proc)

            chrome_proc = subprocess.Popen(
                [
                    str(browser_exe),
                    "--headless=new",
                    f"--remote-debugging-port={cdp_port}",
                    f"--user-data-dir={profile_dir}",
                    "--no-sandbox",
                    "--disable-gpu",
                    f"http://127.0.0.1:{api_port}/",
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )

            wait_until(
                lambda: _try_json(f"http://127.0.0.1:{cdp_port}/json"),
                timeout=10.0,
                label="CDP json",
            )
            pages = _try_json(f"http://127.0.0.1:{cdp_port}/json")
            ws_url = next(p["webSocketDebuggerUrl"] for p in pages if p.get("type") == "page")
            cdp = CDPClient(ws_url)
            cdp.call("Page.enable")
            cdp.call("Runtime.enable")
            cdp.call("Log.enable")

            wait_until(
                lambda: cdp.eval("document.querySelectorAll('[data-reading-id]').length >= 4"),
                timeout=8.0,
                label="initial readings render",
            )

            # Check security boundaries: no token leak in storage/URL
            sec_check = cdp.eval(
                """(() => ({
                    localStorageLen: localStorage.length,
                    sessionStorageLen: sessionStorage.length,
                    hrefHasToken: location.href.includes(document.querySelector('meta[name="pc-token"]')?.content || 'X'),
                    latestIds: [...document.querySelectorAll('[data-reading-id]')].map(e => e.getAttribute('data-reading-id')),
                    historyIds: [...document.querySelectorAll('[data-history-id]')].map(e => e.getAttribute('data-history-id')),
                }))()"""
            )
            assert sec_check["localStorageLen"] == 0
            assert sec_check["sessionStorageLen"] == 0
            assert not sec_check["hrefHasToken"]
            assert sec_check["latestIds"] == [str(r["id"]) for r in py_latest], (
                f"Mismatch latestIds {sec_check['latestIds']} vs {[str(r['id']) for r in py_latest]}"
            )
            assert sec_check["historyIds"] == [str(r.id) for r in py_history]

            if screenshots_dir:
                screenshots_dir.mkdir(parents=True, exist_ok=True)
                cdp.screenshot(screenshots_dir / "react-records-1366.png")

            # Filter parity check (select I-AM)
            cdp.eval(
                """(() => {
                    const sel = document.querySelector('select[aria-label="点検"]');
                    const setter = Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, 'value').set;
                    setter.call(sel, 'I-AM');
                    sel.dispatchEvent(new Event('change', { bubbles: true }));
                })()"""
            )
            wait_until(
                lambda: cdp.eval("document.querySelectorAll('[data-history-id]').length") == 4,
                timeout=5.0,
                label="filtered I-AM",
            )
            filtered_ids = cdp.eval(
                "[...document.querySelectorAll('[data-reading-id]')].map(e => e.getAttribute('data-reading-id'))"
            )
            assert filtered_ids == [str(r["id"]) for r in py_filtered_am]

            # Reset filter
            cdp.eval(
                """(() => {
                    const btn = [...document.querySelectorAll('button')].find(b => b.textContent.includes('絞り込みを解除'));
                    btn && btn.click();
                })()"""
            )
            wait_until(
                lambda: cdp.eval("document.querySelectorAll('[data-history-id]').length") == 5,
                timeout=5.0,
                label="filter reset",
            )

            # Image modal check (original + overlay Blob URLs)
            cdp.eval("document.querySelector('[data-reading-id=\"2\"]')?.click()")
            wait_until(
                lambda: cdp.eval(
                    """(() => {
                        const imgs = [...document.querySelectorAll('[data-preview-reading-id="2"] img')];
                        return imgs.length === 2 && imgs.every(i => i.complete && i.naturalWidth > 0 && i.src.startsWith('blob:'));
                    })()"""
                ),
                timeout=5.0,
                label="original & overlay Blob load",
            )
            if screenshots_dir:
                cdp.screenshot(screenshots_dir / "react-overlay-1366.png", full=False)
            cdp.eval(
                "[...document.querySelectorAll('button')].find(b => b.textContent.includes('閉じる'))?.click()"
            )

            # Missing original image fallback check (id=4)
            cdp.eval("document.querySelector('[data-reading-id=\"4\"]')?.click()")
            wait_until(
                lambda: cdp.eval("document.body.innerText.includes('元の写真が見つかりません。')"),
                timeout=5.0,
                label="missing image fallback",
            )
            cdp.eval(
                "[...document.querySelectorAll('button')].find(b => b.textContent.includes('閉じる'))?.click()"
            )

            # 3. 10 Roundtrips Navigation + Pairing QR + 10 USB disconnect/reconnect cycles
            cdp.eval(
                "[...document.querySelectorAll('nav button')].find(b => b.textContent.includes('接続・設定'))?.click()"
            )
            wait_until(
                lambda: cdp.eval("document.querySelector('[data-testid=\"owner-instance-id\"]')?.textContent") == owner.instance_id,
                timeout=5.0,
                label="settings view owner id",
            )
            cdp.eval(
                "[...document.querySelectorAll('button')].find(b => b.textContent.includes('スマホを登録'))?.click()"
            )
            wait_until(
                lambda: cdp.eval("Boolean(document.querySelector('[data-testid=\"pairing-qr-box\"] svg'))"),
                timeout=5.0,
                label="pairing QR visible",
            )
            if screenshots_dir:
                cdp.screenshot(screenshots_dir / "react-settings-1366.png")

            for i in range(10):
                cdp.eval(
                    "[...document.querySelectorAll('nav button')].find(b => b.textContent.includes('機器の記録'))?.click()"
                )
                wait_until(
                    lambda: cdp.eval("Boolean(document.querySelector('#heading-latest'))"),
                    timeout=3.0,
                    label=f"roundtrip {i} records",
                )
                cdp.eval(
                    "[...document.querySelectorAll('nav button')].find(b => b.textContent.includes('接続・設定'))?.click()"
                )
                wait_until(
                    lambda: cdp.eval("Boolean(document.querySelector('[data-testid=\"pairing-qr-box\"] svg'))"),
                    timeout=3.0,
                    label=f"roundtrip {i} settings",
                )
                oid = cdp.eval("document.querySelector('[data-testid=\"owner-instance-id\"]')?.textContent")
                assert oid == owner.instance_id

            # USB 10 disconnect/reconnect cycles
            for cycle in range(1, 11):
                fake_usb.set_state(devices=[], last_error=f"adb disconnected cycle {cycle}")
                wait_until(
                    lambda c=cycle: f"cycle {c}" in (cdp.eval("document.querySelector('[data-testid=\"usb-last-error\"]')?.textContent || ''") or ""),
                    timeout=5.0,
                    label=f"usb disconnect {cycle}",
                )
                fake_usb.set_state(devices=["emulator-5554"], last_error=None, pulled_total=cycle, cycles=cycle + 1)
                wait_until(
                    lambda c=cycle: cdp.eval("document.querySelector('[data-testid=\"usb-pulled-total\"]')?.textContent") == f"{c}組",
                    timeout=5.0,
                    label=f"usb reconnect {cycle}",
                )

            # Pairing cancel + server expiry hide test
            cdp.eval(
                "[...document.querySelectorAll('button')].find(b => b.textContent.includes('登録を中止'))?.click()"
            )
            wait_until(
                lambda: cdp.eval("Boolean(document.querySelector('[data-testid=\"pairing-inactive\"]'))"),
                timeout=5.0,
                label="pairing cancel hides QR",
            )

            cdp.eval(
                "[...document.querySelectorAll('button')].find(b => b.textContent.includes('スマホを登録'))?.click()"
            )
            wait_until(
                lambda: cdp.eval("Boolean(document.querySelector('[data-testid=\"pairing-qr-box\"] svg'))"),
                timeout=5.0,
                label="pairing recreate",
            )
            rx_server.cancel_pairing()
            wait_until(
                lambda: cdp.eval("Boolean(document.querySelector('[data-testid=\"pairing-inactive\"]'))"),
                timeout=5.0,
                label="pairing expiry hides QR",
            )

            # 4. Return to Records, enable auto-refresh (5s), measure DB commit -> render across 3 phases
            cdp.eval(
                "[...document.querySelectorAll('nav button')].find(b => b.textContent.includes('機器の記録'))?.click()"
            )
            wait_until(
                lambda: cdp.eval("Boolean(document.querySelector('input[type=\"checkbox\"]'))"),
                timeout=3.0,
                label="records checkbox",
            )
            cdp.eval("document.querySelector('input[type=\"checkbox\"]').click()")

            phase_latencies = []
            for phase_idx, wait_offset in enumerate((0.2, 2.5, 4.5), start=1):
                cdp.eval(
                    "[...document.querySelectorAll('button')].find(b => b.textContent.trim() === '更新')?.click()"
                )
                time.sleep(wait_offset)

                dev_name = f"フェーズ計測-{phase_idx}"
                c2 = sqlite3.connect(db_path)
                try:
                    with c2:
                        cur = c2.execute(
                            "INSERT INTO meter_readings "
                            "(timestamp, device_name, value, status, stage, image_path, overlay_path, captured_at, received_at) "
                            "VALUES (?, ?, ?, 'ok', 'done', ?, ?, ?, ?)",
                            (
                                f"2026-11-13T11:00:0{phase_idx}+09:00",
                                dev_name,
                                50.0 + phase_idx,
                                str(orig_a),
                                str(ov_a),
                                f"2026-11-13T11:00:0{phase_idx}+09:00",
                                f"2026-11-13T11:00:0{phase_idx}+09:00",
                            ),
                        )
                        new_id = str(cur.lastrowid)
                    t_commit = time.perf_counter()
                finally:
                    c2.close()

                wait_until(
                    lambda nid=new_id: cdp.eval(f"Boolean(document.querySelector('[data-reading-id=\"{nid}\"]'))"),
                    timeout=7.0,
                    step=0.02,
                    label=f"phase {phase_idx} dom render",
                )
                t_dom = time.perf_counter()
                cdp.eval(f"document.querySelector('[data-reading-id=\"{new_id}\"]')?.click()")
                wait_until(
                    lambda nid=new_id: cdp.eval(
                        f"Boolean(document.querySelector('[data-preview-reading-id=\"{nid}\"] img[data-image-loaded]:not([data-image-loaded=\"\"])'))"
                    ),
                    timeout=5.0,
                    step=0.02,
                    label=f"phase {phase_idx} image load",
                )
                t_img = time.perf_counter()
                cdp.eval(
                    "[...document.querySelectorAll('button')].find(b => b.textContent.includes('閉じる'))?.click()"
                )
                phase_latencies.append(
                    {
                        "phase": phase_idx,
                        "offset_s": wait_offset,
                        "commit_to_dom_s": round(t_dom - t_commit, 3),
                        "commit_to_image_s": round(t_img - t_commit, 3),
                    }
                )

            # 5. Real HTTP /upload -> real call_pipeline -> ingest_result -> DB -> React DOM + Blob image
            t0 = time.perf_counter()
            sidecar_payload = {
                "local_id": "rx01",
                "device_name": "実受信計測メーター",
                "captured_at": "2026-11-13T11:15:00+09:00",
                "inspection_id": "I-RX",
                "inspection_name": "受信計測",
            }
            status_code, rx_body = _receiver_upload(
                rx_port,
                "verify-phone-token",
                "20261113T111500_rx01.png",
                FIXTURE_PNG.read_bytes(),
                sidecar_payload,
            )
            assert status_code in (200, 201), (status_code, rx_body)
            t_http_ok = time.perf_counter()

            saved_img = incoming / rx_body["stored"]
            saved_sidecar = saved_img.with_suffix(".json")
            sidecar_obj = load_sidecar(str(saved_sidecar))
            pipeline_res = execute_pipeline(str(saved_img), use_vlm=False)
            storage = Storage(str(db_path))
            orig_cwd = os.getcwd()
            os.chdir(root)
            try:
                row_id = ingest_result(
                    storage,
                    str(saved_img),
                    sidecar_obj,
                    pipeline_res,
                    str(images),
                    str(overlays),
                )
            finally:
                os.chdir(orig_cwd)
            t_db = time.perf_counter()
            assert row_id is not None

            new_rx_id = str(row_id)
            wait_until(
                lambda: cdp.eval(f"Boolean(document.querySelector('[data-reading-id=\"{new_rx_id}\"]'))"),
                timeout=7.0,
                step=0.02,
                label="real receive dom render",
            )
            t_rx_dom = time.perf_counter()
            cdp.eval(f"document.querySelector('[data-reading-id=\"{new_rx_id}\"]')?.click()")
            expected_imgs = 2 if pipeline_res.get("status") != "failed" else 1
            wait_until(
                lambda: cdp.eval(
                    f"""(() => {{
                        const imgs = [...document.querySelectorAll('[data-preview-reading-id="{new_rx_id}"] img[data-image-loaded]:not([data-image-loaded=""])')];
                        return imgs.length >= {expected_imgs} && imgs.every(i => i.complete && i.naturalWidth > 0 && i.src.startsWith('blob:'));
                    }})()"""
                ),
                timeout=5.0,
                step=0.02,
                label="real receive image load",
            )
            t_rx_img = time.perf_counter()

            errors = []
            for ev in cdp.events:
                m = ev.get("method")
                if m == "Runtime.exceptionThrown":
                    errors.append(ev)
                elif m == "Log.entryAdded":
                    entry = ev.get("params", {}).get("entry", {})
                    if entry.get("level") == "error":
                        url = entry.get("url", "")
                        # id=4 is an intentional missing-original-image test case expecting 404.
                        if "/api/v1/images/4-o-" in url and "404" in entry.get("text", ""):
                            continue
                        errors.append(entry)

            assert not errors, f"Browser/CSP errors detected: {errors}"

            return {
                "parity_latest_count": len(py_latest),
                "parity_history_count": len(py_history),
                "roundtrips_completed": 10,
                "usb_cycles_completed": 10,
                "csp_and_console_errors": len(errors),
                "phase_latencies": phase_latencies,
                "max_commit_to_image_s": max(p["commit_to_image_s"] for p in phase_latencies),
                "receive_to_render": {
                    "http_upload_s": round(t_http_ok - t0, 3),
                    "pipeline_and_db_s": round(t_db - t_http_ok, 3),
                    "db_to_dom_s": round(t_rx_dom - t_db, 3),
                    "db_to_image_s": round(t_rx_img - t_db, 3),
                    "total_http_to_image_s": round(t_rx_img - t0, 3),
                    "pipeline_status": pipeline_res.get("status"),
                    "pipeline_value": pipeline_res.get("value"),
                    "images_loaded": expected_imgs,
                },
            }
        finally:
            owner_mod.init_receiver_for_app = orig_init_rx
            if cdp is not None:
                try:
                    cdp.close()
                except Exception:
                    pass
            if chrome_proc is not None:
                chrome_proc.terminate()
                try:
                    chrome_proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    chrome_proc.kill()
            if api_proc is not None and api_proc.poll() is None:
                api_proc.terminate()
                try:
                    api_proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    api_proc.kill()
            owner.stop()


def _try_json(url: str):
    try:
        with urllib.request.urlopen(url, timeout=1) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception:
        return None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--screenshots-dir", type=Path, default=None)
    args = parser.parse_args()
    result = run_verification(screenshots_dir=args.screenshots_dir)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
