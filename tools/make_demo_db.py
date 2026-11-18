"""デモ用DBを作成し、受信・取り込み・照合までを実行するCLI/モジュール。

仕様: tasks/design/デモ用3Dメーターと機器カタログ.md
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
from pathlib import Path
import re
import secrets
import sqlite3
import stat
import subprocess
import sys
import tempfile
import threading
import time
from typing import Callable

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from manager.devices import list_devices
from manager.receiver import ReceiverServer
from manager.routes import save_route
from manager.storage import Storage
from tools.demo_catalog import APPEARANCE_KEYS, DEFAULT_CATALOG_PATH, load_catalog
from tools.demo_scenario import BROKEN_PNG_BYTES, ROUTES, build_inspections
from tools.demo_transport import send_manifest, upload_photo
from tools.sync_devices import sync_devices

REPO_ROOT = Path(__file__).resolve().parent.parent
RUN_NAME_RE = re.compile(r"^demo-[a-z0-9][a-z0-9-]{0,23}$")
REQUIRED_SHOTS = (1, 2, 3, 4)


def _reject_reparse_point(path: Path) -> None:
    if path.is_symlink():
        raise ValueError(f"シンボリックリンクは許可されていません: {path}")
    if path.exists():
        attrs = getattr(os.lstat(path), "st_file_attributes", 0)
        if attrs & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0):
            raise ValueError(f"ジャンクション・再解析ポイントは許可されていません: {path}")


def validate_run_name(run_name: str) -> str:
    if not isinstance(run_name, str) or not RUN_NAME_RE.fullmatch(run_name):
        raise ValueError(
            f"--run は demo-[a-z0-9][a-z0-9-]{{0,23}} の形式で指定してください: {run_name!r}"
        )
    return run_name


def validate_inputs(catalog: list[dict], truth: dict, photos_dir: Path) -> None:
    """台帳と groundtruth.json、および画像実ファイルの整合性を事前検証する。"""
    if truth.get("v") != 1 or not isinstance(truth.get("frames"), list):
        raise ValueError("groundtruth.json の形式が不正です")

    photos_root = photos_dir.resolve()
    devices_by_id = {d["device_id"]: d for d in catalog}
    frames = truth["frames"]
    expected_count = len(catalog) * len(REQUIRED_SHOTS)
    if len(frames) != expected_count:
        raise ValueError(
            f"groundtruth.json のフレーム数が一致しません: 期待 {expected_count}, 実際 {len(frames)}"
        )

    seen_keys: set[tuple[str, int]] = set()
    for frame in frames:
        if not isinstance(frame, dict):
            raise ValueError("groundtruth.json のフレーム要素がオブジェクトではありません")
        did = frame.get("device_id")
        shot = frame.get("shot")
        if did not in devices_by_id:
            raise ValueError(f"未知の機器IDです: {did!r}")
        if shot not in REQUIRED_SHOTS or (did, shot) in seen_keys:
            raise ValueError(f"shot が不正または重複しています: {did} shot={shot!r}")
        seen_keys.add((did, shot))

        dev = devices_by_id[did]
        for key in ("device_name", "unit", "min_value", "max_value"):
            if frame.get(key) != dev[key]:
                raise ValueError(
                    f"{did} shot {shot}: {key} が台帳と一致しません ({frame.get(key)!r} != {dev[key]!r})"
                )
        expected_app = {k: dev[k] for k in APPEARANCE_KEYS}
        if frame.get("appearance") != expected_app:
            raise ValueError(f"{did} shot {shot}: appearance が台帳と一致しません")

        rel = frame.get("file")
        if not isinstance(rel, str) or not rel:
            raise ValueError(f"{did} shot {shot}: file が不正です")
        img_path = (photos_root / rel).resolve()
        if not img_path.is_relative_to(photos_root):
            raise ValueError(f"{did} shot {shot}: パスが photos_dir 外を指しています: {rel!r}")
        _reject_reparse_point(img_path)
        if not img_path.is_file():
            raise ValueError(f"{did} shot {shot}: 画像ファイルが存在しません: {img_path}")

        actual_sha = hashlib.sha256(img_path.read_bytes()).hexdigest()
        if actual_sha != str(frame.get("sha256", "")).lower():
            raise ValueError(
                f"{did} shot {shot}: SHA-256 が一致しません ({actual_sha} != {frame.get('sha256')!r})"
            )


def seed_catalog_and_routes(db_path: Path, catalog: list[dict]) -> None:
    """台帳CSVをrun内DBへ同期し、デモ用ルート2本を登録する。"""
    csv_path = db_path.parent / "devices.csv"
    columns = [
        "device_id",
        "device_name",
        "kind",
        "unit",
        "min_value",
        "max_value",
        "provisional",
        "note",
    ]
    with csv_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=columns, lineterminator="\n")
        writer.writeheader()
        for dev in catalog:
            writer.writerow(
                {
                    "device_id": dev["device_id"],
                    "device_name": dev["device_name"],
                    "kind": dev["kind"],
                    "unit": dev["unit"],
                    "min_value": dev["min_value"],
                    "max_value": dev["max_value"],
                    "provisional": 0,
                    "note": "3Dデモ",
                }
            )

    sync_res = sync_devices(csv_path, db_path, apply=True)
    if sync_res.get("errors") or not sync_res.get("applied"):
        raise RuntimeError(f"台帳同期に失敗しました: {sync_res.get('errors')}")

    storage = Storage(str(db_path))
    registered = list_devices(storage)
    if len(registered) != len(catalog):
        raise RuntimeError(f"登録機器数が一致しません: 期待 {len(catalog)}, 実際 {len(registered)}")

    devices_by_id = {d["device_id"]: d for d in catalog}
    for route_id, _suffix, route_name, device_ids in ROUTES:
        route_devices = [
            {"id": did, "name": devices_by_id[did]["device_name"]}
            for did in sorted(device_ids)
            if did in devices_by_id
        ]
        if route_devices:
            save_route(storage, route_name, route_devices, route_id=route_id)


def _open_ro_db(db_path: Path) -> sqlite3.Connection:
    return sqlite3.connect(f"{db_path.resolve().as_uri()}?mode=ro", uri=True)


def verify_db(
    db_path: Path,
    expected: dict[str, dict],
    catalog: list[dict],
    expected_inspections: int,
    *,
    check_full_scenario: bool = False,
) -> dict:
    """取り込み完了後のDBを計画・台帳と照合し、集計を返す。"""
    conn = _open_ro_db(db_path)
    try:
        db_devices = conn.execute(
            "SELECT device_id, device_name, kind, unit, min_value, max_value FROM devices"
        ).fetchall()
        catalog_by_id = {d["device_id"]: d for d in catalog}
        if len(db_devices) != len(catalog):
            raise RuntimeError(f"DB機器数が一致しません: 期待 {len(catalog)}, 実際 {len(db_devices)}")
        for did, dname, kind, unit, vmin, vmax in db_devices:
            dev = catalog_by_id.get(did)
            if dev is None:
                raise RuntimeError(f"DBに未知の機器IDがあります: {did}")
            if (dname, kind, unit, vmin, vmax) != (
                dev["device_name"],
                dev["kind"],
                dev["unit"],
                dev["min_value"],
                dev["max_value"],
            ):
                raise RuntimeError(f"機器メタデータが台帳と一致しません: {did}")

        routes_count = conn.execute("SELECT COUNT(*) FROM inspection_routes").fetchone()[0]
        inspections_count = conn.execute("SELECT COUNT(*) FROM inspections").fetchone()[0]
        if inspections_count != expected_inspections:
            raise RuntimeError(
                f"点検数が一致しません: 期待 {expected_inspections}, 実際 {inspections_count}"
            )

        rows = conn.execute(
            "SELECT image_sha256, inspection_id, route_id, device_id, device_id_source, "
            "stage, status, failure_stage, failure_code, value FROM meter_readings"
        ).fetchall()
    finally:
        conn.close()

    by_key: dict[tuple[str, str], list[tuple]] = {}
    for row in rows:
        sha = (row[0] or "").lower()
        insp_id = row[1] or ""
        if sha not in expected:
            raise RuntimeError(f"期待外の画像SHA-256がDBにあります: {sha!r}")
        by_key.setdefault((sha, insp_id), []).append(row)

    if len(rows) != len(expected):
        raise RuntimeError(f"読み取り行数が一致しません: 期待 {len(expected)}, 実際 {len(rows)}")

    route_ok_counts: dict[str, int] = {}
    expected_routes = {exp["route_id"] for exp in expected.values()}
    ocr_ok = 0
    ocr_failed = 0

    for sha, exp in expected.items():
        key = (sha, exp["inspection_id"])
        matched = by_key.get(key, [])
        if len(matched) != 1:
            raise RuntimeError(
                f"{exp['file_name']} ({exp['inspection_id']}) のDB行数が1ではありません: {len(matched)}"
            )
        (
            _sha,
            insp_id,
            route_id,
            device_id,
            device_id_source,
            stage,
            status,
            failure_stage,
            failure_code,
            value,
        ) = matched[0]
        if route_id != exp["route_id"]:
            raise RuntimeError(f"{exp['file_name']}: route_id 不一致 ({route_id!r} != {exp['route_id']!r})")
        if device_id != exp["device_id"]:
            raise RuntimeError(f"{exp['file_name']}: device_id 不一致 ({device_id!r} != {exp['device_id']!r})")
        if device_id_source != exp["device_id_source"]:
            raise RuntimeError(
                f"{exp['file_name']}: device_id_source 不一致 ({device_id_source!r} != {exp['device_id_source']!r})"
            )

        if exp["broken"]:
            if (
                stage != "image_unreadable"
                or status != "failed"
                or failure_stage != "unknown"
                or failure_code != "unknown_failure"
                or value is not None
            ):
                raise RuntimeError(
                    f"破損画像 {exp['file_name']} の失敗行が期待と異なります: "
                    f"stage={stage!r}, status={status!r}, failure_stage={failure_stage!r}, "
                    f"failure_code={failure_code!r}, value={value!r}"
                )
            ocr_failed += 1
        else:
            if stage == "ok" and value is not None and math.isfinite(value):
                ocr_ok += 1
                route_ok_counts[route_id] = route_ok_counts.get(route_id, 0) + 1
            else:
                ocr_failed += 1

    for r_id in expected_routes:
        if route_ok_counts.get(r_id, 0) < 1:
            raise RuntimeError(f"ルート {r_id} で stage='ok' かつ有限値の行が1件もありません")

    if check_full_scenario:
        conn = _open_ro_db(db_path)
        try:
            a_rows = conn.execute(
                "SELECT device_id, COUNT(*) FROM meter_readings "
                "WHERE inspection_id='DMO-20261118-A' GROUP BY device_id"
            ).fetchall()
        finally:
            conn.close()
        counts_a = {did: cnt for did, cnt in a_rows}
        if counts_a.get("DMO-010", 0) != 0:
            raise RuntimeError(f"11/18 A の DMO-010 が未撮影ではありません: {counts_a.get('DMO-010')}")
        if counts_a.get("DMO-011", 0) != 1:
            raise RuntimeError(f"11/18 A の DMO-011 (追加) が1件ではありません: {counts_a.get('DMO-011', 0)}")
        if counts_a.get("DMO-001", 0) != 2:
            raise RuntimeError(f"11/18 A の DMO-001 (撮り直し) が2件ではありません: {counts_a.get('DMO-001', 0)}")

    return {
        "devices": len(db_devices),
        "routes": routes_count,
        "inspections": inspections_count,
        "unique_photos": len(expected),
        "ocr_ok": ocr_ok,
        "ocr_failed": ocr_failed,
    }


def wait_for_ingest(
    db_path: Path,
    expected: dict[str, dict],
    watcher: subprocess.Popen,
    timeout_s: int = 1200,
) -> dict:
    """ウォッチャーによる全期待画像のDB取り込み完了を1秒間隔で待機する。"""
    deadline = time.monotonic() + timeout_s
    log_path = db_path.parent / "watcher.log"

    while True:
        rc = watcher.poll()
        if rc is not None:
            raise RuntimeError(f"watch_inbox が途中終了しました (code={rc}, log={log_path})")

        seen_shas: set[str] = set()
        if db_path.exists():
            try:
                conn = _open_ro_db(db_path)
                try:
                    rows = conn.execute(
                        "SELECT DISTINCT LOWER(image_sha256) FROM meter_readings "
                        "WHERE image_sha256 IS NOT NULL"
                    ).fetchall()
                    seen_shas = {r[0] for r in rows}
                finally:
                    conn.close()
            except sqlite3.OperationalError:
                pass

        missing_shas = [sha for sha in expected if sha not in seen_shas]
        if not missing_shas:
            return {"processed": len(expected), "missing": []}

        remaining = deadline - time.monotonic()
        if remaining <= 0:
            missing_files = [expected[s]["file_name"] for s in missing_shas]
            raise TimeoutError(
                f"取り込みがタイムアウトしました ({timeout_s}秒): 未処理={missing_files}, log={log_path}"
            )
        time.sleep(min(1.0, remaining))


def _build_expected_map(inspections: list[dict], truth: dict) -> dict[str, dict]:
    frames_by_sha = {str(f["sha256"]).lower(): f for f in truth["frames"]}
    broken_sha = hashlib.sha256(BROKEN_PNG_BYTES).hexdigest()
    expected: dict[str, dict] = {}
    for insp in inspections:
        for upload in insp["uploads"]:
            sha = str(upload["sha256"]).lower()
            if sha in expected:
                continue
            sidecar = upload["sidecar"]
            is_broken = sha == broken_sha
            device_id = sidecar.get("device_id") or frames_by_sha[sha]["device_id"]
            device_id_source = "sidecar" if "device_id" in sidecar else "pc_qr"
            expected[sha] = {
                "file_name": upload["file_name"],
                "inspection_id": sidecar["inspection_id"],
                "route_id": sidecar["route_id"],
                "device_id": device_id,
                "device_id_source": device_id_source,
                "broken": is_broken,
            }
    return expected


def _write_result_atomic(result_path: Path, data: dict) -> None:
    fd, tmp_name = tempfile.mkstemp(dir=result_path.parent, prefix=".result-", suffix=".tmp")
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, result_path)
    finally:
        if tmp_path.exists():
            tmp_path.unlink(missing_ok=True)


def run_demo_db(
    run_name: str,
    *,
    repo_root: Path = REPO_ROOT,
    catalog_path: Path | None = None,
    photos_dir: Path | None = None,
    inspections_builder: Callable[[list[dict], dict, Path], list[dict]] | None = None,
    watcher_cmd_builder: Callable[[Path, Path, Path, Path], list[str]] | None = None,
    timeout_s: int | None = None,
) -> dict:
    """指定された run 名で隔離されたデモDBを作成し、取り込み・照合を実行する。"""
    t0 = time.monotonic()
    validate_run_name(run_name)

    root = Path(repo_root).resolve()
    demo_dir = root / "demo"
    runs_dir = demo_dir / "runs"
    _reject_reparse_point(demo_dir)
    _reject_reparse_point(runs_dir)

    run_dir = runs_dir / run_name
    if run_dir.exists() or run_dir.is_symlink():
        raise FileExistsError(f"run ディレクトリが既に存在します: {run_dir}")

    cat_path = catalog_path if catalog_path is not None else DEFAULT_CATALOG_PATH
    ph_dir = photos_dir if photos_dir is not None else (demo_dir / "photos")
    _reject_reparse_point(ph_dir)
    truth_path = ph_dir / "groundtruth.json"
    if not truth_path.is_file():
        raise FileNotFoundError(f"groundtruth.json が見つかりません: {truth_path}")

    catalog = load_catalog(cat_path)
    truth = json.loads(truth_path.read_text(encoding="utf-8"))
    validate_inputs(catalog, truth, ph_dir)

    builder = inspections_builder or (lambda cat, tr, pdir: build_inspections(cat, tr, photos_dir=pdir))
    inspections = builder(catalog, truth, ph_dir)
    expected = _build_expected_map(inspections, truth)

    runs_dir.mkdir(parents=True, exist_ok=True)
    run_dir.mkdir(exist_ok=False)
    incoming_dir = run_dir / "incoming"
    images_dir = run_dir / "images"
    overlays_dir = run_dir / "overlays"
    incoming_dir.mkdir()
    images_dir.mkdir()
    overlays_dir.mkdir()
    db_path = run_dir / "manager.db"
    log_path = run_dir / "watcher.log"

    seed_catalog_and_routes(db_path, catalog)

    token = secrets.token_urlsafe(32)
    server: ReceiverServer | None = None
    thread: threading.Thread | None = None
    watcher: subprocess.Popen | None = None
    uploads_count = 0
    duplicates_count = 0

    try:
        server = ReceiverServer(
            ("127.0.0.1", 0),
            token,
            str(incoming_dir),
            quiet=True,
            db_path=str(db_path),
        )
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        host, port = server.server_address
        base_url = f"http://{host}:{port}"

        for insp in inspections:
            for upload in insp["uploads"]:
                res = upload_photo(base_url, token, upload)
                uploads_count += 1
                if res.get("duplicate") is True:
                    duplicates_count += 1
            send_manifest(base_url, token, insp["manifest"])

        server.shutdown()
        thread.join(timeout=5)
        server.server_close()
        server = None
        thread = None

        cmd = (
            watcher_cmd_builder(incoming_dir, db_path, images_dir, overlays_dir)
            if watcher_cmd_builder is not None
            else [
                sys.executable,
                "-m",
                "manager.watch_inbox",
                "--watch-dir",
                str(incoming_dir),
                "--db",
                str(db_path),
                "--images-dir",
                str(images_dir),
                "--overlays-dir",
                str(overlays_dir),
            ]
        )
        effective_timeout = timeout_s if timeout_s is not None else max(60, 45 * len(expected))
        with log_path.open("a", encoding="utf-8", errors="replace") as log_file:
            watcher = subprocess.Popen(
                cmd,
                cwd=str(root),
                stdout=log_file,
                stderr=subprocess.STDOUT,
            )
            wait_for_ingest(db_path, expected, watcher, timeout_s=effective_timeout)

        summary = verify_db(
            db_path,
            expected,
            catalog,
            len(inspections),
            check_full_scenario=(inspections_builder is None and len(catalog) == 20),
        )
    finally:
        if watcher is not None and watcher.poll() is None:
            watcher.terminate()
            try:
                watcher.wait(timeout=10)
            except subprocess.TimeoutExpired:
                watcher.kill()
                watcher.wait(timeout=5)
        if server is not None:
            server.shutdown()
            if thread is not None:
                thread.join(timeout=5)
            server.server_close()

    elapsed = round(time.monotonic() - t0, 2)
    result = {
        "v": 1,
        "uploads": uploads_count,
        "unique_photos": summary["unique_photos"],
        "duplicates": duplicates_count,
        "devices": summary["devices"],
        "routes": summary["routes"],
        "inspections": summary["inspections"],
        "ocr_ok": summary["ocr_ok"],
        "ocr_failed": summary["ocr_failed"],
        "elapsed_seconds": elapsed,
    }
    _write_result_atomic(run_dir / "result.json", result)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="デモ用DBを作成し取り込みと照合を行う")
    parser.add_argument("--run", required=True, help="demo-[a-z0-9][a-z0-9-]{0,23} 形式の実行名")
    args = parser.parse_args(argv)
    try:
        result = run_demo_db(args.run)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
