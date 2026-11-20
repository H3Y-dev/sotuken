"""Verify bundled React inspection CSV export with a temporary DB and headless Chrome/Edge."""

from contextlib import closing
import csv
import json
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory
from unittest.mock import patch
from urllib.parse import urlsplit

from verify_react_migration import (
    CDPClient, DEFAULT_CHROME, DEFAULT_EDGE, STATIC_DIR, _try_json, wait_until,
)

from manager.storage import Storage
from pc_api.server import PCAPI


def verify_browser(cdp, origin, launch_key, downloads, saved_dir):
    def expect_response(method, path):
        def response_status():
            cdp.eval("0")  # Drain events queued since the last CDP command.
            request_ids = {
                event["params"]["requestId"] for event in cdp.events
                if event.get("method") == "Network.requestWillBeSent"
                and event["params"]["request"]["method"] == method
                and urlsplit(event["params"]["request"]["url"]).path == path
            }
            for event in cdp.events:
                if (event.get("method") == "Network.responseReceived"
                        and event["params"]["requestId"] in request_ids):
                    return event["params"]["response"]["status"]
            return None

        status = wait_until(response_status, label=f"{method} {path} response")
        assert status == 200, f"{method} {path}: HTTP {status}"

    def click_button(label):
        clicked = cdp.eval(f"""(() => {{
            const button = [...document.querySelectorAll('button')].find(
                b => b.textContent.trim() === {json.dumps(label)} && !b.disabled
            );
            if (!button) return false;
            button.click();
            return true;
        }})()""")
        assert clicked, f"Enabled button not found: {label}"

    cdp.call("Network.enable")
    cdp.call("Page.enable")
    cdp.call("Page.setDownloadBehavior", {"behavior": "allow", "downloadPath": str(downloads)})
    cdp.call("Page.navigate", {"url": f"{origin}/#k={launch_key}"})
    expect_response("POST", "/api/v1/session")
    wait_until(lambda: cdp.eval("""[...document.querySelectorAll('nav button')]
        .some(b => b.textContent.trim() === '点検確認') && !location.hash"""),
        label="React session and cleared launch fragment")

    click_button("点検確認")
    expect_response("GET", "/api/v1/inspections")
    wait_until(lambda: cdp.eval("""document.querySelector('h1')?.textContent === '点検の一覧' &&
        document.querySelector('a[href="#/gauge/CSV-1"]')?.textContent.includes('CSV検証点検')"""),
        label="seeded inspection in React list")
    cdp.eval("""document.querySelector('a[href="#/gauge/CSV-1"]').click()""")
    expect_response("GET", "/api/v1/inspections/CSV-1/progress")
    wait_until(lambda: cdp.eval("document.querySelector('h1')?.textContent === 'CSV検証点検'"),
               label="seeded inspection detail")

    measurements = wait_until(lambda: cdp.eval("""(() => {
        const needles = [...document.querySelectorAll('.g-needle')];
        const segments = [...document.querySelectorAll('.g-seg')];
        if (!needles.length || !segments.length) return null;
        return {
            needles: needles.map(needle => {
                const svg = needle.ownerSVGElement;
                const center = new DOMPoint(60, 60);
                const pivot = center.matrixTransform(needle.getScreenCTM());
                const target = center.matrixTransform(svg.getScreenCTM());
                return {origin: getComputedStyle(needle).transformOrigin,
                        error_px: Math.hypot(pivot.x - target.x, pivot.y - target.y)};
            }),
            heights_px: segments.map(segment => segment.getBoundingClientRect().height),
        };
    })()"""), label="rendered gauges and progress")
    for needle in measurements["needles"]:
        assert needle["origin"] == "60px 60px", needle
        assert needle["error_px"] < 0.1, needle
    assert all(height > 0 for height in measurements["heights_px"]), measurements

    click_button("CSVをダウンロード")
    expect_response("POST", "/api/v1/inspections/CSV-1/csv")

    def completed_download():
        cdp.eval("0")
        started = {event["params"]["guid"]: event["params"]["suggestedFilename"]
                   for event in cdp.events if event.get("method") == "Page.downloadWillBegin"}
        for event in cdp.events:
            if event.get("method") == "Page.downloadProgress":
                params = event["params"]
                assert params["state"] != "canceled", "Browser canceled the CSV download"
                if params["state"] == "completed":
                    return started[params["guid"]]
        return None

    name = wait_until(completed_download, label="completed Chrome/Edge CSV download")
    downloaded, = downloads.iterdir()
    assert downloaded.name == name and downloaded.suffix == ".csv", downloaded.name

    click_button("CSVを保存")
    expect_response("POST", "/api/v1/inspections/CSV-1/csv/save")
    success = wait_until(lambda: cdp.eval("""[...document.querySelectorAll('[role="status"]')]
        .find(p => p.innerText.startsWith('保存しました: '))?.innerText"""),
        label="CSV save success message")
    saved, = saved_dir.iterdir()
    assert saved.suffix == ".csv" and success.startswith(f"保存しました: {saved.name}（"), success
    assert "メーター点検" in success, success

    expected = [
        ["メーター名称", "読み取り値", "状態", "取込時刻", "画像参照"],
        ["流量計", "3.5", "要確認", "2026-11-19T10:00:00", "flow.png"],
        ["圧力計", "12.5", "正常", "2026-11-19T09:00:00", "pressure.png"],
    ]
    contents = downloaded.read_bytes()
    assert contents == saved.read_bytes(), "Downloaded and saved CSV bytes differ"
    with downloaded.open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.reader(stream))
    assert rows == expected, f"Unexpected CSV rows: {rows!r}"
    return {
        "gauge_measurements": measurements,
        "http_200": 5,
        "csv_files": 2,
        "columns": len(rows[0]),
        "data_rows_per_file": len(rows) - 1,
        "download_name": downloaded.name,
        "saved_name": saved.name,
        "save_message": success,
    }


def run_verification():
    browser = next((Path(p) for p in (DEFAULT_CHROME, DEFAULT_EDGE) if Path(p).is_file()), None)
    if browser is None:
        raise FileNotFoundError("Chrome or Edge executable not found")
    if not (STATIC_DIR / "index.html").is_file():
        raise FileNotFoundError(f"Bundled React build missing at {STATIC_DIR}")

    with TemporaryDirectory(prefix="sotuken-react-csv-") as temp:
        root = Path(temp)
        db, incoming, downloads = root / "csv-test.db", root / "incoming", root / "downloads"
        documents, profile = root / "documents", root / "browser-profile"
        incoming.mkdir()
        downloads.mkdir()
        with Storage(str(db)).connection() as conn:
            conn.executemany("""INSERT INTO meter_readings
                (inspection_id, inspection_name, device_name, value, status, stage, timestamp, image_path)
                VALUES (?, ?, ?, ?, ?, 'done', ?, ?)""", [
                ("CSV-1", "CSV検証点検", "圧力計", 1.0, "ok", "2026-11-18T09:00:00", "old.png"),
                ("CSV-1", "CSV検証点検", "圧力計", 12.5, "ok", "2026-11-19T09:00:00", "pressure.png"),
                ("CSV-1", "CSV検証点検", "流量計", 3.5, "low_confidence", "2026-11-19T10:00:00", "flow.png"),
                ("CSV-2", "別の点検", "圧力計", 99.0, "ok", "2026-11-19T11:00:00", "other.png"),
            ])
            conn.execute("INSERT INTO devices (device_id, device_name, min_value, max_value) VALUES (?, ?, ?, ?)",
                         ("pressure", "圧力計", 0, 20))
            conn.execute("UPDATE meter_readings SET device_id = ? WHERE device_name = ?", ("pressure", "圧力計"))

        # The app also checks runtime and USB status. Never contact a running Owner.
        api = PCAPI(db, incoming_dir=incoming, image_dirs=[incoming], static_dir=STATIC_DIR,
                    owner_port=0, port=0)
        # Override the Known Folder resolver in the same process as the real /csv/save handler.
        with patch("manager.export._documents_dir", return_value=documents) as resolve_documents:
            api.start()
            try:
                result = run_browser(browser, api, profile, downloads, documents / "メーター点検")
                resolve_documents.assert_called_once_with()
                return {"browser": browser.name, **result}
            finally:
                api.stop()


def run_browser(browser, api, profile, downloads, saved_dir):
    with subprocess.Popen([
        str(browser), "--headless=new", "--no-first-run", "--remote-debugging-port=0",
        f"--user-data-dir={profile}", "about:blank",
    ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) as process:
        try:
            active_port = profile / "DevToolsActivePort"
            wait_until(active_port.is_file, timeout=10, label="Chrome/Edge DevToolsActivePort")
            port = active_port.read_text(encoding="utf-8").splitlines()[0]

            def page_socket():
                pages = _try_json(f"http://127.0.0.1:{port}/json") or []
                return next((p["webSocketDebuggerUrl"] for p in pages
                             if p.get("type") == "page" and p.get("url") == "about:blank"), None)

            with closing(CDPClient(wait_until(page_socket, label="blank CDP page"))) as cdp:
                return verify_browser(cdp, f"http://127.0.0.1:{api.port}",
                                      api.sessions.issue_launch_key(), downloads, saved_dir)
        finally:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)


if __name__ == "__main__":
    if not __debug__:
        raise SystemExit("Run without -O so verification assertions are enabled")
    print(json.dumps(run_verification(), indent=2))
