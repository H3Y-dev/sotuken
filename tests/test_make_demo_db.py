"""tools/make_demo_db.py の単体テストおよび小規模結合テスト。"""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from PIL import Image

from manager.storage import Storage
from tools.demo_catalog import APPEARANCE_KEYS, DEFAULT_CATALOG_PATH, load_catalog
from tools.demo_scenario import BROKEN_PNG_BYTES
from tools.embed_qr_into_synthetic import create_qr_plate
from tools.make_demo_db import (
    main,
    run_demo_db,
    seed_catalog_and_routes,
    validate_inputs,
    validate_run_name,
    verify_db,
    wait_for_ingest,
)


def _write_catalog_csv(path: Path, devices: list[dict]) -> None:
    cols = list(devices[0].keys())
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=cols, lineterminator="\n")
        writer.writeheader()
        for dev in devices:
            row = dict(dev)
            row["danger_band"] = "true" if dev["danger_band"] else "false"
            row["max_pointer"] = "true" if dev["max_pointer"] else "false"
            row["acceptable_min"] = "" if dev["acceptable_min"] is None else dev["acceptable_min"]
            row["acceptable_max"] = "" if dev["acceptable_max"] is None else dev["acceptable_max"]
            writer.writerow(row)


def _make_mini_photos(devices: list[dict], photos_dir: Path) -> dict:
    frames_dir = photos_dir / "frames"
    frames_dir.mkdir(parents=True, exist_ok=True)
    frames: list[dict] = []
    for idx, dev in enumerate(devices):
        did = dev["device_id"]
        num = int(did.split("-")[1])
        appearance = {k: dev[k] for k in APPEARANCE_KEYS}
        for shot in (1, 2, 3, 4):
            rel = f"frames/{did}-{shot}.png"
            out_path = photos_dir / rel
            base = Image.new("RGB", (640, 480), (240, 240, 240))
            if num % 2 == 1:
                plate = create_qr_plate(
                    did,
                    dev["device_name"],
                    224,
                    unit=dev["unit"],
                    min_value=dev["min_value"],
                    max_value=dev["max_value"],
                )
                canvas = Image.new("RGB", (640 + 256, 480), (229, 231, 235))
                canvas.paste(base, (0, 0))
                canvas.paste(plate, (656, 64))
                canvas.save(out_path, format="PNG")
                qr_bbox = [656, 64, 224, 224]
            else:
                base.save(out_path, format="PNG")
                qr_bbox = None
            raw_bytes = out_path.read_bytes()
            frames.append(
                {
                    "file": rel,
                    "sha256": hashlib.sha256(raw_bytes).hexdigest(),
                    "device_id": did,
                    "device_name": dev["device_name"],
                    "appearance": appearance,
                    "shot": shot,
                    "seed": 1000 + (idx + 1) * 10 + shot,
                    "true_value": float(shot),
                    "unit": dev["unit"],
                    "min_value": dev["min_value"],
                    "max_value": dev["max_value"],
                    "value_percent": 10 * shot,
                    "yaw_deg": 0,
                    "pitch_deg": 0,
                    "lighting": "normal",
                    "glass_scratches": 0.0,
                    "sensor_noise": 0.0,
                    "qr_bbox": qr_bbox,
                }
            )
    truth = {"v": 1, "frames": frames}
    (photos_dir / "groundtruth.json").write_text(
        json.dumps(truth, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return truth


class _FakeWatcher:
    def __init__(self, rc: int | None = None) -> None:
        self._rc = rc

    def poll(self) -> int | None:
        return self._rc


class TestMakeDemoDbUnit(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        all_devices = load_catalog(DEFAULT_CATALOG_PATH)
        self.mini_devices = [all_devices[0], all_devices[1], all_devices[10]]  # 001, 002, 011
        self.photos_dir = self.root / "photos"
        self.truth = _make_mini_photos(self.mini_devices, self.photos_dir)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_validate_run_name_and_cli_rejection(self) -> None:
        self.assertEqual(validate_run_name("demo-01"), "demo-01")
        for bad in ("", "prod", "demo-", "demo-../x", "demo-" + "a" * 25, "demo_01"):
            with self.assertRaises(ValueError):
                validate_run_name(bad)
        self.assertEqual(main(["--run", "bad-name"]), 1)

    def test_validate_inputs_rejects_mismatch_and_traversal(self) -> None:
        validate_inputs(self.mini_devices, self.truth, self.photos_dir)

        bad_ver = {"v": 2, "frames": self.truth["frames"]}
        with self.assertRaises(ValueError):
            validate_inputs(self.mini_devices, bad_ver, self.photos_dir)

        bad_sha = json.loads(json.dumps(self.truth))
        bad_sha["frames"][0]["sha256"] = "0" * 64
        with self.assertRaises(ValueError):
            validate_inputs(self.mini_devices, bad_sha, self.photos_dir)

        bad_app = json.loads(json.dumps(self.truth))
        bad_app["frames"][0]["appearance"]["dial_color"] = "invalid"
        with self.assertRaises(ValueError):
            validate_inputs(self.mini_devices, bad_app, self.photos_dir)

        bad_path = json.loads(json.dumps(self.truth))
        bad_path["frames"][0]["file"] = "../outside.png"
        with self.assertRaises(ValueError):
            validate_inputs(self.mini_devices, bad_path, self.photos_dir)

    def test_wait_for_ingest_exited_and_timeout(self) -> None:
        db_path = self.root / "manager.db"
        Storage(str(db_path))
        expected = {
            "a" * 64: {
                "file_name": "20261116T080100_1.png",
                "inspection_id": "DMO-20261116-A",
                "route_id": "DMO-ROUTE-A",
                "device_id": "DMO-001",
                "device_id_source": "pc_qr",
                "broken": False,
            }
        }
        with self.assertRaises(RuntimeError):
            wait_for_ingest(db_path, expected, _FakeWatcher(rc=1), timeout_s=5)  # type: ignore[arg-type]

        with self.assertRaises(TimeoutError) as ctx:
            wait_for_ingest(db_path, expected, _FakeWatcher(rc=None), timeout_s=0)  # type: ignore[arg-type]
        self.assertIn("20261116T080100_1.png", str(ctx.exception))
        self.assertIn("watcher.log", str(ctx.exception))

    def test_verify_db_checks_duplicates_source_broken_and_route_ok(self) -> None:
        db_path = self.root / "manager.db"
        seed_catalog_and_routes(db_path, self.mini_devices)
        storage = Storage(str(db_path))

        sha1 = "1" * 64
        sha2 = "2" * 64
        sha3 = "3" * 64
        expected = {
            sha1: {
                "file_name": "f1.png",
                "inspection_id": "DMO-20261116-A",
                "route_id": "DMO-ROUTE-A",
                "device_id": "DMO-001",
                "device_id_source": "pc_qr",
                "broken": False,
            },
            sha2: {
                "file_name": "f2.png",
                "inspection_id": "DMO-20261116-B",
                "route_id": "DMO-ROUTE-B",
                "device_id": "DMO-011",
                "device_id_source": "sidecar",
                "broken": True,
            },
            sha3: {
                "file_name": "f3.png",
                "inspection_id": "DMO-20261116-B",
                "route_id": "DMO-ROUTE-B",
                "device_id": "DMO-011",
                "device_id_source": "pc_qr",
                "broken": False,
            },
        }
        with storage.connection() as conn:
            conn.execute(
                "INSERT INTO inspections VALUES ('DMO-20261116-A','A','DMO-ROUTE-A','op','pl','2026-11-16T08:00:00+09:00','2026-11-16T08:20:00+09:00','2026-11-16T08:20:00+09:00','{}')"
            )
            conn.execute(
                "INSERT INTO inspections VALUES ('DMO-20261116-B','B','DMO-ROUTE-B','op','pl','2026-11-16T14:00:00+09:00','2026-11-16T14:20:00+09:00','2026-11-16T14:20:00+09:00','{}')"
            )
            conn.execute(
                "INSERT INTO meter_readings (device_name, value, stage, image_path, timestamp, image_sha256, status, device_id, device_id_source, inspection_id, route_id) "
                "VALUES ('d1', 1.2, 'ok', 'p1', '2026-11-16T08:01:00+09:00', ?, 'ok', 'DMO-001', 'pc_qr', 'DMO-20261116-A', 'DMO-ROUTE-A')",
                (sha1,),
            )
            conn.execute(
                "INSERT INTO meter_readings (device_name, value, stage, image_path, timestamp, image_sha256, status, failure_stage, failure_code, device_id, device_id_source, inspection_id, route_id) "
                "VALUES ('d2', NULL, 'image_unreadable', 'p2', '2026-11-16T14:01:00+09:00', ?, 'failed', 'unknown', 'unknown_failure', 'DMO-011', 'sidecar', 'DMO-20261116-B', 'DMO-ROUTE-B')",
                (sha2,),
            )
            conn.execute(
                "INSERT INTO meter_readings (device_name, value, stage, image_path, timestamp, image_sha256, status, device_id, device_id_source, inspection_id, route_id) "
                "VALUES ('d2', 5.0, 'ok', 'p3', '2026-11-16T14:02:00+09:00', ?, 'ok', 'DMO-011', 'pc_qr', 'DMO-20261116-B', 'DMO-ROUTE-B')",
                (sha3,),
            )

        summary = verify_db(db_path, expected, self.mini_devices, expected_inspections=2)
        self.assertEqual(summary["ocr_ok"], 2)
        self.assertEqual(summary["ocr_failed"], 1)

        with storage.connection() as conn:
            conn.execute(
                "INSERT INTO meter_readings (device_name, value, stage, image_path, timestamp, image_sha256, status, device_id, device_id_source, inspection_id, route_id) "
                "VALUES ('d1', 1.2, 'ok', 'p1b', '2026-11-16T08:01:00+09:00', ?, 'ok', 'DMO-001', 'pc_qr', 'DMO-20261116-A', 'DMO-ROUTE-A')",
                (sha1,),
            )
        with self.assertRaises(RuntimeError):
            verify_db(db_path, expected, self.mini_devices, expected_inspections=2)


class TestMakeDemoDbIntegration(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        all_devices = load_catalog(DEFAULT_CATALOG_PATH)
        self.mini_devices = [all_devices[0], all_devices[1], all_devices[10]]  # 001, 002, 011
        self.catalog_path = self.root / "demo_devices.csv"
        _write_catalog_csv(self.catalog_path, self.mini_devices)
        self.photos_dir = self.root / "demo" / "photos"
        self.truth = _make_mini_photos(self.mini_devices, self.photos_dir)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _mini_inspections(self, catalog: list[dict], truth: dict, photos_dir: Path) -> list[dict]:
        frames = {(f["device_id"], f["shot"]): f for f in truth["frames"]}
        by_id = {d["device_id"]: d for d in catalog}

        def make_upload(did: str, shot: int, local_id: int, ts: str, insp_id: str, insp_name: str, route_id: str, broken: bool = False) -> dict:
            if broken:
                body = BROKEN_PNG_BYTES
            else:
                body = (photos_dir / frames[(did, shot)]["file"]).read_bytes()
            sha = hashlib.sha256(body).hexdigest()
            sidecar: dict = {
                "local_id": local_id,
                "captured_at": ts,
                "inspection_id": insp_id,
                "inspection_name": insp_name,
                "route_id": route_id,
            }
            include_id = broken or (int(did.split("-")[1]) % 2 == 0)
            if include_id:
                sidecar["device_id"] = did
                sidecar["device_name"] = by_id[did]["device_name"]
            return {
                "file_name": f"{ts[:19].replace('-', '').replace(':', '')}_{local_id}.png",
                "body": body,
                "sidecar": sidecar,
                "sha256": sha,
            }

        u1 = make_upload("DMO-001", 1, 1, "2026-11-16T08:01:00+09:00", "DMO-20261116-A", "2026-11-16 動力設備巡回", "DMO-ROUTE-A")
        u2 = make_upload("DMO-002", 1, 2, "2026-11-16T08:02:00+09:00", "DMO-20261116-A", "2026-11-16 動力設備巡回", "DMO-ROUTE-A")
        u3 = make_upload("DMO-011", 1, 3, "2026-11-16T14:01:00+09:00", "DMO-20261116-B", "2026-11-16 冷却・熱交換設備巡回", "DMO-ROUTE-B")
        u4 = make_upload("DMO-011", 3, 4, "2026-11-16T14:02:00+09:00", "DMO-20261116-B", "2026-11-16 冷却・熱交換設備巡回", "DMO-ROUTE-B", broken=True)

        def mphoto(u: dict, include_id: bool) -> dict:
            return {
                "file_name": u["file_name"],
                "sha256": u["sha256"],
                "device_id": u["sidecar"]["device_id"] if include_id else None,
                "device_id_source": None,
                "captured_at": u["sidecar"]["captured_at"],
            }

        return [
            {
                "uploads": [u1, dict(u1), u2],
                "manifest": {
                    "v": 1,
                    "inspection_id": "DMO-20261116-A",
                    "inspection_name": "2026-11-16 動力設備巡回",
                    "route_id": "DMO-ROUTE-A",
                    "operator": "デモ担当",
                    "place": "設備棟",
                    "started_at": "2026-11-16T08:00:00+09:00",
                    "completed_at": "2026-11-16T08:20:00+09:00",
                    "missing": [],
                    "extra": [],
                    "photos": [mphoto(u1, False), mphoto(u2, True)],
                },
            },
            {
                "uploads": [u3, u4],
                "manifest": {
                    "v": 1,
                    "inspection_id": "DMO-20261116-B",
                    "inspection_name": "2026-11-16 冷却・熱交換設備巡回",
                    "route_id": "DMO-ROUTE-B",
                    "operator": "デモ担当",
                    "place": "設備棟",
                    "started_at": "2026-11-16T14:00:00+09:00",
                    "completed_at": "2026-11-16T14:20:00+09:00",
                    "missing": [],
                    "extra": [],
                    "photos": [mphoto(u3, False), mphoto(u4, True)],
                },
            },
        ]

    def _fast_watcher_cmd(self, incoming_dir: Path, db_path: Path, images_dir: Path, overlays_dir: Path) -> list[str]:
        repo = Path(__file__).resolve().parents[1]
        code = "\n".join(
            [
                "import sys",
                f"sys.path.insert(0, {str(repo)!r})",
                "from unittest.mock import patch",
                "import manager.watcher as mw",
                "def fake_pipe(path, use_vlm=False):",
                "    with open(path, 'rb') as f:",
                "        data = f.read(16)",
                "    return {'stage': 'ok', 'value': 12.3} if data.startswith(b'\\x89PNG') else {'stage': 'image_unreadable', 'value': None}",
                "with patch.object(mw, 'execute_pipeline', fake_pipe):",
                "    import manager.watch_inbox as wi",
                "    wi.main()",
            ]
        )
        return [
            sys.executable,
            "-c",
            code,
            "--watch-dir",
            str(incoming_dir),
            "--db",
            str(db_path),
            "--images-dir",
            str(images_dir),
            "--overlays-dir",
            str(overlays_dir),
        ]

    def test_run_demo_db_small_plan_and_reject_existing_run(self) -> None:
        result = run_demo_db(
            "demo-mini",
            repo_root=self.root,
            catalog_path=self.catalog_path,
            photos_dir=self.photos_dir,
            inspections_builder=self._mini_inspections,
            watcher_cmd_builder=self._fast_watcher_cmd,
            timeout_s=30,
        )
        self.assertEqual(result["v"], 1)
        self.assertEqual(result["uploads"], 5)
        self.assertEqual(result["unique_photos"], 4)
        self.assertEqual(result["duplicates"], 1)
        self.assertEqual(result["devices"], 3)
        self.assertEqual(result["routes"], 2)
        self.assertEqual(result["inspections"], 2)
        self.assertEqual(result["ocr_ok"], 3)
        self.assertEqual(result["ocr_failed"], 1)

        result_file = self.root / "demo" / "runs" / "demo-mini" / "result.json"
        self.assertTrue(result_file.is_file())
        saved = json.loads(result_file.read_text(encoding="utf-8"))
        self.assertEqual(saved, result)

        with self.assertRaises(FileExistsError):
            run_demo_db(
                "demo-mini",
                repo_root=self.root,
                catalog_path=self.catalog_path,
                photos_dir=self.photos_dir,
                inspections_builder=self._mini_inspections,
                watcher_cmd_builder=self._fast_watcher_cmd,
                timeout_s=30,
            )


if __name__ == "__main__":
    unittest.main()
