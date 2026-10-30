"""manager/qr_decode.py の単体テスト。"""

from __future__ import annotations

import os
from pathlib import Path
import tempfile
import unittest

import cv2
import numpy as np
import qrcode
import qrcode.constants

from manager.qr_decode import QrResult, issue_for, read_device_qr
from manager.qr_label import build_payload


def _make_qr_image(payload: str, box_size: int = 10, border: int = 4) -> np.ndarray:
    """テスト用のQRコード画像を生成してBGRのndarrayで返す。"""
    qr = qrcode.QRCode(
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=box_size,
        border=border,
    )
    qr.add_data(payload)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white").convert("RGB")
    rgb = np.array(img)
    return cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)


class TestQrDecode(unittest.TestCase):
    """read_device_qr および issue_for の動作検証。"""

    def test_case_a_single_device_qr(self):
        """(a) 機器QR1つの画像 -> found"""
        payload = build_payload("DEV-001", "ボイラー圧力計")
        img = _make_qr_image(payload)

        result = read_device_qr(img)
        self.assertEqual(result.status, "found")
        self.assertEqual(result.device_id, "DEV-001")
        self.assertEqual(result.device_name, "ボイラー圧力計")
        self.assertIn(payload, result.payloads)
        self.assertIsNotNone(result.method)

    def test_case_b_two_device_qrs_different_id(self):
        """(b) 機器QR2つ（異なるid）-> multiple"""
        p1 = build_payload("DEV-001", "圧力計1")
        p2 = build_payload("DEV-002", "圧力計2")
        qr1 = _make_qr_image(p1, box_size=8)
        qr2 = _make_qr_image(p2, box_size=8)

        # 2つのQRを同一キャンバスに並べる
        h = max(qr1.shape[0], qr2.shape[0]) + 40
        w = qr1.shape[1] + qr2.shape[1] + 80
        canvas = np.full((h, w, 3), 255, dtype=np.uint8)
        canvas[20 : 20 + qr1.shape[0], 20 : 20 + qr1.shape[1]] = qr1
        canvas[20 : 20 + qr2.shape[0], qr1.shape[1] + 40 : qr1.shape[1] + 40 + qr2.shape[1]] = qr2

        result = read_device_qr(canvas)
        self.assertEqual(result.status, "multiple")
        self.assertIsNone(result.device_id)
        self.assertIsNone(result.device_name)
        self.assertGreaterEqual(len(result.payloads), 2)
        self.assertIn(p1, result.payloads)
        self.assertIn(p2, result.payloads)

    def test_case_c_two_device_qrs_same_id(self):
        """(c) 同じidのQR2つ -> found"""
        p1 = build_payload("DEV-001", "ボイラー計器")
        qr1 = _make_qr_image(p1, box_size=8)
        qr2 = _make_qr_image(p1, box_size=8)

        h = max(qr1.shape[0], qr2.shape[0]) + 40
        w = qr1.shape[1] + qr2.shape[1] + 80
        canvas = np.full((h, w, 3), 255, dtype=np.uint8)
        canvas[20 : 20 + qr1.shape[0], 20 : 20 + qr1.shape[1]] = qr1
        canvas[20 : 20 + qr2.shape[0], qr1.shape[1] + 40 : qr1.shape[1] + 40 + qr2.shape[1]] = qr2

        result = read_device_qr(canvas)
        self.assertEqual(result.status, "found")
        self.assertEqual(result.device_id, "DEV-001")
        self.assertEqual(result.device_name, "ボイラー計器")

    def test_case_d_ordinary_non_device_qr(self):
        """(d) 機器QRでない普通のQR -> not_device"""
        p = "https://example.com/meter-manual"
        img = _make_qr_image(p)

        result = read_device_qr(img)
        self.assertEqual(result.status, "not_device")
        self.assertIsNone(result.device_id)
        self.assertIsNone(result.device_name)
        self.assertIn(p, result.payloads)
        self.assertIsNotNone(result.method)

    def test_case_e_device_and_non_device_qr_mixed(self):
        """(e) 機器QR＋非機器QR -> found（非機器QRは無視される）"""
        p_dev = build_payload("DEV-001", "混合計器")
        p_other = "https://example.com/spec"
        qr_dev = _make_qr_image(p_dev, box_size=8)
        qr_other = _make_qr_image(p_other, box_size=8)

        h = max(qr_dev.shape[0], qr_other.shape[0]) + 40
        w = qr_dev.shape[1] + qr_other.shape[1] + 80
        canvas = np.full((h, w, 3), 255, dtype=np.uint8)
        canvas[20 : 20 + qr_dev.shape[0], 20 : 20 + qr_dev.shape[1]] = qr_dev
        canvas[20 : 20 + qr_other.shape[0], qr_dev.shape[1] + 40 : qr_dev.shape[1] + 40 + qr_other.shape[1]] = qr_other

        result = read_device_qr(canvas)
        self.assertEqual(result.status, "found")
        self.assertEqual(result.device_id, "DEV-001")
        self.assertEqual(result.device_name, "混合計器")

    def test_case_f_no_qr(self):
        """(f) QRなし -> not_found"""
        blank = np.full((400, 400, 3), 255, dtype=np.uint8)
        result = read_device_qr(blank)
        self.assertEqual(result.status, "not_found")
        self.assertIsNone(result.device_id)
        self.assertIsNone(result.device_name)
        self.assertEqual(result.payloads, [])
        self.assertIsNone(result.method)

    def test_case_g_broken_or_missing_file(self):
        """(g) 壊れた画像・存在しないパス -> not_found（例外なし）"""
        # 存在しないパス
        result = read_device_qr("C:/path/to/definitely_non_existent_file_98765.png")
        self.assertEqual(result.status, "not_found")
        self.assertIsNone(result.device_id)
        self.assertEqual(result.payloads, [])

        # 壊れた画像ファイル（テキストファイル）
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            f.write(b"NOT_A_VALID_IMAGE_DATA")
            corrupt_path = f.name
        try:
            result = read_device_qr(corrupt_path)
            self.assertEqual(result.status, "not_found")
            self.assertIsNone(result.device_id)
        finally:
            if os.path.exists(corrupt_path):
                os.unlink(corrupt_path)

        # 0バイトファイル
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            empty_path = f.name
        try:
            result = read_device_qr(empty_path)
            self.assertEqual(result.status, "not_found")
        finally:
            if os.path.exists(empty_path):
                os.unlink(empty_path)

        # 不正な入力型
        self.assertEqual(read_device_qr(None).status, "not_found")
        self.assertEqual(read_device_qr(12345).status, "not_found")
        self.assertEqual(read_device_qr(np.array([])).status, "not_found")
        self.assertEqual(read_device_qr(np.zeros((0, 0, 3))).status, "not_found")

    def test_case_h_japanese_path(self):
        """(h) 日本語パスの画像が読める"""
        payload = build_payload("JP-PATH-001", "日本語パス圧力計")
        img = _make_qr_image(payload)

        temp_dir = Path(tempfile.gettempdir()) / "卒研_QRテスト_日本語フォルダ"
        temp_dir.mkdir(parents=True, exist_ok=True)
        test_file = temp_dir / "点検機器_ラベル.png"

        # 日本語パスに保存
        is_success, encoded_img = cv2.imencode(".png", img)
        self.assertTrue(is_success)
        encoded_img.tofile(str(test_file))

        try:
            result = read_device_qr(test_file)
            self.assertEqual(result.status, "found")
            self.assertEqual(result.device_id, "JP-PATH-001")
            self.assertEqual(result.device_name, "日本語パス圧力計")
        finally:
            if test_file.exists():
                test_file.unlink()
            if temp_dir.exists():
                temp_dir.rmdir()

    def test_case_i_bottom_right_small_qr(self):
        """(i) 右下の隅に小さく貼ったQR（200px板を1280×960の画像の右下）が読める"""
        payload = build_payload("DEV-CORNER", "右下コーナー計器")
        qr_img = _make_qr_image(payload, box_size=5)
        # 200px角にリサイズ
        qr_200 = cv2.resize(qr_img, (200, 200), interpolation=cv2.INTER_AREA)

        # 1280x960の画像キャンバス
        canvas = np.full((960, 1280, 3), 200, dtype=np.uint8)
        # 右下隅（余白24px）に配置
        y1, y2 = 960 - 24 - 200, 960 - 24
        x1, x2 = 1280 - 24 - 200, 1280 - 24
        canvas[y1:y2, x1:x2] = qr_200

        result = read_device_qr(canvas)
        self.assertEqual(result.status, "found")
        self.assertEqual(result.device_id, "DEV-CORNER")
        self.assertEqual(result.device_name, "右下コーナー計器")

    def test_corner_cases_top_right_and_left(self):
        """四隅（右上・左上・左下）に配置したQRも検出できる"""
        payload = build_payload("DEV-CORNER-TL", "左上計器")
        qr_img = _make_qr_image(payload, box_size=5)
        qr_200 = cv2.resize(qr_img, (200, 200), interpolation=cv2.INTER_AREA)

        # 左上隅（余白24px）
        canvas = np.full((960, 1280, 3), 200, dtype=np.uint8)
        canvas[24:224, 24:224] = qr_200

        result = read_device_qr(canvas)
        self.assertEqual(result.status, "found")
        self.assertEqual(result.device_id, "DEV-CORNER-TL")

    def test_case_j_issue_for(self):
        """(j) issue_for の対応検証"""
        self.assertIsNone(issue_for(QrResult(status="found")))
        self.assertEqual(issue_for(QrResult(status="not_found")), "qr_not_found")
        self.assertEqual(issue_for(QrResult(status="not_device")), "qr_not_device")
        self.assertEqual(issue_for(QrResult(status="multiple")), "qr_multiple")

        # 文字列直接渡し
        self.assertIsNone(issue_for("found"))
        self.assertEqual(issue_for("not_found"), "qr_not_found")
        self.assertEqual(issue_for("not_device"), "qr_not_device")
        self.assertEqual(issue_for("multiple"), "qr_multiple")

        # 未知のステータスは安全に qr_not_found
        self.assertEqual(issue_for("unknown"), "qr_not_found")


if __name__ == "__main__":
    unittest.main()
