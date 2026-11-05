import io
import os
import tempfile
import unittest
from contextlib import contextmanager
from datetime import date
from pathlib import Path
from unittest.mock import patch

from manager.devices import register_device
from manager.inspection_ui import (default_inspection_id, device_choices, missing_devices,
                                   preview_inspection, save_inspection)
from manager.storage import Storage


@contextmanager
def chdir(path):
    old = os.getcwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(old)


def populate(storage):
    register_device(storage, 'A-1', device_name='圧力計', unit='MPa', min_value=0, max_value=1)
    register_device(storage, 'B-1', device_name='温度計', unit='C')
    storage.save_reading('圧力計', 'a.jpg', dict(value=0.5, stage='ok', status='ok', device_id='A-1',
                         captured_at='2026-10-30T09:00:00', received_at='2026-10-30T10:00:00'),
                         image_sha256='h1')


class InspectionUiLogicTests(unittest.TestCase):
    def setUp(self):
        self.storage = Storage(':memory:')
        self.addCleanup(self.storage._conn.close)
        populate(self.storage)

    def test_choices_preview_missing_and_save(self):
        self.assertEqual(list(device_choices(self.storage)), ['A-1', 'B-1'])
        result, table = preview_inspection(self.storage, 'T-1', date(2026, 10, 30), date(2026, 10, 30),
                                           ['A-1', 'B-1'])
        self.assertEqual([row['機器番号'] for row in table], ['A-1'])
        self.assertEqual(table[0]['測定方法'], '自動')
        self.assertEqual(missing_devices(result), ['B-1'])
        with tempfile.TemporaryDirectory() as tmp:
            paths = save_inspection(result, tmp)
            self.assertEqual(len(paths), 3)
            self.assertTrue(all(Path(p).exists() for p in paths.values()))
            with self.assertRaises(FileExistsError):
                save_inspection(result, tmp)

    def test_invalid_period_and_id(self):
        with self.assertRaises(ValueError):
            preview_inspection(self.storage, 'T-1', date(2026, 10, 31), date(2026, 10, 30), ['A-1'])
        with self.assertRaises(ValueError):
            preview_inspection(self.storage, 'a/b', date(2026, 10, 30), date(2026, 10, 30), ['A-1'])
        self.assertTrue(default_inspection_id().startswith('INS-'))


class InspectionAppTest(unittest.TestCase):
    def test_tab_preview_and_export(self):
        from streamlit import cache_data, cache_resource
        from streamlit.testing.v1 import AppTest
        cache_data.clear()
        cache_resource.clear()
        self.addCleanup(cache_data.clear)
        self.addCleanup(cache_resource.clear)
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        storage = Storage(str(root / 'manager.db'))
        populate(storage)
        out = root / 'exports'
        app_path = Path(__file__).resolve().parents[1] / 'app.py'
        at = AppTest.from_file(str(app_path), default_timeout=30)
        with chdir(root), \
             patch('manager.receiver.init_receiver_for_app', return_value=dict(running=False, error='t', url='t', token='t')), \
             patch('manager.export._documents_dir', return_value=out):
            at.run()
            self.assertEqual(len(at.exception), 0, str(at.exception))
            at.date_input(key='insp_from').set_value(date(2026, 10, 30))
            at.date_input(key='insp_to').set_value(date(2026, 10, 30))
            at.text_input(key='insp_id').set_value('UI-1')
            at.run()
            self.assertEqual(len(at.exception), 0, str(at.exception))
            self.assertIn('期間内に撮影が無い機器: B-1', [w.value for w in at.warning])
            at.button(key='insp_export').click().run()
            self.assertEqual(len(at.exception), 0, str(at.exception))
            self.assertEqual(len(list((out / 'メーター点検').glob('*UI-1*'))), 3)
            at.button(key='insp_export').click().run()
            self.assertTrue(any('書き出せませんでした' in e.value for e in at.error))


if __name__ == '__main__':
    unittest.main()