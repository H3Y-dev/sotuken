"""tools/generate_demo_photos.py のユニットテスト（Chrome・Node不要）。"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from tools.demo_catalog import APPEARANCE_KEYS, DEFAULT_CATALOG_PATH, load_catalog
from tools.generate_demo_photos import (
    SHOT_SPECS,
    build_groundtruth_entry,
    build_renderer_args,
    main,
    verify_groundtruth,
    verify_raw_output,
)


def _args_to_dict(args: list[str]) -> dict[str, str]:
    it = iter(args)
    return {k: next(it) for k in it}


def _write_raw_frame(
    raw_dir: Path,
    device: dict,
    shot: int,
    *,
    appearance_override: dict | None = None,
    min_value_override: float | None = None,
    max_value_override: float | None = None,
    true_value_override: float | None = None,
    unit_override: str | None = None,
) -> Path:
    raw_dir.mkdir(parents=True, exist_ok=True)
    png_path = raw_dir / "frame.png"
    png_path.write_bytes(f"png-{device['device_id']}-{shot}".encode("utf-8"))

    pct = float(SHOT_SPECS[shot]["value_percent"])
    min_v = device["min_value"] if min_value_override is None else min_value_override
    max_v = device["max_value"] if max_value_override is None else max_value_override
    true_v = (
        min_v + (max_v - min_v) * pct / 100.0
        if true_value_override is None
        else true_value_override
    )
    app = {
        "sweep_deg": device["sweep_deg"],
        "dial_color": device["dial_color"],
        "number_position": device["number_position"],
        "font": device["font"],
        "needle_shape": device["needle_shape"],
        "needle_color": device["needle_color"],
        "bezel_color": device["bezel_color"],
        "danger_band": device["danger_band"],
        "max_pointer": device["max_pointer"],
    }
    if appearance_override:
        app.update(appearance_override)

    per_frame_json = {
        "unit": device["unit"] if unit_override is None else unit_override,
        "min_value": min_v,
        "max_value": max_v,
        "true_value": true_v,
        "appearance": app,
    }
    (raw_dir / "frame.json").write_text(
        json.dumps(per_frame_json, ensure_ascii=False), encoding="utf-8"
    )
    manifest = {
        "frames": [
            {
                "file": "frame.png",
                "json": "frame.json",
                "true_value": true_v,
                "min_value": min_v,
                "max_value": max_v,
                "appearance": app,
            }
        ]
    }
    (raw_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False), encoding="utf-8"
    )
    return png_path


class TestGenerateDemoPhotos(unittest.TestCase):
    def setUp(self) -> None:
        self.catalog = load_catalog(DEFAULT_CATALOG_PATH)

    def test_build_renderer_args_preserves_catalog_appearance(self) -> None:
        appearance_flags = (
            "--sweep-deg",
            "--dial-color",
            "--number-position",
            "--font",
            "--needle-shape",
            "--needle-color",
            "--bezel-color",
            "--danger-band",
            "--max-pointer",
        )
        with tempfile.TemporaryDirectory() as tmp:
            for device in self.catalog:
                per_shot_appearances = []
                for shot in (1, 2, 3, 4):
                    raw_dir = Path(tmp) / device["device_id"] / str(shot)
                    args = build_renderer_args(device, shot, raw_dir)
                    self.assertNotIn("--legacy-grid", args)
                    self.assertNotIn("--final-set", args)
                    arg_map = _args_to_dict(args)
                    self.assertEqual(arg_map["--meters"], device["meter_key"])
                    self.assertEqual(arg_map["--sweep-deg"], str(device["sweep_deg"]))
                    self.assertEqual(arg_map["--dial-color"], device["dial_color"])
                    self.assertEqual(arg_map["--number-position"], device["number_position"])
                    self.assertEqual(arg_map["--font"], device["font"])
                    self.assertEqual(arg_map["--needle-shape"], device["needle_shape"])
                    self.assertEqual(arg_map["--needle-color"], device["needle_color"])
                    self.assertEqual(arg_map["--bezel-color"], device["bezel_color"])
                    self.assertEqual(arg_map["--danger-band"], "false")
                    self.assertEqual(arg_map["--max-pointer"], "false")
                    self.assertEqual(arg_map["--distance"], "5.6")
                    self.assertEqual(arg_map["--out"], str(raw_dir.resolve()))
                    per_shot_appearances.append(tuple(arg_map[k] for k in appearance_flags))
                self.assertEqual(len(set(per_shot_appearances)), 1)

    def test_verify_raw_output_accepts_matching_frame(self) -> None:
        device = self.catalog[0]
        with tempfile.TemporaryDirectory() as tmp:
            raw_dir = Path(tmp) / "raw"
            _write_raw_frame(raw_dir, device, 1)
            png_path, frame = verify_raw_output(device, 1, raw_dir)
            self.assertTrue(png_path.is_file())
            self.assertAlmostEqual(frame["true_value"], 1.6 * 0.07, places=8)

    def test_verify_raw_output_rejects_mismatched_appearance_or_range(self) -> None:
        device = self.catalog[0]
        with tempfile.TemporaryDirectory() as tmp:
            bad_app = Path(tmp) / "bad_app"
            _write_raw_frame(bad_app, device, 1, appearance_override={"dial_color": "black"})
            with self.assertRaises(ValueError):
                verify_raw_output(device, 1, bad_app)

            bad_range = Path(tmp) / "bad_range"
            _write_raw_frame(bad_range, device, 1, max_value_override=2.0)
            with self.assertRaises(ValueError):
                verify_raw_output(device, 1, bad_range)

            bad_unit = Path(tmp) / "bad_unit"
            _write_raw_frame(bad_unit, device, 1, unit_override="kPa")
            with self.assertRaises(ValueError):
                verify_raw_output(device, 1, bad_unit)

    def test_verify_groundtruth_matches_catalog_and_detects_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            photos_dir = Path(tmp) / "photos"
            frames_dir = photos_dir / "frames"
            frames_dir.mkdir(parents=True)
            entries = []
            for device in self.catalog:
                for shot in (1, 2, 3, 4):
                    rel = f"frames/{device['device_id']}-{shot}.png"
                    png_path = photos_dir / rel
                    png_path.write_bytes(f"img-{device['device_id']}-{shot}".encode("utf-8"))
                    sha = hashlib.sha256(png_path.read_bytes()).hexdigest()
                    pct = float(SHOT_SPECS[shot]["value_percent"])
                    raw_frame = {
                        "true_value": device["min_value"]
                        + (device["max_value"] - device["min_value"]) * pct / 100.0
                    }
                    entry = build_groundtruth_entry(device, shot, rel, sha, raw_frame)
                    self.assertIsNone(entry["qr_bbox"])
                    self.assertEqual(
                        entry["appearance"], {k: device[k] for k in APPEARANCE_KEYS}
                    )
                    entries.append(entry)

            truth = {"v": 1, "frames": entries}
            verify_groundtruth(self.catalog, truth, photos_dir)

            truth["frames"][0]["appearance"]["dial_color"] = "black"
            with self.assertRaises(ValueError):
                verify_groundtruth(self.catalog, truth, photos_dir)

    def test_main_rejects_existing_output_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            existing = Path(tmp) / "photos"
            existing.mkdir()
            rc = main(["--out", str(existing)])
            self.assertEqual(rc, 1)


if __name__ == "__main__":
    unittest.main()
