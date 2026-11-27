"""tools/eval_front_main.py の単体テスト（外部データセット非依存のモックテスト）。"""

from __future__ import annotations

import csv
import json
from pathlib import Path
import tempfile
import unittest

import qrcode

from manager.qr_label import build_payload
from tools.eval_front_main import (
    compute_group_metrics,
    filter_jsw_entries,
    filter_synthetic_front,
    load_devices_csv,
    main as eval_main,
    verify_dataset,
)


def _make_qr_png(path: Path, payload: str) -> None:
    img = qrcode.make(payload)
    img.save(path)


class TestEvalFrontMain(unittest.TestCase):
    def test_filter_synthetic_and_jsw(self) -> None:
        syn_raw = [
            {"image": "a.png", "device_id": "SYN-001", "condition": {"category": "正面"}},
            {"image": "b.png", "device_id": "SYN-002", "condition": {"category": "斜め"}},
            {
                "image": "c.png",
                "device_id": "SYN-003",
                "condition": {"category": "正面", "degradations": ["blur"]},
            },
            {
                "image": "d.png",
                "device_id": "SYN-004",
                "condition": {"category": "正面"},
                "degradations": ["glare"],
            },
        ]
        real_raw = [
            {"image": "C:/data/企業提供_日本製鋼所/m1.jpg", "device_id": "JSW-001"},
            {"image": "C:/data/other/m2.jpg", "device_id": "JSW-002"},
            {"image": "C:/data/other/m3.jpg", "device_id": "REAL-001"},
        ]

        syn_filtered = filter_synthetic_front(syn_raw)
        jsw_filtered = filter_jsw_entries(real_raw)

        self.assertEqual([e["image"] for e in syn_filtered], ["a.png"])
        self.assertEqual([e["device_id"] for e in jsw_filtered], ["JSW-001", "JSW-002"])

    def test_verify_dataset_and_cli_check_qr_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            qr_img = tmp / "syn_001.png"
            _make_qr_png(qr_img, build_payload("SYN-001", "テスト圧力計"))

            devices_csv = tmp / "devices.csv"
            with devices_csv.open("w", encoding="utf-8", newline="") as f:
                writer = csv.writer(f)
                writer.writerow(["device_id", "device_name", "kind", "unit", "min_value", "max_value"])
                writer.writerow(["SYN-001", "テスト圧力計", "synthetic", "MPa", "0", "150"])
                writer.writerow(["JSW-001", "企業提供圧力計", "real", "MPa", "0", "150"])

            syn_gt = tmp / "syn_gt.json"
            syn_gt.write_text(
                json.dumps(
                    [
                        {
                            "image": str(qr_img),
                            "device_id": "SYN-001",
                            "true_value": 10.0,
                            "min_value": 0.0,
                            "max_value": 150.0,
                            "condition": {"category": "正面"},
                        },
                        {
                            "image": "ignored_angled.png",
                            "device_id": "SYN-999",
                            "condition": {"category": "斜め"},
                        },
                    ],
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            real_gt = tmp / "real_gt.json"
            real_gt.write_text(
                json.dumps(
                    [
                        {
                            "image": "C:/mock/企業提供_日本製鋼所/sample.jpg",
                            "device_id": "JSW-001",
                            "true_value": 0.16,
                            "min_value": 0.0,
                            "max_value": 150.0,
                        }
                    ],
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            out_ds = tmp / "combined.json"
            rc = eval_main(
                [
                    "--synthetic-gt",
                    str(syn_gt),
                    "--real-gt",
                    str(real_gt),
                    "--devices-csv",
                    str(devices_csv),
                    "--out-dataset",
                    str(out_ds),
                    "--check-qr-only",
                ]
            )
            self.assertEqual(rc, 0)
            combined = json.loads(out_ds.read_text(encoding="utf-8"))
            self.assertEqual(len(combined), 2)

            devices = load_devices_csv(devices_csv)
            verif = verify_dataset(
                [combined[0]],
                [combined[1]],
                devices,
                check_qr=True,
            )
            self.assertTrue(verif["ok"])
            self.assertEqual(verif["synthetic"]["qr_ok"], 1)
            self.assertEqual(verif["synthetic"]["id_match"], 1)
            self.assertEqual(verif["jsw"]["csv_ok"], 1)

    def test_compute_group_metrics(self) -> None:
        rows = [
            {"value": 10.0, "reference_error": 0.01},
            {"value": 20.0, "reference_error": 0.04},
            {"value": None, "reference_error": None},
        ]
        m = compute_group_metrics(rows)
        self.assertEqual(m["total"], 3)
        self.assertEqual(m["read_ok"], 2)
        self.assertEqual(m["within_2_5_fs"], 1)
        self.assertEqual(m["within_5_0_fs"], 2)
        self.assertEqual(m["mean_fs"], 2.5)
        self.assertEqual(m["median_fs"], 2.5)
        self.assertEqual(m["max_fs"], 4.0)


if __name__ == "__main__":
    unittest.main()
