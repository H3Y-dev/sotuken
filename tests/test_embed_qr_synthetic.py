"""tests/test_embed_qr_synthetic.py

3D合成画像へのQR板合成ツール（tools/embed_qr_into_synthetic.py）の単体・結合テスト。
実際の合成画像データセットやリポジトリの eval/ に依存せず、一時ディレクトリ内のモックデータで完結する。
"""

from datetime import datetime, timedelta, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import tempfile
import unittest

import cv2
import numpy as np

from manager.qr_label import parse_payload
from tools.embed_qr_into_synthetic import (
    METER_CENTER,
    METER_RADIUS_WITH_SHADOW,
    apply_qr_degradations,
    calculate_captured_at,
    create_qr_plate,
    embed_plate_in_image,
    evaluate_qr_read_rates,
    process_dataset,
    save_image_unicode_safe,
)


class TestEmbedQrSynthetic(unittest.TestCase):
    def setUp(self):
        self.device_id = "SYN-001"
        self.device_name = "合成 圧力計0-150 白"
        self.canvas_w = 1280
        self.canvas_h = 960

    def test_qr_placement_no_overlap_with_meter(self):
        """1. 貼る位置が画像枠内に収まり、メーター範囲（半径約450px）と重ならないことを検証。"""
        plate_pil = create_qr_plate(self.device_id, self.device_name)
        plate_bgr = cv2.cvtColor(np.array(plate_pil), cv2.COLOR_RGB2BGR)

        # 正対および複数の傾き角度（yaw: 0, 15, 30, 45, 60 / pitch: 0, 25）で検証
        test_angles = [
            (0.0, 0.0),
            (15.0, 0.0),
            (30.0, 0.0),
            (45.0, 0.0),
            (60.0, 0.0),
            (0.0, 25.0),
        ]

        for yaw, pitch in test_angles:
            base_canvas = np.full((self.canvas_h, self.canvas_w, 3), 128, dtype=np.uint8)
            composite, bbox, _ = embed_plate_in_image(
                base_canvas, plate_bgr, yaw_deg=yaw, pitch_deg=pitch, margin=24
            )

            x, y, w, h = bbox
            # A. 画像境界内に収まっているか
            self.assertGreaterEqual(x, 0, f"x < 0 at yaw={yaw}, pitch={pitch}")
            self.assertGreaterEqual(y, 0, f"y < 0 at yaw={yaw}, pitch={pitch}")
            self.assertLessEqual(x + w, self.canvas_w, f"x+w > canvas_w at yaw={yaw}, pitch={pitch}")
            self.assertLessEqual(y + h, self.canvas_h, f"y+h > canvas_h at yaw={yaw}, pitch={pitch}")

            # B. メーター中心 (640, 480) からの最短距離が 450px より大きいか
            cx, cy = METER_CENTER
            # bboxの4隅で最短距離を判定
            corners = [
                (x, y),
                (x + w, y),
                (x, y + h),
                (x + w, y + h),
            ]
            min_dist = min(math.hypot(px - cx, py - cy) for px, py in corners)
            self.assertGreater(
                min_dist,
                METER_RADIUS_WITH_SHADOW,
                f"Overlap detected with meter shadow: min_dist={min_dist:.1f} <= {METER_RADIUS_WITH_SHADOW} at yaw={yaw}, pitch={pitch}",
            )

    def test_clean_qr_readable(self):
        """2. 劣化なし（正面）のQR板が正しく読み取れ、device_id が一致することを検証。"""
        plate_pil = create_qr_plate(self.device_id, self.device_name)
        plate_bgr = cv2.cvtColor(np.array(plate_pil), cv2.COLOR_RGB2BGR)

        base_canvas = np.full((self.canvas_h, self.canvas_w, 3), 220, dtype=np.uint8)
        composite, _, degraded = embed_plate_in_image(
            base_canvas, plate_bgr, yaw_deg=0.0, pitch_deg=0.0
        )
        self.assertEqual(degraded, [])

        detector = cv2.QRCodeDetector()
        val, _, _ = detector.detectAndDecode(composite)
        self.assertTrue(bool(val), "Clean QR should be detected by QRCodeDetector")

        parsed = parse_payload(val)
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed["id"], self.device_id)
        self.assertEqual(parsed["name"], self.device_name)

    def test_motion_blur_difficulty_and_degraded_list(self):
        """3. ブレをかけると読み取りの難度が上がり、かけた劣化がリストに残ることを検証。"""
        plate_pil = create_qr_plate(self.device_id, self.device_name)
        plate_bgr = cv2.cvtColor(np.array(plate_pil), cv2.COLOR_RGB2BGR)

        # ブラーなしでの基準読み取り
        detector = cv2.QRCodeDetector()
        val_clean, _, _ = detector.detectAndDecode(plate_bgr)
        self.assertTrue(bool(val_clean), "Raw plate should be decoded")

        # 25pxの水平モーションブラー適用
        cond = {"blur": "motion25", "target_blur_width": 25}
        blurred_plate, applied = apply_qr_degradations(plate_bgr, cond, {})

        # かけた劣化がリストに残っているか
        self.assertIn("motion_blur_25px", applied)

        # 画像に埋め込み
        base_canvas = np.full((self.canvas_h, self.canvas_w, 3), 200, dtype=np.uint8)
        composite, _, extra = embed_plate_in_image(base_canvas, blurred_plate, yaw_deg=0.0, pitch_deg=0.0)
        total_applied = applied + extra
        self.assertIn("motion_blur_25px", total_applied)

        # ブラーによる読み取り難化（未検出または復号不能）の確認
        val_blurred, _, _ = detector.detectAndDecode(composite)
        self.assertFalse(
            bool(val_blurred),
            "Heavy motion blur (25px) should increase difficulty and fail OpenCV standard detector",
        )

    def test_captured_at_determinism(self):
        """4. captured_at の決定性と規則（1日進行、機器番号×3分オフセット）を検証。"""
        # A. 同一入力に対する決定性
        t1 = calculate_captured_at("SYN-001", 0)
        t2 = calculate_captured_at("SYN-001", 0)
        self.assertEqual(t1, t2)

        # B. 機器番号による3分オフセット
        # SYN-001 -> 1 * 3 = 3分 (09:03:00)
        # SYN-002 -> 2 * 3 = 6分 (09:06:00)
        self.assertEqual(t1, "2026-10-01T09:03:00+09:00")
        t_dev2 = calculate_captured_at("SYN-002", 0)
        self.assertEqual(t_dev2, "2026-10-01T09:06:00+09:00")

        # C. 画像インデックスによる1日進行
        t_dev1_img1 = calculate_captured_at("SYN-001", 1)
        self.assertEqual(t_dev1_img1, "2026-10-02T09:03:00+09:00")
        t_dev1_img2 = calculate_captured_at("SYN-001", 2)
        self.assertEqual(t_dev1_img2, "2026-10-03T09:03:00+09:00")

    def test_ingestion_folders_difference_and_unmodified_source(self):
        """5. 取り込み用2フォルダの内容の違い、および 6. 元のフォルダが変更されないことを検証。"""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            src_dir = temp_path / "mock_synthetic_input"
            src_category_dir = src_dir / "正面"
            src_category_dir.mkdir(parents=True, exist_ok=True)

            out_dir = temp_path / "mock_synthetic_output"

            # モック画像2枚を作成
            dummy_img = np.full((960, 1280, 3), 180, dtype=np.uint8)
            img1_path = src_category_dir / "sample_img_01.png"
            img2_path = src_category_dir / "sample_img_02.png"
            save_image_unicode_safe(img1_path, dummy_img)
            save_image_unicode_safe(img2_path, dummy_img)

            # モック groundtruth_synthetic.json
            mock_gt = [
                {
                    "image": str(img1_path).replace("\\", "/"),
                    "true_value": 10.0,
                    "min_value": 0.0,
                    "max_value": 150.0,
                    "scope": "synthetic",
                    "category": "正面",
                    "device_id": "SYN-001",
                    "device_name": "合成 圧力計0-150 白",
                    "condition": {"camera_yaw": 0, "camera_pitch": 0, "blur": "none"},
                    "degradations": {},
                },
                {
                    "image": str(img2_path).replace("\\", "/"),
                    "true_value": 20.0,
                    "min_value": 0.0,
                    "max_value": 150.0,
                    "scope": "synthetic",
                    "category": "正面",
                    "device_id": "SYN-002",
                    "device_name": "合成 圧力計0-150 クリーム",
                    "condition": {"camera_yaw": 0, "camera_pitch": 0, "blur": "none"},
                    "degradations": {},
                },
            ]
            gt_file = src_dir / "groundtruth_synthetic.json"
            with open(gt_file, "w", encoding="utf-8") as f:
                json.dump(mock_gt, f, indent=2, ensure_ascii=False)

            # 6. 元フォルダの全ファイルのハッシュを事前記録
            def compute_dir_hashes(d: Path) -> dict[str, str]:
                hashes = {}
                for p in d.rglob("*"):
                    if p.is_file():
                        rel = str(p.relative_to(d))
                        hashes[rel] = hashlib.sha256(p.read_bytes()).hexdigest()
                return hashes

            pre_hashes = compute_dir_hashes(src_dir)

            # データセット処理実行
            ret = process_dataset(src_dir, out_dir)
            self.assertEqual(ret, 0)

            # 6. 元のフォルダが全く変更されていないことを検証
            post_hashes = compute_dir_hashes(src_dir)
            self.assertEqual(pre_hashes, post_hashes, "Source folder files must NOT be modified")

            # 5. 取り込み用フォルダの検証
            with_dev_dir = out_dir / "取り込み用_サイドカーに機器あり"
            qr_only_dir = out_dir / "取り込み用_QRのみ"

            self.assertTrue(with_dev_dir.is_dir())
            self.assertTrue(qr_only_dir.is_dir())

            # 画像ファイルの存在確認
            self.assertTrue((with_dev_dir / "sample_img_01.png").is_file())
            self.assertTrue((qr_only_dir / "sample_img_01.png").is_file())

            # サイドカーJSONの内容の違いの検証
            sidecar_with_dev = json.loads(
                (with_dev_dir / "sample_img_01.json").read_text(encoding="utf-8")
            )
            sidecar_qr_only = json.loads(
                (qr_only_dir / "sample_img_01.json").read_text(encoding="utf-8")
            )

            # 「機器あり」側: local_id, captured_at, device_id, device_name が入っていること
            self.assertEqual(sidecar_with_dev.get("local_id"), "sample_img_01")
            self.assertEqual(sidecar_with_dev.get("captured_at"), "2026-10-01T09:03:00+09:00")
            self.assertEqual(sidecar_with_dev.get("device_id"), "SYN-001")
            self.assertEqual(sidecar_with_dev.get("device_name"), "合成 圧力計0-150 白")

            # 「QRのみ」側: local_id, captured_at だけが入っており、device_id, device_name は含まれないこと
            self.assertEqual(sidecar_qr_only.get("local_id"), "sample_img_01")
            self.assertEqual(sidecar_qr_only.get("captured_at"), "2026-10-01T09:03:00+09:00")
            self.assertNotIn("device_id", sidecar_qr_only)
            self.assertNotIn("device_name", sidecar_qr_only)

            # 正解_QR付き.json の検証
            gt_qr_path = out_dir / "正解_QR付き.json"
            self.assertTrue(gt_qr_path.is_file())
            gt_qr_data = json.loads(gt_qr_path.read_text(encoding="utf-8"))
            self.assertEqual(len(gt_qr_data), 2)
            for item in gt_qr_data:
                self.assertIn("qr", item)
                qr_info = item["qr"]
                self.assertIn("bbox", qr_info)
                self.assertIn("degraded", qr_info)
                self.assertIn("payload", qr_info)
                self.assertEqual(len(qr_info["bbox"]), 4)

            # レポートとREADMEの存在確認
            self.assertTrue((out_dir / "QR読み取り率.md").is_file())
            self.assertTrue((out_dir / "README.md").is_file())


if __name__ == "__main__":
    unittest.main()
