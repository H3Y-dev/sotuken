"""tools/demo_transport.py の単体テスト。"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile
import threading
import unittest
import urllib.error

from manager.receiver import ReceiverServer
from manager.routes import get_manifest, inspection_status
from manager.storage import Storage
from tools.demo_catalog import APPEARANCE_KEYS, DEFAULT_CATALOG_PATH, load_catalog
from tools.demo_scenario import BROKEN_PNG_BYTES, build_inspections
from tools.demo_transport import send_manifest, upload_photo


def _make_dummy_truth(catalog: list[dict], photos_dir: Path) -> dict:
    frames_dir = photos_dir / "frames"
    frames_dir.mkdir(parents=True, exist_ok=True)
    frames: list[dict] = []
    for dev_idx, device in enumerate(catalog):
        did = device["device_id"]
        appearance = {k: device[k] for k in APPEARANCE_KEYS}
        for shot in (1, 2, 3, 4):
            rel_file = f"frames/{did}-{shot}.png"
            raw_bytes = b"\x89PNG\r\n\x1a\n" + f"{did}:{shot}".encode("ascii")
            (photos_dir / rel_file).write_bytes(raw_bytes)
            frames.append(
                {
                    "file": rel_file,
                    "sha256": hashlib.sha256(raw_bytes).hexdigest(),
                    "device_id": did,
                    "device_name": device["device_name"],
                    "appearance": appearance,
                    "shot": shot,
                    "seed": 1000 + (dev_idx + 1) * 10 + shot,
                    "true_value": float(shot),
                    "unit": device["unit"],
                    "min_value": device["min_value"],
                    "max_value": device["max_value"],
                    "value_percent": 10 * shot,
                    "yaw_deg": 0,
                    "pitch_deg": 0,
                    "lighting": "normal",
                    "glass_scratches": 0.0,
                    "sensor_noise": 0.0,
                    "qr_bbox": None,
                }
            )
    return {"v": 1, "frames": frames}


class TestDemoTransport(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self.root = Path(self._tmpdir.name)
        self.photos_dir = self.root / "photos"
        self.incoming_dir = self.root / "incoming"
        self.db_path = self.root / "manager.db"
        self.token = "demo-test-token-not-prod"
        self.server = ReceiverServer(
            ("127.0.0.1", 0),
            self.token,
            str(self.incoming_dir),
            quiet=True,
            db_path=str(self.db_path),
        )
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        host, port = self.server.server_address
        self.base_url = f"http://{host}:{port}"

    def tearDown(self) -> None:
        self.server.shutdown()
        self.thread.join(timeout=5)
        self.server.server_close()
        self._tmpdir.cleanup()

    def test_send_all_planned_inspections_and_manifests(self) -> None:
        catalog = load_catalog(DEFAULT_CATALOG_PATH)
        truth = _make_dummy_truth(catalog, self.photos_dir)
        inspections = build_inspections(catalog, truth, photos_dir=self.photos_dir)

        normal_count = 0
        duplicate_count = 0
        manifest_responses: list[dict] = []
        expected_files: dict[str, dict] = {}

        for insp in inspections:
            for upload in insp["uploads"]:
                res = upload_photo(self.base_url, self.token, upload)
                self.assertEqual(res["stored"], upload["file_name"])
                if res.get("duplicate") is True:
                    duplicate_count += 1
                else:
                    self.assertNotIn("duplicate", res)
                    normal_count += 1
                expected_files.setdefault(upload["file_name"], upload)
            m_res = send_manifest(self.base_url, self.token, insp["manifest"])
            manifest_responses.append(m_res)

        self.assertEqual(normal_count + duplicate_count, 62)
        self.assertEqual(normal_count, 61)
        self.assertEqual(duplicate_count, 1)
        self.assertEqual(len(manifest_responses), 6)

        saved_pngs = sorted(p.name for p in self.incoming_dir.glob("*.png"))
        saved_jsons = sorted(p.name for p in self.incoming_dir.glob("*.json"))
        self.assertEqual(len(saved_pngs), 61)
        self.assertEqual(len(saved_jsons), 61)
        self.assertEqual(saved_pngs, sorted(expected_files))

        for file_name, upload in expected_files.items():
            saved_body = (self.incoming_dir / file_name).read_bytes()
            self.assertEqual(saved_body, upload["body"])
            self.assertEqual(hashlib.sha256(saved_body).hexdigest(), upload["sha256"])

            sidecar_path = self.incoming_dir / f"{Path(file_name).stem}.json"
            saved_sidecar = json.loads(sidecar_path.read_text(encoding="utf-8"))
            self.assertEqual(saved_sidecar, upload["sidecar"])

        # 破損画像も受信されていること
        broken_items = [u for u in expected_files.values() if u["body"] == BROKEN_PNG_BYTES]
        self.assertEqual(len(broken_items), 1)
        self.assertEqual(broken_items[0]["sidecar"]["device_id"], "DMO-019")

        storage = Storage(str(self.db_path))
        for insp, m_res in zip(inspections, manifest_responses):
            manifest = insp["manifest"]
            iid = manifest["inspection_id"]
            self.assertTrue(m_res["ok"])
            self.assertEqual(m_res["matched"], len(manifest["photos"]))
            self.assertEqual(m_res["missing_photos"], [])
            self.assertEqual(get_manifest(storage, iid), manifest)
            status = inspection_status(storage, iid, str(self.incoming_dir))
            self.assertEqual(status["state"], "完了")
            self.assertEqual(status["matched"], len(manifest["photos"]))
            self.assertEqual(status["missing_photos"], [])

    def test_upload_conflict_returns_409(self) -> None:
        first_body = b"\x89PNG\r\n\x1a\nfirst"
        photo = {
            "file_name": "20261116T080100_1.png",
            "body": first_body,
            "sidecar": {"local_id": 1, "captured_at": "2026-11-16T08:01:00+09:00"},
            "sha256": hashlib.sha256(first_body).hexdigest(),
        }
        self.assertEqual(upload_photo(self.base_url, self.token, photo), {"stored": photo["file_name"]})

        # 同一再送は 200 + duplicate=True
        self.assertEqual(
            upload_photo(self.base_url, self.token, photo),
            {"stored": photo["file_name"], "duplicate": True},
        )

        # 異なる本文で同名送信は 409
        other_body = b"\x89PNG\r\n\x1a\nsecond"
        conflict_photo = {
            "file_name": photo["file_name"],
            "body": other_body,
            "sidecar": photo["sidecar"],
            "sha256": hashlib.sha256(other_body).hexdigest(),
        }
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            upload_photo(self.base_url, self.token, conflict_photo)
        self.assertEqual(ctx.exception.code, 409)
        ctx.exception.close()

    def test_send_manifest_fails_when_photos_missing(self) -> None:
        manifest = {
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
            "photos": [
                {
                    "file_name": "20261116T080100_1.png",
                    "sha256": "0" * 64,
                    "device_id": None,
                    "device_id_source": None,
                    "captured_at": "2026-11-16T08:01:00+09:00",
                }
            ],
        }
        with self.assertRaises(RuntimeError):
            send_manifest(self.base_url, self.token, manifest)
