"""tools/demo_scenario.py の単体テスト。"""

from __future__ import annotations

import hashlib
import io
from pathlib import Path
import re
import tempfile
import unittest

from PIL import Image, ImageDraw

from manager.qr_decode import read_device_qr
from manager.receiver import validate_sidecar_metadata
from manager.routes import validate_manifest
from tools.demo_catalog import APPEARANCE_KEYS, DEFAULT_CATALOG_PATH, load_catalog
from tools.demo_scenario import BROKEN_PNG_BYTES, build_inspections
from tools.embed_qr_into_synthetic import create_qr_plate

FILENAME_RE = re.compile(r"^\d{8}T\d{6}_([1-9]\d*)\.png$")


def _make_dummy_truth(catalog: list[dict], photos_dir: Path) -> dict:
    """生成器を呼ばずにテスト用のダミー画像と groundtruth.json を作る。"""
    frames_dir = photos_dir / "frames"
    frames_dir.mkdir(parents=True, exist_ok=True)
    frames: list[dict] = []

    for dev_idx, device in enumerate(catalog):
        did = device["device_id"]
        is_odd = int(did.split("-")[1]) % 2 == 1
        appearance = {k: device[k] for k in APPEARANCE_KEYS}
        for shot in (1, 2, 3, 4):
            rel_file = f"frames/{did}-{shot}.png"
            dest = photos_dir / rel_file
            if is_odd:
                plate = create_qr_plate(
                    did,
                    device["device_name"],
                    plate_size=224,
                    unit=device["unit"],
                    min_value=device["min_value"],
                    max_value=device["max_value"],
                )
                img = Image.new("RGB", (320, 260), (229, 231, 235))
                img.paste(plate, (48, 18))
                # shot ごとに異なる画素を描き SHA-256 を一意にする
                draw = ImageDraw.Draw(img)
                draw.rectangle((4, 4, 12, 12), fill=(shot * 50, dev_idx * 10, 100))
                qr_bbox = [1296, 64, 224, 224]
            else:
                img = Image.new("RGB", (64, 64), (dev_idx * 10, shot * 50, 200))
                qr_bbox = None
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            raw_bytes = buf.getvalue()
            dest.write_bytes(raw_bytes)
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
                    "qr_bbox": qr_bbox,
                }
            )
    return {"v": 1, "frames": frames}


class TestDemoScenario(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._tmpdir = tempfile.TemporaryDirectory()
        cls.photos_dir = Path(cls._tmpdir.name)
        cls.catalog = load_catalog(DEFAULT_CATALOG_PATH)
        cls.truth = _make_dummy_truth(cls.catalog, cls.photos_dir)
        cls.inspections = build_inspections(cls.catalog, cls.truth, photos_dir=cls.photos_dir)

    @classmethod
    def tearDownClass(cls) -> None:
        cls._tmpdir.cleanup()

    def test_inspection_count_dates_and_validate_manifest(self) -> None:
        self.assertEqual(len(self.inspections), 6)
        expected_meta = [
            ("DMO-20261116-A", "2026-11-16 動力設備巡回", "DMO-ROUTE-A", "2026-11-16T08:00:00+09:00", "2026-11-16T08:20:00+09:00"),
            ("DMO-20261116-B", "2026-11-16 冷却・熱交換設備巡回", "DMO-ROUTE-B", "2026-11-16T14:00:00+09:00", "2026-11-16T14:20:00+09:00"),
            ("DMO-20261117-A", "2026-11-17 動力設備巡回", "DMO-ROUTE-A", "2026-11-17T08:00:00+09:00", "2026-11-17T08:20:00+09:00"),
            ("DMO-20261117-B", "2026-11-17 冷却・熱交換設備巡回", "DMO-ROUTE-B", "2026-11-17T14:00:00+09:00", "2026-11-17T14:20:00+09:00"),
            ("DMO-20261118-A", "2026-11-18 動力設備巡回", "DMO-ROUTE-A", "2026-11-18T08:00:00+09:00", "2026-11-18T08:20:00+09:00"),
            ("DMO-20261118-B", "2026-11-18 冷却・熱交換設備巡回", "DMO-ROUTE-B", "2026-11-18T14:00:00+09:00", "2026-11-18T14:20:00+09:00"),
        ]
        for insp, (iid, iname, rid, started, completed) in zip(self.inspections, expected_meta):
            manifest = insp["manifest"]
            validate_manifest(iid, manifest)
            self.assertEqual(manifest["inspection_id"], iid)
            self.assertEqual(manifest["inspection_name"], iname)
            self.assertEqual(manifest["route_id"], rid)
            self.assertEqual(manifest["operator"], "デモ担当")
            self.assertEqual(manifest["place"], "設備棟")
            self.assertEqual(manifest["started_at"], started)
            self.assertEqual(manifest["completed_at"], completed)

    def test_upload_and_unique_photo_counts_and_resend(self) -> None:
        total_uploads = sum(len(i["uploads"]) for i in self.inspections)
        total_manifest_photos = sum(len(i["manifest"]["photos"]) for i in self.inspections)
        self.assertEqual(total_uploads, 62)
        self.assertEqual(total_manifest_photos, 61)
        self.assertEqual(total_uploads - total_manifest_photos, 1)

        # 11/16 A のみ再送1件（同じ file_name / body / sidecar / sha256）
        day1_a = self.inspections[0]
        self.assertEqual(len(day1_a["uploads"]), 11)
        self.assertEqual(len(day1_a["manifest"]["photos"]), 10)
        self.assertEqual(day1_a["uploads"][0], day1_a["uploads"][1])
        self.assertEqual(day1_a["uploads"][0]["sidecar"]["local_id"], 1)

    def test_missing_extra_retake_and_broken_exceptions(self) -> None:
        for idx, insp in enumerate(self.inspections):
            m = insp["manifest"]
            if m["inspection_id"] == "DMO-20261118-A":
                self.assertEqual(m["missing"], ["DMO-010"])
                self.assertEqual(m["extra"], ["DMO-011"])
                self.assertEqual(len(m["photos"]), 11)
                self.assertEqual(len(insp["uploads"]), 11)
            else:
                self.assertEqual(m["missing"], [], msg=f"index {idx}")
                self.assertEqual(m["extra"], [], msg=f"index {idx}")
                self.assertEqual(len(m["photos"]), 10, msg=f"index {idx}")

        # 11/18 A: DMO-001 の撮り直し（shot 3 と shot 4 の別写真）と DMO-011 のルート外
        day3_a_uploads = self.inspections[4]["uploads"]
        shot3_001 = day3_a_uploads[0]
        extra_011 = day3_a_uploads[9]
        retake_001 = day3_a_uploads[10]
        self.assertNotEqual(shot3_001["sha256"], retake_001["sha256"])
        self.assertNotEqual(shot3_001["body"], retake_001["body"])
        self.assertEqual(
            shot3_001["sha256"],
            next(f["sha256"] for f in self.truth["frames"] if f["device_id"] == "DMO-001" and f["shot"] == 3),
        )
        self.assertEqual(
            retake_001["sha256"],
            next(f["sha256"] for f in self.truth["frames"] if f["device_id"] == "DMO-001" and f["shot"] == 4),
        )
        self.assertEqual(
            extra_011["sha256"],
            next(f["sha256"] for f in self.truth["frames"] if f["device_id"] == "DMO-011" and f["shot"] == 4),
        )

        # 11/18 B: DMO-019 の破損本文と送信ハッシュ
        day3_b = self.inspections[5]
        broken_upload = day3_b["uploads"][8]  # 011..020 の9番目が DMO-019
        broken_sha = hashlib.sha256(BROKEN_PNG_BYTES).hexdigest()
        self.assertEqual(broken_upload["body"], BROKEN_PNG_BYTES)
        self.assertEqual(broken_upload["sha256"], broken_sha)
        self.assertEqual(broken_upload["sidecar"]["device_id"], "DMO-019")
        self.assertEqual(broken_upload["sidecar"]["device_name"], "熱交換器一次側温度計")
        self.assertEqual(day3_b["manifest"]["photos"][8]["sha256"], broken_sha)
        self.assertEqual(day3_b["manifest"]["photos"][8]["device_id"], "DMO-019")

    def test_sidecar_contracts_and_qr_consistency(self) -> None:
        catalog_by_id = {d["device_id"]: d for d in self.catalog}
        sha_to_frame = {f["sha256"]: f for f in self.truth["frames"]}
        seen_local_ids: list[int] = []

        for insp in self.inspections:
            iid = insp["manifest"]["inspection_id"]
            rid = insp["manifest"]["route_id"]
            for idx, upload in enumerate(insp["uploads"]):
                side = upload["sidecar"]
                self.assertIsNone(validate_sidecar_metadata(dict(side)))
                for req_key in ("local_id", "captured_at", "inspection_id", "inspection_name", "route_id"):
                    self.assertIn(req_key, side)
                self.assertEqual(side["inspection_id"], iid)
                self.assertEqual(side["route_id"], rid)
                m = FILENAME_RE.fullmatch(upload["file_name"])
                self.assertIsNotNone(m, msg=upload["file_name"])
                self.assertEqual(m.group(1), str(side["local_id"]))
                if not (iid == "DMO-20261116-A" and idx == 1):
                    seen_local_ids.append(side["local_id"])

                if upload["body"] == BROKEN_PNG_BYTES:
                    continue

                frame = sha_to_frame[upload["sha256"]]
                did = frame["device_id"]
                is_odd = int(did.split("-")[1]) % 2 == 1
                if is_odd:
                    self.assertNotIn("device_id", side)
                    self.assertNotIn("device_name", side)
                    self.assertNotIn("device_id_source", side)
                    # 写真内QRのIDとカタログIDが一致すること
                    tmp_png = self.photos_dir / f"qr_check_{side['local_id']}.png"
                    tmp_png.write_bytes(upload["body"])
                    qr = read_device_qr(str(tmp_png))
                    self.assertEqual(qr.status, "found")
                    self.assertEqual(qr.device_id, did)
                else:
                    self.assertEqual(side["device_id"], did)
                    self.assertEqual(side["device_name"], catalog_by_id[did]["device_name"])
                    self.assertNotIn("device_id_source", side)

        self.assertEqual(seen_local_ids, list(range(1, 62)))

    def test_same_device_has_identical_appearance_in_truth(self) -> None:
        catalog_by_id = {d["device_id"]: {k: d[k] for k in APPEARANCE_KEYS} for d in self.catalog}
        seen: dict[str, set[tuple]] = {}
        for frame in self.truth["frames"]:
            did = frame["device_id"]
            app = frame["appearance"]
            self.assertEqual(app, catalog_by_id[did])
            seen.setdefault(did, set()).add(tuple(sorted(app.items())))
        for did, apps in seen.items():
            self.assertEqual(len(apps), 1, msg=did)


if __name__ == "__main__":
    unittest.main()
