from contextlib import chdir
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


class WebNavigationTest(unittest.TestCase):
    def test_history_pagination_photos_and_full_export(self):
        import csv
        from streamlit.testing.v1 import AppTest
        from manager.storage import Storage
        app = Path(__file__).resolve().parents[1] / 'app.py'
        with tempfile.TemporaryDirectory() as directory, chdir(directory), patch(
                'manager.receiver.init_receiver_for_app',
                return_value={'running': False, 'error': 'test'}), patch(
                'manager.web_pages_ui.get_thumbnail_path', return_value=None) as thumbnail:
            storage = Storage('manager.db')
            for index in range(205):
                storage.save_reading('meter', f'{index}.jpg', {
                    'stage': 'ok', 'status': 'ok', 'value': index,
                    'inspection_id': 'round', 'inspection_name': '巡回A'})
            at = AppTest.from_file(str(app), default_timeout=30).run()
            next(b for b in at.button if b.label == '巡回A').click().run()
            self.assertFalse(at.exception)
            self.assertEqual(at.radio(key='page').value, '点検')
            self.assertEqual(at.selectbox(key='selected_inspection').value, 'round')
            self.assertIn('受信中', at.selectbox(key='selected_inspection').options[-1])
            self.assertEqual(len(at.dataframe[-1].value), 100)
            thumbnail.assert_not_called()
            at.button(key='more_history').click().run()
            self.assertFalse(at.exception)
            self.assertEqual(len(at.dataframe[-1].value), 200)
            at.button(key='more_history').click().run()
            self.assertEqual(len(at.dataframe[-1].value), 205)
            next(c for c in at.checkbox if c.label == '写真を表示').check().run()
            self.assertFalse(at.exception)
            self.assertEqual(thumbnail.call_count, 20)
            thumbnail.reset_mock()
            next(b for b in at.button if b.label == '写真をさらに表示').click().run()
            self.assertFalse(at.exception)
            self.assertEqual(thumbnail.call_count, 40)
            next(b for b in at.button if b.label == 'CSVを書き出す').click().run()
            with open('readings_export.csv', encoding='utf-8-sig', newline='') as stream:
                self.assertEqual(len(list(csv.DictReader(stream))), 205)

    def test_cached_history_tracks_wal_and_metadata_changes(self):
        from manager.storage import Storage
        from manager.web_data_ui import load_history
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / 'wal.db')
            storage = Storage(path)
            with storage.connection() as conn:
                conn.execute('PRAGMA journal_mode=WAL')
                self.assertEqual(load_history(path), [])
                row_id = storage.save_reading('before', 'a.jpg', {'value': 1, 'stage': 'ok'})
                self.assertEqual(len(load_history(path)), 1)
                conn.execute('UPDATE meter_readings SET device_name=? WHERE id=?', ('after', row_id))
                conn.commit()
                self.assertEqual(load_history(path)[0].device_name, 'after')
                conn.execute('DELETE FROM meter_readings')
                conn.commit()
                self.assertEqual(load_history(path), [])

    def test_only_selected_page_runs(self):
        from streamlit.testing.v1 import AppTest
        app = Path(__file__).resolve().parents[1] / 'app.py'
        with tempfile.TemporaryDirectory() as directory, chdir(directory), patch(
                'manager.receiver.init_receiver_for_app',
                return_value={'running': False, 'error': 'test'}):
            at = AppTest.from_file(str(app), default_timeout=30).run()
            self.assertFalse(at.exception)
            self.assertEqual(at.radio(key='page').value, 'ホーム')
            self.assertNotIn('画像から読み取る', [h.value for h in at.header])
            self.assertNotIn('機器別の推移', [h.value for h in at.header])
            for page, header in [('点検', '点検'), ('機器', '機器の判定'),
                                 ('ルート', None), ('接続・設定', 'スマホの送信先'),
                                 ('手動読み取り(開発用)', '画像から読み取る')]:
                at.radio(key='page').set_value(page).run()
                self.assertFalse(at.exception, page)
                if header:
                    self.assertIn(header, [h.value for h in at.header])
