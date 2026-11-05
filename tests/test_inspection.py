import csv
import hashlib
import json
import tempfile
import unittest
from unittest.mock import patch
from datetime import date
from pathlib import Path

from manager.devices import register_device, rename_device
from manager.inspection import create_inspection, export_inspection, restore_inspection
from manager.storage import MeterReading, Storage


class InspectionTests(unittest.TestCase):
    def setUp(self):
        self.storage = Storage(':memory:')
        self.addCleanup(self.storage._conn.close)
        register_device(self.storage, 'A-1', device_name='圧力計', unit='MPa', min_value=0, max_value=1)

    def add(self, hash='image', captured='2026-10-30T09:00:00', **kwargs):
        row = MeterReading(device_name='旧名称', value=0.5, stage='ok', image_path='old.jpg',
                           device_id='A-1', image_sha256=hash, captured_at=captured,
                           received_at='2026-10-30T10:00:00', image_rel='images/test.jpg', status='ok')
        for key, value in kwargs.items():
            setattr(row, key, value)
        self.storage.save_reading(row.device_name, row.image_path, vars(row), image_sha256=hash)

    def snapshot(self, targets=('A-1',)):
        return create_inspection(self.storage, 'PT-1', date(2026, 10, 30), date(2026, 10, 30), targets)

    def test_latest_image_then_latest_capture_even_failed(self):
        self.add(value=0.2)
        self.add(value=None, status='failed')
        self.add(hash='older', captured='2026-10-30T08:00:00', value=0.8)
        result = self.snapshot()
        self.assertEqual(len(result['history']), 2)
        row = result['rows'][0]
        self.assertIsNone(row['測定値'])
        self.assertEqual(row['読取状態'], '失敗')
        self.assertIn('読み取り失敗', row['要確認理由'])
        self.assertEqual(row['機器名'], '圧力計')

    def test_manual_warning_and_note(self):
        self.add(value=None, status='failed', device_id_issue='id_conflict')
        self.storage.save_image_truth('image', operator_value=0, operator_note='現場確認')
        row = self.snapshot()['rows'][0]
        self.assertEqual(row['測定方法'], '手動')
        self.assertEqual(row['現場入力値'], 0)
        self.assertEqual(row['備考'], '現場確認')
        self.assertIn('id_conflict', row['要確認理由'])

    def test_period_targets_and_null_hash(self):
        self.add(hash=None)
        self.add(hash=None)
        self.add(hash='outside', captured='2026-10-31T00:00:00')
        self.add(hash='other', device_id='B-1')
        self.assertEqual(len(self.snapshot()['history']), 2)
        self.assertEqual(self.snapshot(())['rows'], [])

    def test_range_and_missing_name(self):
        self.add(value=2)
        self.assertIn('範囲外の疑い', self.snapshot()['rows'][0]['要確認理由'])
        self.add(hash='unknown', device_id=None, device_name='unknown')
        row = self.snapshot(('name:unknown',))['rows'][0]
        self.assertIn('名称未設定', row['要確認理由'])
        self.assertIn('機器番号なし', row['要確認理由'])

    def test_manifest_export_and_restore_fixed_ids(self):
        self.add()
        result = self.snapshot()
        with tempfile.TemporaryDirectory() as directory:
            paths = export_inspection(result, directory)
            manifest = json.loads(Path(paths['manifest']).read_text(encoding='utf-8'))
            self.assertEqual(manifest['inspection_id'], 'PT-1')
            self.assertEqual(manifest['device_ids'], ['A-1'])
            self.assertEqual(manifest['date_from'], '2026-10-30')
            self.assertTrue(manifest['generated_at'])
            self.assertEqual(manifest['csv_sha256'], hashlib.sha256(Path(paths['csv']).read_bytes()).hexdigest())
            self.assertEqual(len(manifest['readings']), 1)
            self.assertEqual(manifest['readings'][0]['id'], 1)
            self.assertTrue(manifest['readings'][0]['reading_id'])
            with open(paths['history'], encoding='utf-8-sig', newline='') as stream:
                reader = csv.DictReader(stream)
                self.assertEqual(len(list(reader)), 1)
                self.assertNotIn('device_id_source', reader.fieldnames)
                self.assertNotIn('pipeline_version', reader.fieldnames)
                self.assertEqual(len(reader.fieldnames), 13)
            self.add(value=0.9)
            rename_device(self.storage, 'A-1', '新名称')
            restored = restore_inspection(self.storage, manifest)
            self.assertEqual(restored['rows'][0]['測定値'], 0.5)
            self.assertEqual(restored['rows'][0]['機器名'], '新名称')
            with self.assertRaises(FileExistsError):
                export_inspection(result, directory)

    def test_invalid_period_and_filename(self):
        with self.assertRaises(ValueError):
            create_inspection(self.storage, '../bad', date(2026, 10, 30), date(2026, 10, 30), [])
        with self.assertRaises(ValueError):
            create_inspection(self.storage, 'PT-1', date(2026, 10, 31), date(2026, 10, 30), [])

    def test_raw_range_fallback_and_truth_priority(self):
        self.add(device_id='B-1', value=2, min_value=0, max_value=1)
        row = self.snapshot(('B-1',))['rows'][0]
        self.assertIn('範囲外の疑い', row['要確認理由'])
        self.storage.save_image_truth('image', scale_min=0, scale_max=3)
        self.assertNotIn('範囲外の疑い', self.snapshot(('B-1',))['rows'][0]['要確認理由'])

    def test_time_fallback_utc_and_tie(self):
        self.add(hash='first', captured=None, value=0.1)
        self.add(hash='second', captured='2026-10-30T19:00:00+09:00', value=0.2)
        result = self.snapshot()
        self.assertEqual(result['rows'][0]['測定値'], 0.2)
        self.assertIsNone(result['history'][0]['撮影日時'])

    def test_fixed_target_copy_and_missing_restore_row(self):
        self.add()
        targets = ['A-1']
        result = self.snapshot(targets)
        targets.append('B-1')
        self.assertEqual(result['manifest']['device_ids'], ['A-1'])
        self.storage._conn.execute('DELETE FROM meter_readings')
        with self.assertRaises(ValueError):
            restore_inspection(self.storage, result['manifest'])

    def test_partial_write_cleanup_preserves_existing_files(self):
        self.add()
        with tempfile.TemporaryDirectory() as directory:
            with patch('manager.inspection.write_report_csv', side_effect=OSError('disk full')):
                with self.assertRaises(OSError):
                    export_inspection(self.snapshot(), directory)
            self.assertEqual(list(Path(directory).iterdir()), [])

    def test_reprocessing_uses_id_before_period_and_target_filter(self):
        self.add(value=0.1)
        self.add(captured='2026-10-31T09:00:00', device_id='B-1')
        self.assertEqual(self.snapshot()['history'], [])

    def test_device_order_case_and_registry_range_priority(self):
        register_device(self.storage, 'a-1', device_name='別機器')
        self.add(hash='lower', device_id='a-1', value=0)
        self.add(hash='upper', value=2)
        self.storage.save_image_truth('upper', scale_min=0, scale_max=3)
        result = self.snapshot(('a-1', 'A-1'))
        self.assertEqual([row['機器番号'] for row in result['rows']], ['A-1', 'a-1'])
        self.assertIn('範囲外の疑い', result['rows'][0]['要確認理由'])
        self.assertEqual(result['rows'][1]['測定値'], 0)
