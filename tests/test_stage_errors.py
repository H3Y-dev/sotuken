"""
eval/stage_errors.py および eval/summarize_stage.py の単体テスト。

実画像やVLM/重い検出モデルは使わず、計算関数とモックによる再開スキップ処理を高速に検証する。
"""
import json
import math
import os
import shutil
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from eval import stage_errors
from eval import summarize_stage


class TestGeometryAndMetrics(unittest.TestCase):

    def test_ang(self):
        # (0, 0) を中心とした各方向の偏角
        self.assertAlmostEqual(stage_errors.ang((0, 0), (10, 0)), 0.0)
        self.assertAlmostEqual(stage_errors.ang((0, 0), (0, 10)), math.pi / 2)
        self.assertAlmostEqual(stage_errors.ang((0, 0), (-10, 0)), math.pi)
        self.assertAlmostEqual(stage_errors.ang((0, 0), (0, -10)), -math.pi / 2)

    def test_angdiff_deg(self):
        # 同一角度
        self.assertAlmostEqual(stage_errors.angdiff_deg(0, 0), 0.0)
        # 直角差 (90度)
        self.assertAlmostEqual(stage_errors.angdiff_deg(0, math.pi / 2), 90.0)
        # 順序非依存
        self.assertAlmostEqual(stage_errors.angdiff_deg(math.pi / 2, 0), 90.0)
        # 180度境界の跨ぎ（179度と-179度の差は2度）
        a1 = math.radians(179)
        a2 = math.radians(-179)
        self.assertAlmostEqual(stage_errors.angdiff_deg(a1, a2), 2.0)
        # 180度ちょうど
        self.assertAlmostEqual(stage_errors.angdiff_deg(0, math.pi), 180.0)

    def test_dist(self):
        self.assertAlmostEqual(stage_errors.dist((0, 0), (3, 4)), 5.0)
        self.assertAlmostEqual(stage_errors.dist((10, 20), (10, 20)), 0.0)

    def test_compute_stage_row_normal(self):
        entry = {
            'image': 'test_panel.png',
            'note': 'test meter note',
            'true_value': 50.0,
            'min_value': 0.0,
            'max_value': 100.0,
            'category': 'test_cat',
        }
        result = {
            'stage': 'ok',
            'value': 52.5,
            'center': (100.0, 100.0),
            'zero_pt': (50.0, 100.0),
            'full_pt': (150.0, 100.0),
            'min_value': 0.0,
            'max_value': 100.0,
            'orientation_angle': 0,
            'cropped': False,
            'read_method': 'global',
            'scale_confident': True,
        }
        pts = {
            'center': (100.0, 100.0),
            'zero_pt': (50.0, 100.0),
            'full_pt': (150.0, 100.0),
            'needle_tip': (100.0, 50.0),
        }
        needle = {
            'direction': (0.0, -1.0),
            'angle_tip': -math.pi / 2,
            'tip': (100.0, 52.0),
        }

        row = stage_errors.compute_stage_row(entry, result, pts, 'test_panel.png', needle=needle)

        self.assertEqual(row['image'], 'test_panel.png')
        self.assertEqual(row['stage'], 'ok')
        # 誤差: |52.5 - 50.0| / 100 * 100 = 2.5%
        self.assertAlmostEqual(row['err_fs'], 2.5)
        self.assertTrue(row['coords_comparable'])
        self.assertAlmostEqual(row['center_px'], 0.0)
        self.assertAlmostEqual(row['center_pct_radius'], 0.0)
        self.assertAlmostEqual(row['zero_pt_deg'], 0.0)
        self.assertAlmostEqual(row['full_pt_deg'], 0.0)
        self.assertTrue(row['range_ok'])
        self.assertAlmostEqual(row['needle_seg_deg'], 0.0)
        self.assertAlmostEqual(row['needle_tip_px'], 2.0)

    def test_compute_stage_row_rotated_or_cropped(self):
        entry = {
            'image': 'test_rot.png',
            'true_value': 10.0,
            'min_value': 0.0,
            'max_value': 100.0,
        }
        result = {
            'stage': 'ok',
            'value': 10.0,
            'center': (120.0, 120.0),
            'orientation_angle': 90,
            'cropped': False,
        }
        pts = {
            'center': (100.0, 100.0),
            'zero_pt': (50.0, 100.0),
        }
        row = stage_errors.compute_stage_row(entry, result, pts, 'test_rot.png')
        self.assertFalse(row['coords_comparable'])
        self.assertNotIn('center_px', row)

    def test_make_error_row(self):
        entry = {'image': 'error_sample.png', 'note': 'bad input'}
        row = stage_errors.make_error_row(entry, 'Division by zero', 'error_sample.png')
        self.assertEqual(row['image'], 'error_sample.png')
        self.assertEqual(row['stage'], 'error')
        self.assertIn('Division by zero', row['error'])
        self.assertFalse(row['coords_comparable'])

    @patch('meter_reader.detect_needle')
    def test_compute_stage_row_does_not_swallow_detect_needle_exception(self, mock_detect_needle):
        mock_detect_needle.side_effect = RuntimeError('needle crash')
        entry = {'image': 'test.png', 'true_value': 50.0, 'min_value': 0.0, 'max_value': 100.0}
        result = {
            'stage': 'ok',
            'value': 50.0,
            'center': (100.0, 100.0),
            'orientation_angle': 0,
            'cropped': False,
            'processed_img': MagicMock(),
        }
        pts = {'center': (100.0, 100.0), 'needle_tip': (100.0, 50.0)}
        with self.assertRaises(RuntimeError) as ctx:
            stage_errors.compute_stage_row(entry, result, pts, 'test.png')
        self.assertIn('needle crash', str(ctx.exception))


class TestResumeAndLimit(unittest.TestCase):

    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.gt_path = os.path.join(self.test_dir, 'groundtruth.json')
        self.out_path = os.path.join(self.test_dir, 'results.jsonl')

        # 5件のダミー正解データと画像ファイルを作成
        self.entries = []
        for i in range(5):
            img_name = 'img_%d.png' % i
            img_path = os.path.join(self.test_dir, img_name)
            with open(img_path, 'wb') as f:
                f.write(b'dummy_image_data')

            self.entries.append({
                'image': img_path,
                'true_value': float(i * 10),
                'min_value': 0.0,
                'max_value': 100.0,
                'note': 'pressure-150 v%d%% y0p0 normal none' % (i * 10),
                'points': {
                    'center': [100, 100],
                    'zero_pt': [50, 100],
                    'full_pt': [150, 100],
                    'needle_tip': [100, 50],
                }
            })
        with open(self.gt_path, 'w', encoding='utf-8') as f:
            json.dump(self.entries, f)

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    @patch('cv2.imdecode')
    @patch('meter_pipeline.read_meter')
    def test_resume_skips_and_limit(self, mock_read_meter, mock_imdecode):
        mock_imdecode.return_value = MagicMock()
        mock_read_meter.return_value = {
            'stage': 'ok',
            'value': 10.0,
            'center': (100, 100),
            'min_value': 0.0,
            'max_value': 100.0,
            'orientation_angle': 0,
            'cropped': False,
            'processed_img': None,
        }

        # 1回目の実行: --limit 3
        stage_errors.run_stage_errors(self.gt_path, self.out_path, limit=3)
        self.assertEqual(mock_read_meter.call_count, 3)

        rows_first = stage_errors.load_completed_images(self.out_path)
        self.assertEqual(len(rows_first), 3)
        self.assertIn('img_0.png', rows_first)
        self.assertIn('img_1.png', rows_first)
        self.assertIn('img_2.png', rows_first)

        # 2回目の実行: --limit 5（最初の3件はスキップされ、残り2件のみ追加）
        stage_errors.run_stage_errors(self.gt_path, self.out_path, limit=5)
        # 合計呼び出し回数は 3 + 2 = 5 になるはず
        self.assertEqual(mock_read_meter.call_count, 5)

        rows_second = stage_errors.load_completed_images(self.out_path)
        self.assertEqual(len(rows_second), 5)
        self.assertIn('img_3.png', rows_second)
        self.assertIn('img_4.png', rows_second)

        # ファイル行数も正確に5行
        with open(self.out_path, 'r', encoding='utf-8') as f:
            lines = [line.strip() for line in f if line.strip()]
        self.assertEqual(len(lines), 5)

    @patch('cv2.imdecode')
    @patch('meter_pipeline.read_meter')
    def test_first_read_error_and_flag_forwarding(self, mock_read_meter, mock_imdecode):
        mock_imdecode.return_value = MagicMock()
        mock_read_meter.side_effect = [
            RuntimeError('first read failed'),
            {
                'stage': 'ok',
                'value': 10.0,
                'center': (100, 100),
                'min_value': 0.0,
                'max_value': 100.0,
                'orientation_angle': 0,
                'cropped': False,
                'processed_img': None,
            },
        ]

        stage_errors.run_stage_errors(
            self.gt_path,
            self.out_path,
            local_read=True,
            needle_angle='tip',
            limit=2,
        )

        self.assertEqual(mock_read_meter.call_count, 2)
        # Verify forwarding of use_vlm=False, local_read=True, needle_angle='tip'
        for call_args in mock_read_meter.call_args_list:
            _, kwargs = call_args
            self.assertFalse(kwargs.get('use_vlm'))
            self.assertTrue(kwargs.get('local_read'))
            self.assertEqual(kwargs.get('needle_angle'), 'tip')

        rows = summarize_stage.load_rows(self.out_path)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]['stage'], 'error')
        self.assertIn('first read failed', rows[0]['error'])
        self.assertEqual(rows[1]['stage'], 'ok')

    @patch('cv2.imdecode')
    @patch('meter_pipeline.read_meter')
    def test_missing_points_records_error_row(self, mock_read_meter, mock_imdecode):
        mock_imdecode.return_value = MagicMock()
        mock_read_meter.return_value = {'stage': 'ok', 'value': 10.0, 'center': (100, 100)}

        bad_gt = os.path.join(self.test_dir, 'bad_gt.json')
        with open(bad_gt, 'w', encoding='utf-8') as f:
            json.dump([{'image': self.entries[0]['image'], 'true_value': 10.0}], f)

        bad_out = os.path.join(self.test_dir, 'bad_out.jsonl')
        stage_errors.run_stage_errors(bad_gt, bad_out)

        rows = summarize_stage.load_rows(bad_out)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['stage'], 'error')

    @patch('cv2.imdecode')
    @patch('meter_pipeline.read_meter')
    def test_resume_repairs_truncated_final_row_and_summary_loads(self, mock_read_meter, mock_imdecode):
        mock_imdecode.return_value = MagicMock()
        mock_read_meter.return_value = {
            'stage': 'ok',
            'value': 10.0,
            'center': (100, 100),
            'min_value': 0.0,
            'max_value': 100.0,
            'orientation_angle': 0,
            'cropped': False,
            'processed_img': None,
        }

        # 正常な1行目と、途中で切れた不正な2行目を書き込む
        valid_first_row = {
            'image': 'img_0.png',
            'note': 'valid first row',
            'stage': 'ok',
            'err_fs': 1.0,
            'coords_comparable': True,
        }
        with open(self.out_path, 'wb') as f:
            f.write(json.dumps(valid_first_row).encode('utf-8') + b'\n')
            f.write(b'{"image": "img_1.png", "stage": "ok", "err_fs":')

        # 再開（limit=2）
        stage_errors.run_stage_errors(self.gt_path, self.out_path, limit=2)

        # summarize_stage.load_rows で正常に2件読み出せること
        rows = summarize_stage.load_rows(self.out_path)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]['image'], 'img_0.png')
        self.assertEqual(rows[0]['stage'], 'ok')
        self.assertEqual(rows[1]['image'], 'img_1.png')
        self.assertEqual(rows[1]['stage'], 'ok')

        s = summarize_stage.summary(rows)
        self.assertEqual(s['n'], 2)
        self.assertEqual(s['ok'], 2)

    def test_malformed_nonfinal_line_raises_error(self):
        with open(self.out_path, 'wb') as f:
            f.write(b'{"image": "img_0.png"}\n')
            f.write(b'{"corrupted": bad json\n')
            f.write(b'{"image": "img_2.png"}\n')

        with self.assertRaises(ValueError):
            stage_errors.load_completed_images(self.out_path)


class TestSummarizeStage(unittest.TestCase):

    def test_load_rows_jsonl(self):
        path = os.path.join(tempfile.gettempdir(), 'test_load_rows.jsonl')
        with open(path, 'w', encoding='utf-8') as f:
            f.write('{"stage": "ok", "err_fs": 1.0}\n\n{"stage": "ok", "err_fs": 2.0}\n')
        try:
            rows = summarize_stage.load_rows(path)
            self.assertEqual(len(rows), 2)
            self.assertEqual(rows[0]['err_fs'], 1.0)
            self.assertEqual(rows[1]['err_fs'], 2.0)
        finally:
            if os.path.exists(path):
                os.remove(path)

    def test_cond_parsing(self):
        r = {'note': 'pressure-150 v27% y30p0 glare none'}
        c = summarize_stage.cond(r)
        self.assertEqual(c['meter'], 'pressure-150')
        self.assertEqual(c['camera'], 'y30p0')
        self.assertEqual(c['light'], 'glare')
        self.assertEqual(c['blur'], 'none')

    def test_summary_metrics(self):
        rs = [
            {'stage': 'ok', 'err_fs': 1.0, 'range_ok': True, 'center_pct_radius': 2.0, 'zero_pt_deg': 0.5, 'full_pt_deg': 0.5, 'needle_seg_deg': 0.2},
            {'stage': 'ok', 'err_fs': 2.0, 'range_ok': True, 'center_pct_radius': 3.0, 'zero_pt_deg': 0.8, 'full_pt_deg': 0.6, 'needle_seg_deg': 0.4},
            {'stage': 'needle', 'range_ok': False, 'center_pct_radius': 10.0},
        ]
        s = summarize_stage.summary(rs)
        self.assertEqual(s['n'], 3)
        self.assertEqual(s['ok'], 2)
        self.assertEqual(s['within2.5'], 2)
        self.assertAlmostEqual(s['mean'], 1.5)
        self.assertAlmostEqual(s['median'], 1.5)
        self.assertAlmostEqual(s['max'], 2.0)
        self.assertEqual(s['cat25'], 0)
        self.assertEqual(s['range_ok'], '2/3')
        self.assertAlmostEqual(s['center_pct_radius_med'], 3.0)

    def test_generate_markdown_runs(self):
        rs = [
            {
                'image': 'test.png',
                'note': 'pressure-150 v10% y0p0 normal none',
                'stage': 'ok',
                'err_fs': 1.2,
                'range_ok': True,
                'center_pct_radius': 0.8,
                'needle_seg_deg': 0.5,
                'coords_comparable': True,
            }
        ]
        md = summarize_stage.generate_markdown(rs)
        self.assertIn('# 工程別評価集計レポート', md)
        self.assertIn('pressure-150', md)
        self.assertIn('| ok | 1 | 100.0% |', md)

    def test_generate_markdown_empty(self):
        md = summarize_stage.generate_markdown([])
        self.assertIn('対象データが空です', md)


class TestArgParse(unittest.TestCase):

    def test_negative_limit_rejected(self):
        with self.assertRaises(SystemExit):
            stage_errors.parse_args(['dummy_gt.json', '-o', 'dummy_out.jsonl', '--limit', '-1'])

    def test_valid_limit_accepted(self):
        args = stage_errors.parse_args(['dummy_gt.json', '-o', 'dummy_out.jsonl', '--limit', '5'])
        self.assertEqual(args.limit, 5)
        args_zero = stage_errors.parse_args(['dummy_gt.json', '-o', 'dummy_out.jsonl', '--limit', '0'])
        self.assertEqual(args_zero.limit, 0)


if __name__ == '__main__':
    unittest.main()
