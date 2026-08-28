import unittest
import os
from unittest.mock import patch
import cv2
import numpy as np
import orientation

class TestOrientation(unittest.TestCase):
    def setUp(self):
        # eval/images/meter1.png のパスを取得（安全な相対パス）
        self.repo_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.img_path = os.path.join(self.repo_dir, "eval", "images", "meter1.png")

    def test_normalize_orientation_returns_tuple(self):
        """normalize_orientation が正しい形式 (img, angle, count, zero_count) を返すか確認"""
        if not os.path.exists(self.img_path):
            self.skipTest(f"テスト用画像が見つかりません: {self.img_path}")

        # 画像の読み込み（cv2.imreadは日本語パスを扱えないため、
        # このプロジェクトの慣習に合わせてimdecode+np.fromfileを使う）
        data = cv2.imdecode(
            np.fromfile(self.img_path, dtype=np.uint8), cv2.IMREAD_COLOR)
        self.assertIsNotNone(data, "画像の読み込みに失敗しました")

        # 関数の実行
        fixed_img, angle, count, zero_count = orientation.normalize_orientation(data)

        # 戻り値の型と範囲のチェック
        self.assertIsNotNone(fixed_img)
        self.assertIn(angle, [0, 90, 180, 270])
        self.assertIsInstance(count, int)
        self.assertIsInstance(zero_count, int)

class TestOrientationMargin(unittest.TestCase):
    """
    2026-08-28: 0度が僅差で他の向きに負けただけで誤って回転してしまう
    問題（耐圧試験_昇圧前圧力計.jpgで実際に発生、0度=4個/180度=5個の
    僅差で180度が選ばれ全く違う値になった）の回帰テスト。
    OCR呼び出し（read_scale_numbers）をモックして、判定ロジックだけを
    検証する。
    """

    def _fake_img(self):
        return np.zeros((4, 4, 3), dtype=np.uint8)

    def _run_with_counts(self, counts_by_angle):
        """counts_by_angle: {0: n, 90: n, 180: n, 270: n} の通りに
        read_scale_numbers がその個数のダミー結果を返すようにモックする。
        _rotateも合わせてモックし、角度そのものを「回転後画像」として
        扱うことで、どの角度に対する呼び出しかを判定できるようにする。"""
        with patch("orientation._rotate") as mock_rotate, \
             patch("orientation.scale_value_detect.read_scale_numbers") as mock_read:
            mock_rotate.side_effect = lambda img, angle: angle  # 角度そのものを「回転後画像」として渡す
            mock_read.side_effect = lambda rotated: [None] * counts_by_angle[rotated]
            return orientation.normalize_orientation(self._fake_img())

    def test_close_margin_does_not_rotate(self):
        """0度との差が1個（マージン未満）なら、僅差で他の向きが勝っても回転しない"""
        _, angle, _, zero_count = self._run_with_counts({0: 4, 90: 4, 180: 5, 270: 5})
        self.assertEqual(angle, 0)
        self.assertEqual(zero_count, 4)

    def test_large_margin_rotates(self):
        """0度との差が2個以上（マージン以上）なら、その向きを採用する"""
        _, angle, best_count, zero_count = self._run_with_counts(
            {0: 4, 90: 6, 180: 5, 270: 6})
        self.assertIn(angle, (90, 270))
        self.assertEqual(best_count, 6)
        self.assertEqual(zero_count, 4)

    def test_all_tied_keeps_zero(self):
        """全方向が同数なら0度のまま（従来の挙動を維持）"""
        _, angle, _, _ = self._run_with_counts({0: 6, 90: 6, 180: 6, 270: 6})
        self.assertEqual(angle, 0)


if __name__ == "__main__":
    unittest.main()