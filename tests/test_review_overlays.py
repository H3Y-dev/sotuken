"""eval/review_overlays.py の単体テスト。"""
from __future__ import annotations

import csv
import json
import os
import shutil
import tempfile
import unittest
from unittest import mock

import cv2
import numpy as np

from eval.review_overlays import (
    INDIVIDUAL_COLUMNS,
    SUMMARY_COLUMNS,
    analyze_stage_intermediates,
    build_individual_sheet_rows,
    generate_review_artifacts,
    is_failure,
    pick_review_images,
    render_review_overlay,
)


class TestPickReviewImages(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _create_jsonl(self, filename: str, rows: list) -> str:
        path = os.path.join(self.temp_dir, filename)
        with open(path, "w", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        return path

    def test_failure_detection(self):
        ok_row = {"image": "ok.png", "stage": "ok", "range_ok": True, "err_fs": 1.2}
        self.assertFalse(is_failure(ok_row))

        fail_stage = {"image": "f1.png", "stage": "scale", "range_ok": True, "err_fs": 1.0}
        self.assertTrue(is_failure(fail_stage))

        fail_no_err = {"image": "f2.png", "stage": "ok", "range_ok": True, "err_fs": None}
        self.assertTrue(is_failure(fail_no_err))

        fail_range = {"image": "f3.png", "stage": "ok", "range_ok": False, "err_fs": 1.0}
        self.assertTrue(is_failure(fail_range))

        fail_err = {"image": "f4.png", "stage": "ok", "range_ok": True, "err_fs": 2.51}
        self.assertTrue(is_failure(fail_err))

    def test_equal_distribution(self):
        rows = []
        for cat in ["catA", "catB", "catC"]:
            for i in range(10):
                rows.append({
                    "image": f"{cat}_{i}.png",
                    "category": cat,
                    "stage": "scale",
                    "range_ok": False,
                    "err_fs": 5.0,
                })
        path = self._create_jsonl("test.jsonl", rows)

        selected, counts = pick_review_images([path], n=7, seed=42)
        self.assertEqual(len(selected), 7)
        self.assertEqual(len(counts), 3)
        self.assertEqual(sorted(counts.values()), [2, 2, 3])

        selected_20, counts_20 = pick_review_images([path], n=20, seed=42)
        self.assertEqual(len(selected_20), 20)
        self.assertEqual(sorted(counts_20.values()), [6, 7, 7])

    def test_seed_determinism(self):
        rows = [
            {"image": f"img_{i}.png", "category": f"cat_{i % 4}", "stage": "scale", "range_ok": False, "err_fs": 5.0}
            for i in range(40)
        ]
        path = self._create_jsonl("determinism.jsonl", rows)

        res1, counts1 = pick_review_images([path], n=15, seed=123)
        res2, counts2 = pick_review_images([path], n=15, seed=123)
        self.assertEqual(res1, res2)
        self.assertEqual(counts1, counts2)

        res3, _ = pick_review_images([path], n=15, seed=999)
        self.assertNotEqual(res1, res3)

    def test_exclude_images(self):
        rows = [
            {"image": "keep1.png", "category": "catA", "stage": "scale", "range_ok": False, "err_fs": 5.0},
            {"image": "drop1.png", "category": "catA", "stage": "scale", "range_ok": False, "err_fs": 5.0},
            {"image": "drop2.png", "category": "catA", "stage": "scale", "range_ok": False, "err_fs": 5.0},
        ]
        path = self._create_jsonl("data.jsonl", rows)

        exclude_txt = os.path.join(self.temp_dir, "exclude.txt")
        with open(exclude_txt, "w", encoding="utf-8") as f:
            f.write("drop1.png\n")

        selected, _ = pick_review_images([path], n=10, seed=1, exclude=[exclude_txt, "drop2.png"])
        self.assertEqual(selected, ["keep1.png"])

    def test_exclude_categories(self):
        rows = [
            {"image": "img_a.png", "category": "catA", "stage": "scale", "range_ok": False, "err_fs": 5.0},
            {"image": "img_b.png", "category": "catB", "stage": "scale", "range_ok": False, "err_fs": 5.0},
            {"image": "img_c.png", "category": "catC", "stage": "scale", "range_ok": False, "err_fs": 5.0},
        ]
        path = self._create_jsonl("cats.jsonl", rows)

        selected, counts = pick_review_images([path], n=10, seed=1, exclude_categories=["catA,catC"])
        self.assertEqual(selected, ["img_b.png"])
        self.assertNotIn("catA", counts)
        self.assertNotIn("catC", counts)

    def test_multiple_files_overwrite(self):
        f1_rows = [
            {"image": "img1.png", "category": "catA", "stage": "scale", "range_ok": False, "err_fs": 5.0},
            {"image": "img2.png", "category": "catA", "stage": "scale", "range_ok": False, "err_fs": 5.0},
        ]
        p1 = self._create_jsonl("f1.jsonl", f1_rows)

        f2_rows = [
            {"image": "img1.png", "category": "catA", "stage": "ok", "range_ok": True, "err_fs": 0.5},
        ]
        p2 = self._create_jsonl("f2.jsonl", f2_rows)

        selected, _ = pick_review_images([p1, p2], n=10, seed=1)
        self.assertEqual(selected, ["img2.png"])


class TestReviewArtifacts(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_individual_sheet_row_sequence_and_columns(self):
        entry = {
            "image": "sample.png",
            "category": "正面",
            "min_value": 0.0,
            "max_value": 150.0,
            "true_value": 10.5,
        }
        result = {
            "stage": "ok",
            "center": [640.0, 480.0],
            "min_value": 0.0,
            "max_value": 150.0,
            "zero_pt": [438.0, 681.0],
            "full_pt": [841.0, 681.0],
            "value": 10.5,
            "angle_deg": 215.3,
        }
        intermediates = {
            "ticks": [
                {"centroid": [438.0, 681.0], "is_major": True, "_id": "T1"},
                {"centroid": [500.0, 600.0], "is_major": False, "_id": "T2"},
            ],
            "ocr_items": [
                {"id": "N1", "value": 0.0, "x": 438.0, "y": 681.0, "score": 0.99, "bound_tick_id": "T1", "used_in_range": "○"},
                {"id": "N2", "value": 150.0, "x": 841.0, "y": 681.0, "score": 0.98, "bound_tick_id": "なし", "used_in_range": "○"},
            ],
            "needle": {"angle_deg": 215.3, "tip": [385.0, 604.0]},
        }

        rows = build_individual_sheet_rows(entry, result, intermediates)

        # 列の確認
        for r in rows:
            self.assertEqual(list(r.keys()), INDIVIDUAL_COLUMNS)

        # 段階の順序を確認: ①中心 -> ②目盛り -> ③数字 -> ④範囲 -> ⑤針 -> ⑥値
        stages = [r["段階"] for r in rows]
        self.assertEqual(stages[0], "段階①中心")
        self.assertEqual(stages[1], "段階②目盛り")
        self.assertEqual(stages[2], "段階③数字(OCR)")
        self.assertEqual(stages[3], "段階③数字(OCR)")
        self.assertEqual(stages[4], "段階③数字(OCR)")  # OCRが読まなかった目盛りの数字
        self.assertEqual(stages[5], "段階④範囲")
        self.assertEqual(stages[6], "段階⑤針")
        self.assertEqual(stages[7], "段階⑥値")

        # ③数字の行の確認: N1, N2, 未検出行
        self.assertEqual(rows[2]["項目"], "N1")
        self.assertEqual(rows[2]["検出した内容"], "0")
        self.assertEqual(rows[2]["対応目盛り"], "T1")
        self.assertEqual(rows[2]["範囲判定への使用"], "○")

        self.assertEqual(rows[3]["項目"], "N2")
        self.assertEqual(rows[3]["検出した内容"], "150")
        self.assertEqual(rows[3]["対応目盛り"], "なし")

        self.assertEqual(rows[4]["項目"], "OCRが読まなかった目盛りの数字")

        # 人が書く列が空文字であること
        for r in rows:
            self.assertEqual(r["人が読んだもの"], "")
            self.assertEqual(r["合っているか(○×)"], "")
            self.assertEqual(r["メモ"], "")

    def test_generate_review_artifacts_integration(self):
        dummy_img_path = os.path.join(self.temp_dir, "test_meter.png")
        dummy_img = np.zeros((300, 300, 3), dtype=np.uint8)
        cv2.imwrite(dummy_img_path, dummy_img)

        gt_data = [
            {
                "image": dummy_img_path,
                "category": "正面",
                "min_value": 0.0,
                "max_value": 150.0,
                "true_value": 10.5,
                "note": "sample note",
                "points": {
                    "center": [150, 150],
                    "zero_pt": [50, 250],
                    "full_pt": [250, 250],
                    "needle_tip": [100, 200],
                    "numbered_ticks": [
                        {"value": 0, "x": 50, "y": 250},
                        {"value": 150, "x": 250, "y": 250},
                    ],
                },
            }
        ]
        gt_path = os.path.join(self.temp_dir, "groundtruth.json")
        with open(gt_path, "w", encoding="utf-8") as f:
            json.dump(gt_data, f, ensure_ascii=False)

        mock_result = {
            "stage": "ok",
            "min_value": 0.0,
            "max_value": 150.0,
            "value": 12.0,
            "center": [151, 149],
            "zero_pt": [51, 249],
            "full_pt": [249, 251],
            "ticks": [
                {"centroid": [150, 50], "line_angle": 0.0, "length": 15, "is_major": True},
            ],
            "angle_deg": 180.0,
        }

        mock_ocr = [
            {"value": 0.0, "x": 50.0, "y": 250.0, "score": 0.99},
            {"value": 150.0, "x": 250.0, "y": 250.0, "score": 0.98},
        ]

        out_dir = os.path.join(self.temp_dir, "out")
        with mock.patch("meter_pipeline.read_meter", return_value=mock_result), \
             mock.patch("scale_value_detect.read_scale_numbers", return_value=mock_ocr):
            count, summary_rows = generate_review_artifacts(gt_path, out_dir=out_dir)

        self.assertEqual(count, 1)
        self.assertEqual(len(summary_rows), 1)

        # 1. 全体一覧シートの検証
        summary_csv_path = os.path.join(out_dir, "確認シート一覧.csv")
        self.assertTrue(os.path.exists(summary_csv_path))
        with open(summary_csv_path, "r", encoding="utf-8-sig") as f:
            reader = list(csv.reader(f))
            self.assertEqual(reader[0], SUMMARY_COLUMNS)
            self.assertEqual(len(reader), 2)
            row = reader[1]
            self.assertEqual(row[0], "001")
            self.assertEqual(row[1], "test_meter.png")
            self.assertEqual(row[2], "正面")
            self.assertEqual(row[3], "ok")
            self.assertEqual(row[4], "0〜150")
            self.assertEqual(row[5], "10.5")
            self.assertEqual(row[6], "0〜150")
            self.assertEqual(row[7], "12.00")
            self.assertEqual(row[8], "1.00")

        # 2. 個別確認シートの検証
        indiv_csv_path = os.path.join(out_dir, "001_test_meter_確認.csv")
        self.assertTrue(os.path.exists(indiv_csv_path))
        with open(indiv_csv_path, "r", encoding="utf-8-sig") as f:
            indiv_reader = list(csv.reader(f))
            self.assertEqual(indiv_reader[0], INDIVIDUAL_COLUMNS)
            # 段階①〜⑥が存在すること
            indiv_stages = [r[0] for r in indiv_reader[1:]]
            self.assertIn("段階①中心", indiv_stages)
            self.assertIn("段階②目盛り", indiv_stages)
            self.assertIn("段階③数字(OCR)", indiv_stages)
            self.assertIn("段階④範囲", indiv_stages)
            self.assertIn("段階⑤針", indiv_stages)
            self.assertIn("段階⑥値", indiv_stages)

        # 3. 確認用画像の検証
        out_png = os.path.join(out_dir, "001_test_meter.png")
        self.assertTrue(os.path.exists(out_png))


if __name__ == "__main__":
    unittest.main()
