"""QR機器ラベルモジュール (manager/qr_label.py) およびツール (tools/make_qr_labels.py) のテスト。"""

import os
from pathlib import Path
import re
import tempfile
import unittest

from manager.qr_label import (
    build_payload,
    create_label_image,
    make_label_sheet,
    parse_payload,
)
from tools.make_qr_labels import load_devices, load_device_names


class TestQRLabelCommonCases(unittest.TestCase):
    """仕様書 (QR機器ラベル仕様.md) に記載されている共通テストケースの検証。"""

    def test_case_valid_simple(self):
        # {"v":1,"id":"A-101","name":"ボイラー圧力計"} -> id = "A-101", name = "ボイラー圧力計"
        payload = '{"v":1,"id":"A-101","name":"ボイラー圧力計"}'
        result = parse_payload(payload)
        self.assertEqual(result, {"id": "A-101", "name": "ボイラー圧力計"})

    def test_case_valid_with_unit_and_extra(self):
        # {"v":1,"id":"P.1_a-b","name":"  P-1  ","unit":"MPa","extra":1} -> id = "P.1_a-b", name = "P-1", unit = "MPa", extraは無視
        payload = '{"v":1,"id":"P.1_a-b","name":"  P-1  ","unit":"MPa","extra":1}'
        result = parse_payload(payload)
        self.assertEqual(result, {"id": "P.1_a-b", "name": "P-1", "unit": "MPa"})

    def test_case_invalid_version(self):
        # {"v":2,"id":"A-101","name":"P-1"} -> 機器QRではない (None)
        payload = '{"v":2,"id":"A-101","name":"P-1"}'
        self.assertIsNone(parse_payload(payload))

    def test_case_invalid_legacy_format_without_id(self):
        # {"v":1,"name":"ボイラー圧力計A-101"} -> 機器QRではない (idが無い旧形式)
        payload = '{"v":1,"name":"ボイラー圧力計A-101"}'
        self.assertIsNone(parse_payload(payload))

    def test_case_invalid_missing_name(self):
        # {"v":1,"id":"A-101"} -> 機器QRではない (nameが無い)
        payload = '{"v":1,"id":"A-101"}'
        self.assertIsNone(parse_payload(payload))

    def test_case_invalid_empty_id(self):
        # {"v":1,"id":"","name":"P-1"} -> 機器QRではない (idが空)
        payload = '{"v":1,"id":"","name":"P-1"}'
        self.assertIsNone(parse_payload(payload))

    def test_case_invalid_japanese_id(self):
        # {"v":1,"id":"圧力計1","name":"P-1"} -> 機器QRではない (idに日本語)
        payload = '{"v":1,"id":"圧力計1","name":"P-1"}'
        self.assertIsNone(parse_payload(payload))

    def test_case_invalid_id_too_long(self):
        # {"v":1,"id":"A"*33,"name":"P-1"} -> 機器QRではない (idが33文字以上)
        payload = f'{{"v":1,"id":"{"A" * 33}","name":"P-1"}}'
        self.assertIsNone(parse_payload(payload))

    def test_case_invalid_id_with_space(self):
        # {"v":1,"id":"A 101","name":"P-1"} -> 機器QRではない (idに空白)
        payload = '{"v":1,"id":"A 101","name":"P-1"}'
        self.assertIsNone(parse_payload(payload))

    def test_case_invalid_empty_name(self):
        # {"v":1,"id":"A-101","name":""} -> 機器QRではない (nameが空)
        self.assertIsNone(parse_payload('{"v":1,"id":"A-101","name":""}'))
        self.assertIsNone(parse_payload('{"v":1,"id":"A-101","name":"   "}'))

    def test_case_invalid_name_too_long(self):
        # name が65文字以上 -> 機器QRではない (None)
        payload = f'{{"v":1,"id":"A-101","name":"{"A" * 65}"}}'
        self.assertIsNone(parse_payload(payload))

    def test_case_invalid_not_json(self):
        # P-1（JSONでない文字列） -> 機器QRではない (None)
        self.assertIsNone(parse_payload("P-1"))
        self.assertIsNone(parse_payload("{invalid json"))


class TestQRLabelBuildPayload(unittest.TestCase):
    """build_payload の詳細なテスト。"""

    def test_build_payload_basic(self):
        payload = build_payload("A-101", "ボイラー圧力計A-101")
        self.assertEqual(payload, '{"v":1,"id":"A-101","name":"ボイラー圧力計A-101"}')

    def test_build_payload_strip_whitespace_name(self):
        payload = build_payload("P-1", "  ボイラー  ")
        self.assertEqual(payload, '{"v":1,"id":"P-1","name":"ボイラー"}')

    def test_build_payload_all_fields_order(self):
        payload = build_payload("A-1", "名前", unit="MPa", min=0.0, max=10.0)
        # キー順序は v, id, name, unit, min, max
        self.assertEqual(
            payload,
            '{"v":1,"id":"A-1","name":"名前","unit":"MPa","min":0.0,"max":10.0}',
        )

    def test_build_payload_invalid_id(self):
        # 空文字
        with self.assertRaises(ValueError):
            build_payload("", "機器")
        # 33文字（上限32文字）
        with self.assertRaises(ValueError):
            build_payload("A" * 33, "機器")
        # 32文字はOK
        build_payload("A" * 32, "機器")
        # 日本語
        with self.assertRaises(ValueError):
            build_payload("機器01", "機器")
        # 空白入り
        with self.assertRaises(ValueError):
            build_payload("A 101", "機器")
        # 許可文字以外（記号）
        with self.assertRaises(ValueError):
            build_payload("A@101", "機器")
        with self.assertRaises(ValueError):
            build_payload("A/101", "機器")
        # 文字列型以外
        with self.assertRaises(ValueError):
            build_payload(101, "機器")  # type: ignore

    def test_build_payload_invalid_name(self):
        with self.assertRaises(ValueError):
            build_payload("A-1", "")
        with self.assertRaises(ValueError):
            build_payload("A-1", "   ")
        # 64文字はOK、65文字はValueError
        build_payload("A-1", "A" * 64)
        with self.assertRaises(ValueError):
            build_payload("A-1", "A" * 65)
        # 制御文字
        with self.assertRaises(ValueError):
            build_payload("A-1", "P-1\n")
        with self.assertRaises(ValueError):
            build_payload("A-1", "P\t1")
        with self.assertRaises(ValueError):
            build_payload("A-1", "P\x001")
        # 文字列型以外
        with self.assertRaises(ValueError):
            build_payload("A-1", None)  # type: ignore

    def test_build_payload_invalid_unit_min_max(self):
        with self.assertRaises(ValueError):
            build_payload("A-1", "機器", unit=123)  # type: ignore
        with self.assertRaises(ValueError):
            build_payload("A-1", "機器", min="0")  # type: ignore
        with self.assertRaises(ValueError):
            build_payload("A-1", "機器", min=True)  # type: ignore
        with self.assertRaises(ValueError):
            build_payload("A-1", "機器", max=False)  # type: ignore


class TestQRLabelRoundTrip(unittest.TestCase):
    """build_payload と parse_payload の往復テスト。"""

    def test_round_trip_simple(self):
        dev_id = "A-101"
        dev_name = "受水槽圧力計 No.3"
        payload = build_payload(dev_id, dev_name)
        parsed = parse_payload(payload)
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed["id"], dev_id)
        self.assertEqual(parsed["name"], dev_name)

    def test_round_trip_full(self):
        dev_id = "SYN.01_x"
        dev_name = "冷却水ポンプ圧力"
        payload = build_payload(dev_id, dev_name, unit="kPa", min=-100, max=500)
        parsed = parse_payload(payload)
        self.assertIsNotNone(parsed)
        self.assertEqual(
            parsed,
            {
                "id": dev_id,
                "name": dev_name,
                "unit": "kPa",
                "min": -100,
                "max": 500,
            },
        )


class TestQRLabelSheetPDF(unittest.TestCase):
    """make_label_sheet によるPDF生成および create_label_image のテスト。"""

    def test_make_label_sheet_11_devices_creates_2_pages(self):
        # 11台で2ページのPDFを作る
        devices = [(f"DEV-{i:02d}", f"機器-{i:02d}") for i in range(1, 12)]
        with tempfile.TemporaryDirectory() as tmpdir:
            out_pdf = Path(tmpdir) / "test_labels.pdf"
            make_label_sheet(devices, out_pdf)

            self.assertTrue(out_pdf.exists())
            self.assertGreater(out_pdf.stat().st_size, 0)

            # PDF内のページ数を確認 (/Type /Page)
            pdf_data = out_pdf.read_bytes()
            pages = re.findall(rb"/Type\s*/Page\b", pdf_data)
            self.assertEqual(len(pages), 2)

    def test_make_label_sheet_10_devices_creates_1_page(self):
        # 10台でちょうど1ページのPDFを作る
        devices = [(f"DEV-{i:02d}", f"機器-{i:02d}") for i in range(1, 11)]
        with tempfile.TemporaryDirectory() as tmpdir:
            out_pdf = Path(tmpdir) / "test_labels_10.pdf"
            make_label_sheet(devices, out_pdf)

            self.assertTrue(out_pdf.exists())
            pdf_data = out_pdf.read_bytes()
            pages = re.findall(rb"/Type\s*/Page\b", pdf_data)
            self.assertEqual(len(pages), 1)

    def test_create_label_image(self):
        img = create_label_image("DEV-01", "テスト機器A")
        self.assertEqual(img.size, (1100, 636))

        # タプル引数でも動作することを確認
        img2 = create_label_image(("DEV-02", "テスト機器B"))
        self.assertEqual(img2.size, (1100, 636))


class TestMakeQRLabelsTool(unittest.TestCase):
    """tools/make_qr_labels.py のCSV読み込み・ヘッダー・BOM・ID重複・不正行のテスト。"""

    def test_load_csv_with_header(self):
        content = (
            "機器ID,機器名\n"
            "A-101,ボイラー圧力計\n"
            "P-02,給水ポンプ\n"
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            csv_path = Path(tmpdir) / "list.csv"
            csv_path.write_text(content, encoding="utf-8")

            devices = load_devices(csv_path)
            self.assertEqual(
                devices,
                [("A-101", "ボイラー圧力計"), ("P-02", "給水ポンプ")],
            )

    def test_load_csv_without_header(self):
        content = (
            "A-101,ボイラー圧力計\n"
            "P-02,給水ポンプ\n"
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            csv_path = Path(tmpdir) / "list_no_header.csv"
            csv_path.write_text(content, encoding="utf-8")

            devices = load_devices(csv_path)
            self.assertEqual(
                devices,
                [("A-101", "ボイラー圧力計"), ("P-02", "給水ポンプ")],
            )

    def test_load_csv_with_bom_and_empty_lines(self):
        content = (
            "機器ID,機器名\n"
            "\n"
            "A-101,ボイラー圧力計\n"
            "\n"
            "P-02,給水ポンプ\n"
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            csv_path = Path(tmpdir) / "list_bom.csv"
            csv_path.write_text(content, encoding="utf-8-sig")

            devices = load_devices(csv_path)
            self.assertEqual(
                devices,
                [("A-101", "ボイラー圧力計"), ("P-02", "給水ポンプ")],
            )

    def test_load_csv_allow_duplicate_names(self):
        # 機器IDが異なれば、機器名の重複は許容される
        content = (
            "機器ID,機器名\n"
            "A-101,ボイラー圧力計\n"
            "A-102,ボイラー圧力計\n"
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            csv_path = Path(tmpdir) / "list_dup_names.csv"
            csv_path.write_text(content, encoding="utf-8")

            devices = load_devices(csv_path)
            self.assertEqual(
                devices,
                [("A-101", "ボイラー圧力計"), ("A-102", "ボイラー圧力計")],
            )

    def test_load_csv_duplicate_id_raises_value_error(self):
        content = (
            "機器ID,機器名\n"
            "A-101,ボイラー1\n"
            "A-102,ボイラー2\n"
            "A-101,ボイラー3\n"  # 4行目で重複
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            csv_path = Path(tmpdir) / "list_dup_id.csv"
            csv_path.write_text(content, encoding="utf-8")

            with self.assertRaises(ValueError) as ctx:
                load_devices(csv_path)
            msg = str(ctx.exception)
            self.assertIn("4行目", msg)
            self.assertIn("A-101", msg)

    def test_load_csv_insufficient_columns_raises_value_error(self):
        content = (
            "機器ID,機器名\n"
            "A-101\n"  # 2行目が1列しかない
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            csv_path = Path(tmpdir) / "list_short.csv"
            csv_path.write_text(content, encoding="utf-8")

            with self.assertRaises(ValueError) as ctx:
                load_devices(csv_path)
            self.assertIn("2行目", str(ctx.exception))

    def test_load_csv_invalid_id_raises_value_error(self):
        content = (
            "機器ID,機器名\n"
            "A 101,ボイラー\n"  # 2行目のIDに空白
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            csv_path = Path(tmpdir) / "list_bad_id.csv"
            csv_path.write_text(content, encoding="utf-8")

            with self.assertRaises(ValueError) as ctx:
                load_devices(csv_path)
            self.assertIn("2行目", str(ctx.exception))

    def test_load_csv_invalid_name_raises_value_error(self):
        content = (
            "機器ID,機器名\n"
            "A-101,\n"  # 2行目の名前が空
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            csv_path = Path(tmpdir) / "list_empty_name.csv"
            csv_path.write_text(content, encoding="utf-8")

            with self.assertRaises(ValueError) as ctx:
                load_devices(csv_path)
            self.assertIn("2行目", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
