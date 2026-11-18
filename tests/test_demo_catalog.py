"""tools/demo_catalog.py と eval/demo_devices.csv のユニットテスト。"""

from __future__ import annotations

import copy
from pathlib import Path
import tempfile
import unittest

from tools.demo_catalog import (
    DEFAULT_CATALOG_PATH,
    appearance_key,
    check_catalog_history,
    load_catalog,
    main,
)


def _read_default_lines() -> list[str]:
    return DEFAULT_CATALOG_PATH.read_text(encoding="utf-8").splitlines()


class TestDemoCatalog(unittest.TestCase):
    def test_load_default_catalog(self) -> None:
        devices = load_catalog(DEFAULT_CATALOG_PATH)
        self.assertEqual(len(devices), 20)
        self.assertEqual(devices[0]["device_id"], "DMO-001")
        self.assertEqual(devices[-1]["device_id"], "DMO-020")
        keys = {appearance_key(d) for d in devices}
        self.assertEqual(len(keys), 20)
        for d in devices:
            self.assertIsInstance(d["sweep_deg"], int)
            self.assertIsInstance(d["min_value"], float)
            self.assertIsInstance(d["max_value"], float)
            self.assertIs(d["danger_band"], False)
            self.assertIs(d["max_pointer"], False)
            self.assertIsNone(d["acceptable_min"])
            self.assertIsNone(d["acceptable_max"])

    def test_reject_duplicate_id(self) -> None:
        lines = _read_default_lines()
        cols = lines[1].split(",")
        cols[0] = "DMO-001"
        cols[1] = "別名の圧力計"
        lines[2] = ",".join(cols)
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "dup_id.csv"
            p.write_text("\n".join(lines) + "\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                load_catalog(p)

    def test_reject_duplicate_appearance_with_both_ids(self) -> None:
        lines = _read_default_lines()
        row1 = lines[1].split(",")
        row2 = lines[2].split(",")
        # DMO-002 の外観と目盛りを DMO-001 と同一にする（ID・名前のみ別）
        row2[2:] = row1[2:]
        lines[2] = ",".join(row2)
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "dup_app.csv"
            p.write_text("\n".join(lines) + "\n", encoding="utf-8")
            with self.assertRaises(ValueError) as ctx:
                load_catalog(p)
            msg = str(ctx.exception)
            self.assertIn("DMO-001", msg)
            self.assertIn("DMO-002", msg)

    def test_reject_scale_mismatch(self) -> None:
        lines = _read_default_lines()
        row1 = lines[1].split(",")
        row1[5] = "2.0"  # pressure-1.6 なのに max_value=2.0
        lines[1] = ",".join(row1)
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "bad_scale.csv"
            p.write_text("\n".join(lines) + "\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                load_catalog(p)

    def test_reject_one_sided_acceptable_range(self) -> None:
        lines = _read_default_lines()
        row1 = lines[1].split(",")
        row1[-2] = "0.2"
        lines[1] = ",".join(row1)
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "one_sided.csv"
            p.write_text("\n".join(lines) + "\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                load_catalog(p)

    def test_accept_valid_acceptable_range(self) -> None:
        lines = _read_default_lines()
        row1 = lines[1].split(",")
        row1[-2] = "0.2"
        row1[-1] = "1.4"
        lines[1] = ",".join(row1)
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "valid_acc.csv"
            p.write_text("\n".join(lines) + "\n", encoding="utf-8")
            devices = load_catalog(p)
            self.assertEqual(devices[0]["acceptable_min"], 0.2)
            self.assertEqual(devices[0]["acceptable_max"], 1.4)

    def test_history_rejects_deleted_id(self) -> None:
        prev = load_catalog(DEFAULT_CATALOG_PATH)
        curr = copy.deepcopy(prev[:-1])
        with self.assertRaises(ValueError):
            check_catalog_history(prev, curr)

    def test_history_rejects_appearance_change(self) -> None:
        prev = load_catalog(DEFAULT_CATALOG_PATH)
        curr = copy.deepcopy(prev)
        curr[0]["dial_color"] = "cream"
        with self.assertRaises(ValueError):
            check_catalog_history(prev, curr)

    def test_history_rejects_insert_below_max_id(self) -> None:
        prev = load_catalog(DEFAULT_CATALOG_PATH)
        prev_without_19 = [d for d in prev if d["device_id"] != "DMO-019"]
        with self.assertRaises(ValueError):
            check_catalog_history(prev_without_19, prev)

    def test_history_accepts_append(self) -> None:
        prev = load_catalog(DEFAULT_CATALOG_PATH)
        curr = copy.deepcopy(prev)
        extra = copy.deepcopy(prev[-1])
        extra["device_id"] = "DMO-021"
        extra["device_name"] = "予備熱交換器温度計"
        extra["bezel_color"] = "brass"
        curr.append(extra)
        check_catalog_history(prev, curr)

    def test_cli_main(self) -> None:
        self.assertEqual(main([]), 0)
        self.assertEqual(main(["--previous", str(DEFAULT_CATALOG_PATH)]), 0)


if __name__ == "__main__":
    unittest.main()
