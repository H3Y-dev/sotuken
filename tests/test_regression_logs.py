"""
過去の検出ログを使った回帰テスト。

検出ログには、実際にGUIで検出したときの入力（画像・中心点・ゼロ点・
フルスケール点・目盛りの最小/最大値）と、そのときの出力（角度・値）が
セットで残っている。同じ入力を与えて同じ出力になることを確認すれば、
針検出や角度計算に手を入れたときに、意図しない挙動の変化を検出できる。

読み込み先は2か所:

- `tests/fixtures/` — git管理下。**誰がcloneしても必ず実行される**。
  `logs/` はサイズの都合でgit管理外にしてあるため、そこだけに頼ると
  他の開発者の環境ではテストが黙ってスキップされ、「壊していない」
  という担保が効かなくなる。それを防ぐための最小セット。
- `logs/` — 手元にあれば追加で使う。件数が多いほど検出力が上がる。

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

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIXTURE_DIR = os.path.join(_ROOT, 'tests', 'fixtures')
LOG_DIR = os.path.join(_ROOT, 'logs')


def _load_cases_from(directory):
    """1つのディレクトリから、画像が残っていて再現可能なログを集める"""
    cases = []
    for json_path in sorted(glob.glob(os.path.join(directory, '*.json'))):
        try:
            with open(json_path, encoding='utf-8') as f:
                record = json.load(f)
        except (ValueError, OSError):
            continue
        image_path = os.path.join(directory, record.get('scanned_image', ''))
        if not os.path.exists(image_path):
            continue
        if not all(k in record for k in
                   ('center', 'zero_point', 'fullscale_point',
                    'val_min', 'val_max', 'value', 'angle_deg')):
            continue
        cases.append((os.path.basename(json_path), image_path, record))
    return cases


def _load_cases():
    """
    fixtures（git管理下・必ず存在する）と logs（手元にあれば）を合わせて集める。
    同じログが両方にある場合は重複させない。
    """
    cases = _load_cases_from(FIXTURE_DIR)
    known = set(name for name, _, _ in cases)
    for case in _load_cases_from(LOG_DIR):
        if case[0] not in known:
            cases.append(case)
    return cases


class TestPastDetectionsAreReproduced(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.cases = _load_cases()

    def test_fixtures_are_present(self):
        """
        テストデータが1件も無い状態を「成功」にしない。
        スキップされたテストは通ったテストではない。ここが空のまま
        緑になると、挙動を壊したことに誰も気づけなくなる。
        """
        self.assertTrue(
            _load_cases_from(FIXTURE_DIR),
            'tests/fixtures/ に検出ログがありません。git管理下のはずなので、'
            'ファイルが失われているか、cloneが不完全です')

    def test_reading_matches_recorded_result(self):
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
