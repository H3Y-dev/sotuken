"""tools/assign_device_ids.py のユニットテスト。

一時ディレクトリ内にモックデータを作成し、実際のデータやリポジトリの eval/ に依存せずに検証する。
"""

import csv
import json
from pathlib import Path
import shutil
import tempfile
import unittest

from tools.assign_device_ids import (
    SYNTHETIC_METER_ORDER,
    DIAL_COLOR_ORDER,
    build_synthetic_devices,
    build_corporate_devices,
    build_general_devices,
    main,
)


class TestAssignDeviceIds(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.base_path = Path(self.temp_dir)

        # モックの合成画像フォルダ
        self.synth_dir = self.base_path / "synthetic"
        self.synth_dir.mkdir(parents=True)

        # モックの企業提供画像フォルダ
        self.corp_dir = self.base_path / "corporate"
        self.corp_dir.mkdir(parents=True)
        (self.corp_dir / "気密試験_昇圧前.jpg").write_bytes(b"dummy")
        (self.corp_dir / "気密試験_昇圧後.jpg").write_bytes(b"dummy")
        (self.corp_dir / "耐圧試験_昇圧前.jpg").write_bytes(b"dummy")
        (self.corp_dir / "耐圧試験_昇圧後.jpg").write_bytes(b"dummy")

        # モックの一般画像フォルダ
        self.gen_dir = self.base_path / "general"
        self.gen_dir.mkdir(parents=True)
        (self.gen_dir / "20260817_134647.jpg").write_bytes(b"dummy")
        (self.gen_dir / "20260817_134656.jpg").write_bytes(b"dummy")
        (self.gen_dir / "20260817_134745.jpg").write_bytes(b"dummy")
        (self.gen_dir / "meter1.png").write_bytes(b"dummy")
        (self.gen_dir / "meter2.jpg").write_bytes(b"dummy")

        # モックの groundtruth_synthetic.json
        # 10種類 x 3色 = 30台の組み合わせをカバーするモックデータ
        self.mock_synth_items = [
            {
                "image": str(self.synth_dir / "p150_white_1.png"),
                "true_value": 10.0,
                "min_value": 0.0,
                "max_value": 150.0,
                "condition": {"meter_id": "pressure-150"},
                "appearance": {"dial_color": "white"},
            },
            {
                "image": str(self.synth_dir / "p150_white_2.png"),
                "true_value": 20.0,
                "min_value": 0.0,
                "max_value": 150.0,
                "condition": {"meter_id": "pressure-150"},
                "appearance": {"dial_color": "white"},
            },
            {
                "image": str(self.synth_dir / "p150_cream_1.png"),
                "true_value": 30.0,
                "min_value": 0.0,
                "max_value": 150.0,
                "condition": {"meter_id": "pressure-150"},
                "appearance": {"dial_color": "cream"},
            },
            {
                "image": str(self.synth_dir / "t100_black_1.png"),
                "true_value": 50.0,
                "min_value": 0.0,
                "max_value": 100.0,
                "condition": {"meter_id": "temperature-100"},
                "appearance": {"dial_color": "black"},
            },
        ]
        gt_file = self.synth_dir / "groundtruth_synthetic.json"
        with open(gt_file, "w", encoding="utf-8") as f:
            json.dump(self.mock_synth_items, f, ensure_ascii=False, indent=2)

        # サイドカーJSON
        for item in self.mock_synth_items:
            sc_path = Path(item["image"]).with_suffix(".json")
            with open(sc_path, "w", encoding="utf-8") as f:
                json.dump({"unit": "MPa" if "pressure" in item["condition"]["meter_id"] else "℃"}, f)

        # モックの eval/groundtruth.json
        self.mock_eval_gt = [
            {"image": "C:/dummy/気密試験_昇圧前.jpg", "true_value": 0.0},
            {"image": "C:/dummy/気密試験_昇圧後.jpg", "true_value": 100.0},
            {"image": "C:/dummy/耐圧試験_昇圧前.jpg", "true_value": 0.0},
            {"image": "C:/dummy/耐圧試験_昇圧後.jpg", "true_value": 200.0},
            {"image": "C:/dummy/general/20260817_134647.jpg", "true_value": 9.0},
            {"image": "images/meter1.png", "true_value": 21.0},
            {"image": "images/other_meter.jpg", "true_value": 5.0},  # 対象外
        ]
        self.eval_gt_file = self.base_path / "groundtruth.json"
        with open(self.eval_gt_file, "w", encoding="utf-8") as f:
            json.dump(self.mock_eval_gt, f, ensure_ascii=False, indent=2)

        self.devices_csv = self.base_path / "devices.csv"

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_build_synthetic_devices_determinism(self):
        """合成メーターの生成が決定的で、種類×文字盤色ごとに別ID、同種同色は同じIDになることを検証。"""
        devs1, map1 = build_synthetic_devices()
        devs2, map2 = build_synthetic_devices()

        self.assertEqual(len(devs1), 30)
        self.assertEqual(len(devs2), 30)
        self.assertEqual(devs1, devs2)
        self.assertEqual(map1, map2)

        # 全IDの一意性
        all_ids = [d["device_id"] for d in devs1]
        self.assertEqual(len(set(all_ids)), 30)
        self.assertEqual(all_ids[0], "SYN-001")
        self.assertEqual(all_ids[-1], "SYN-030")

        # 同じ種類・変種（色）は同じID
        key_p150_white = ("pressure-150", "white")
        key_p150_cream = ("pressure-150", "cream")
        self.assertEqual(map1[key_p150_white]["device_id"], "SYN-001")
        self.assertEqual(map1[key_p150_cream]["device_id"], "SYN-002")
        self.assertNotEqual(map1[key_p150_white]["device_id"], map1[key_p150_cream]["device_id"])

    def test_build_corporate_and_general_devices(self):
        """企業提供の2台および一般5台のID割り当てを検証。"""
        corp_devs, corp_map = build_corporate_devices(self.corp_dir)
        self.assertEqual(len(corp_devs), 2)
        self.assertEqual(corp_devs[0]["device_id"], "JSW-001")
        self.assertEqual(corp_devs[1]["device_id"], "JSW-002")

        # 気密試験前後は同じ JSW-001
        self.assertEqual(corp_map["気密試験_昇圧前.jpg"]["device_id"], "JSW-001")
        self.assertEqual(corp_map["気密試験_昇圧後.jpg"]["device_id"], "JSW-001")
        # 耐圧試験前後は同じ JSW-002
        self.assertEqual(corp_map["耐圧試験_昇圧前.jpg"]["device_id"], "JSW-002")
        self.assertEqual(corp_map["耐圧試験_昇圧後.jpg"]["device_id"], "JSW-002")

        gen_devs, gen_map = build_general_devices(self.gen_dir, self.eval_gt_file)
        self.assertEqual(len(gen_devs), 5)
        self.assertEqual(gen_devs[0]["device_id"], "GEN-001")
        self.assertEqual(gen_devs[-1]["device_id"], "GEN-005")
        self.assertIn("meter1.png", gen_map)

    def test_dry_run_does_not_modify(self):
        """--dry-run フラグでファイルが一切書き換わらないこと、バックアップも作られないことを検証。"""
        ret = main([
            "--synthetic-dir", str(self.synth_dir),
            "--corporate-dir", str(self.corp_dir),
            "--general-dir", str(self.gen_dir),
            "--devices-csv", str(self.devices_csv),
            "--groundtruth-real", str(self.eval_gt_file),
            "--dry-run",
        ])
        self.assertEqual(ret, 0)

        # devices.csv が作られていないこと
        self.assertFalse(self.devices_csv.exists())

        # バックアップが作られていないこと
        backup_file = self.synth_dir / "groundtruth_synthetic.before_ids.json"
        self.assertFalse(backup_file.exists())

        # groundtruth_synthetic.json が書き換わっていないこと
        with open(self.synth_dir / "groundtruth_synthetic.json", "r", encoding="utf-8") as f:
            data = json.load(f)
        self.assertNotIn("device_id", data[0])

    def test_execution_and_idempotence(self):
        """本番実行でバックアップ作成・ファイル書き換えが行われ、2回実行しても同じ結果になること（冪等性）を検証。"""
        args = [
            "--synthetic-dir", str(self.synth_dir),
            "--corporate-dir", str(self.corp_dir),
            "--general-dir", str(self.gen_dir),
            "--devices-csv", str(self.devices_csv),
            "--groundtruth-real", str(self.eval_gt_file),
        ]

        # 1回目の実行
        ret1 = main(args)
        self.assertEqual(ret1, 0)

        # バックアップの存在確認
        backup_file = self.synth_dir / "groundtruth_synthetic.before_ids.json"
        self.assertTrue(backup_file.exists())

        # devices.csv の確認 (UTF-8 BOM, 30+2+5=37行)
        self.assertTrue(self.devices_csv.exists())
        with open(self.devices_csv, "r", encoding="utf-8-sig") as f:
            rows = list(csv.DictReader(f))
        self.assertEqual(len(rows), 37)

        # groundtruth_synthetic.json の確認
        with open(self.synth_dir / "groundtruth_synthetic.json", "r", encoding="utf-8") as f:
            synth_data = json.load(f)
        self.assertEqual(synth_data[0]["device_id"], "SYN-001")
        self.assertEqual(synth_data[1]["device_id"], "SYN-001")  # 同じp150_white
        self.assertEqual(synth_data[2]["device_id"], "SYN-002")  # p150_cream
        self.assertEqual(synth_data[3]["device_id"], "SYN-024")  # t100_black

        # サイドカーの確認
        sc_path = Path(self.mock_synth_items[0]["image"]).with_suffix(".json")
        with open(sc_path, "r", encoding="utf-8") as f:
            sc_data = json.load(f)
        self.assertEqual(sc_data.get("device_id"), "SYN-001")

        # eval/groundtruth.json の確認
        with open(self.eval_gt_file, "r", encoding="utf-8") as f:
            eval_data = json.load(f)
        self.assertEqual(eval_data[0]["device_id"], "JSW-001")
        self.assertEqual(eval_data[1]["device_id"], "JSW-001")
        self.assertEqual(eval_data[2]["device_id"], "JSW-002")
        self.assertEqual(eval_data[3]["device_id"], "JSW-002")
        self.assertEqual(eval_data[4]["device_id"], "GEN-001")
        self.assertEqual(eval_data[5]["device_id"], "GEN-004")
        self.assertNotIn("device_id", eval_data[6])  # 対象外

        # 状態を保存
        csv_content1 = self.devices_csv.read_text(encoding="utf-8-sig")
        synth_json1 = (self.synth_dir / "groundtruth_synthetic.json").read_text(encoding="utf-8")
        eval_json1 = self.eval_gt_file.read_text(encoding="utf-8")

        # 2回目の実行 (冪等性確認)
        ret2 = main(args)
        self.assertEqual(ret2, 0)

        csv_content2 = self.devices_csv.read_text(encoding="utf-8-sig")
        synth_json2 = (self.synth_dir / "groundtruth_synthetic.json").read_text(encoding="utf-8")
        eval_json2 = self.eval_gt_file.read_text(encoding="utf-8")

        self.assertEqual(csv_content1, csv_content2)
        self.assertEqual(synth_json1, synth_json2)
        self.assertEqual(eval_json1, eval_json2)


if __name__ == "__main__":
    unittest.main()
