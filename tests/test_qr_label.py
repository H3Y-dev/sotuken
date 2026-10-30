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
from tools.make_qr_labels import load_device_names


class TestQRLabelCommonCases(unittest.TestCase):
    """仕様書 (QR機器ラベル仕様.md) に記載されている共通テストケースの検証。"""

    def test_case_valid_simple(self):
        # {"v":1,"name":"ボイラー圧力計A-101"} -> name = "ボイラー圧力計A-101"
        payload = '{"v":1,"name":"ボイラー圧力計A-101"}'
        result = parse_payload(payload)
        self.assertEqual(result, {"name": "ボイラー圧力計A-101"})

    def test_case_valid_with_unit_and_extra(self):
        # {"v":1,"name":"  P-1  ","unit":"MPa","extra":1} -> name = "P-1"、unit = "MPa"、extraは無視
        payload = '{"v":1,"name":"  P-1  ","unit":"MPa","extra":1}'
        result = parse_payload(payload)
        self.assertEqual(result, {"name": "P-1", "unit": "MPa"})

    def test_case_invalid_version(self):
        # {"v":2,"name":"P-1"} -> 機器QRではない (None)
        payload = '{"v":2,"name":"P-1"}'
        self.assertIsNone(parse_payload(payload))

    def test_case_invalid_missing_or_empty_name(self):
        # {"v":1} / {"v":1,"name":""} -> 機器QRではない (None)
        self.assertIsNone(parse_payload('{"v":1}'))
        self.assertIsNone(parse_payload('{"v":1,"name":""}'))
        self.assertIsNone(parse_payload('{"v":1,"name":"   "}'))

    def test_case_invalid_not_json(self):
        # P-1（JSONでない文字列） -> 機器QRではない (None)
        self.assertIsNone(parse_payload("P-1"))
        self.assertIsNone(parse_payload("{invalid json"))

    def test_case_invalid_name_too_long(self):
        # name が65文字以上 -> 機器QRではない (None)
        long_name_65 = "A" * 65
        payload = f'{{"v":1,"name":"{long_name_65}"}}'
        self.assertIsNone(parse_payload(payload))


class TestQRLabelBuildPayload(unittest.TestCase):
    """build_payload の詳細なテスト。"""

    def test_build_payload_basic(self):
        payload = build_payload("ボイラー圧力計A-101")
        self.assertEqual(payload, '{"v":1,"name":"ボイラー圧力計A-101"}')

    def test_build_payload_strip_whitespace(self):
        payload = build_payload("  P-1  ")
        self.assertEqual(payload, '{"v":1,"name":"P-1"}')

    def test_build_payload_all_fields_order(self):
        payload = build_payload("P-1", unit="MPa", min=0.0, max=10.0)
        # キー順序は v, name, unit, min, max
        self.assertEqual(payload, '{"v":1,"name":"P-1","unit":"MPa","min":0.0,"max":10.0}')

    def test_build_payload_invalid_empty(self):
        with self.assertRaises(ValueError):
            build_payload("")
        with self.assertRaises(ValueError):
            build_payload("   ")

    def test_build_payload_invalid_length(self):
        # 64文字はOK、65文字はValueError
        build_payload("A" * 64)
        with self.assertRaises(ValueError):
            build_payload("A" * 65)

    def test_build_payload_invalid_control_characters(self):
        with self.assertRaises(ValueError):
            build_payload("P-1\n")
        with self.assertRaises(ValueError):
            build_payload("P\t1")
        with self.assertRaises(ValueError):
            build_payload("P\x001")


class TestQRLabelRoundTrip(unittest.TestCase):
    """build_payload と parse_payload の往復テスト。"""

    def test_round_trip_simple(self):
        original_name = "受水槽圧力計 No.3"
        payload = build_payload(original_name)
        parsed = parse_payload(payload)
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed["name"], original_name)

    def test_round_trip_full(self):
        payload = build_payload("冷却水ポンプ圧力", unit="kPa", min=-100, max=500)
        parsed = parse_payload(payload)
        self.assertIsNotNone(parsed)
        self.assertEqual(
            parsed,
            {"name": "冷却水ポンプ圧力", "unit": "kPa", "min": -100, "max": 500},
        )


class TestQRLabelSheetPDF(unittest.TestCase):
    """make_label_sheet によるPDF生成のテスト。"""

    def test_make_label_sheet_11_devices_creates_2_pages(self):
        # 11台で2ページのPDFを作る
        devices = [f"機器-{i:02d}" for i in range(1, 12)]
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
        devices = [f"機器-{i:02d}" for i in range(1, 11)]
        with tempfile.TemporaryDirectory() as tmpdir:
            out_pdf = Path(tmpdir) / "test_labels_10.pdf"
            make_label_sheet(devices, out_pdf)

            self.assertTrue(out_pdf.exists())
            pdf_data = out_pdf.read_bytes()
            pages = re.findall(rb"/Type\s*/Page\b", pdf_data)
            self.assertEqual(len(pages), 1)

    def test_create_label_image(self):
        img = create_label_image("テスト機器A")
        self.assertEqual(img.size, (1100, 636))


class TestMakeQRLabelsTool(unittest.TestCase):
    """tools/make_qr_labels.py のファイル読み込み・重複・空行等のテスト。"""

    def test_load_text_file_with_empty_lines_and_duplicates(self):
        content = (
            "機器A\n"
            "\n"
            "  機器B  \n"
            "機器A\n"  # 重複
            "\n"
            "機器C\n"
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            txt_path = Path(tmpdir) / "list.txt"
            txt_path.write_text(content, encoding="utf-8")

            names = load_device_names(txt_path)
            self.assertEqual(names, ["機器A", "機器B", "機器C"])

    def test_load_csv_file_with_header_and_bom(self):
        content = (
            "機器名,備考\n"  # ヘッダー行
            "機器-01,1Fボイラー室\n"
            "\n"
            "機器-02,2F機械室\n"
            "機器-01,重複\n"
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            csv_path = Path(tmpdir) / "list.csv"
            csv_path.write_text(content, encoding="utf-8-sig")

            names = load_device_names(csv_path)
            self.assertEqual(names, ["機器-01", "機器-02"])

    def test_load_file_with_invalid_name_raises_value_error(self):
        content = (
            "機器1\n"
            + ("X" * 65) + "\n"  # 2行目が65文字で不正
            + "機器3\n"
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            txt_path = Path(tmpdir) / "list_bad.txt"
            txt_path.write_text(content, encoding="utf-8")

            with self.assertRaises(ValueError) as ctx:
                load_device_names(txt_path)
            self.assertIn("2行目", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
