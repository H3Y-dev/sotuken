import unittest
import os
import cv2
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

        # 画像の読み込み
        data = cv2.imread(self.img_path)
        self.assertIsNotNone(data, "画像の読み込みに失敗しました")

        # 関数の実行
        fixed_img, angle, count, zero_count = orientation.normalize_orientation(data)

        # 戻り値の型と範囲のチェック
        self.assertIsNotNone(fixed_img)
        self.assertIn(angle, [0, 90, 180, 270])
        self.assertIsInstance(count, int)
        self.assertIsInstance(zero_count, int)

if __name__ == "__main__":
    unittest.main()