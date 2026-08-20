"""
過去の検出ログを使った回帰テスト。

logs/ には、実際にGUIで検出したときの入力（画像・中心点・ゼロ点・
フルスケール点・目盛りの最小/最大値）と、そのときの出力（角度・値）が
セットで残っている。同じ入力を与えて同じ出力になることを確認すれば、
針検出や角度計算に手を入れたときに、意図しない挙動の変化を検出できる。

logs/ はgit管理外なので、ログが無い環境ではスキップする。

実行:
    venv\\Scripts\\python.exe -m unittest discover -s tests
"""
import glob
import json
import os
import sys
import unittest

import cv2
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import meter_reader

LOG_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'logs')


def _load_cases():
    """ログのうち、画像が残っていて再現可能なものだけを集める"""
    cases = []
    for json_path in sorted(glob.glob(os.path.join(LOG_DIR, '*.json'))):
        try:
            with open(json_path, encoding='utf-8') as f:
                record = json.load(f)
        except (ValueError, OSError):
            continue
        image_path = os.path.join(LOG_DIR, record.get('scanned_image', ''))
        if not os.path.exists(image_path):
            continue
        if not all(k in record for k in
                   ('center', 'zero_point', 'fullscale_point',
                    'val_min', 'val_max', 'value', 'angle_deg')):
            continue
        cases.append((os.path.basename(json_path), image_path, record))
    return cases


class TestPastDetectionsAreReproduced(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.cases = _load_cases()

    def test_reading_matches_recorded_result(self):
        if not self.cases:
            self.skipTest('再現できる検出ログがありません（logs/ が空）')

        for name, image_path, record in self.cases:
            with self.subTest(log=name):
                img = cv2.imdecode(
                    np.fromfile(image_path, dtype=np.uint8), cv2.IMREAD_COLOR)
                self.assertIsNotNone(img, '画像を読み込めません: %s' % image_path)

                result = meter_reader.compute_reading(
                    img,
                    tuple(record['center']),
                    tuple(record['zero_point']),
                    tuple(record['fullscale_point']),
                    record['val_min'],
                    record['val_max'],
                )
                self.assertIsNotNone(result, '針を検出できませんでした')
                # ログは丸めて保存されているので、その桁数の範囲で一致を見る
                self.assertAlmostEqual(result['value'], record['value'], places=3)
                self.assertAlmostEqual(result['angle_deg'], record['angle_deg'], places=1)


if __name__ == '__main__':
    unittest.main()
