import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
from contextlib import chdir
from types import SimpleNamespace

from manager.pending_images import pending_images
from manager.routes import _file_hash


class PendingImagesTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.incoming = Path(self.tmp.name)
        self.storage = Mock()
        self.storage.get_processed_hashes.return_value = set()
        _file_hash.cache_clear()

    def test_empty_or_missing_directory(self):
        self.assertEqual((0, []), pending_images(self.incoming, self.storage))
        self.assertEqual((0, []), pending_images(self.incoming / 'missing', self.storage))

    def test_unprocessed_images_and_preview(self):
        for index in range(7):
            (self.incoming / f'{index}.JPG').write_bytes(str(index).encode())
        self.assertEqual((7, [f'{i}.JPG' for i in range(5)]),
                         pending_images(self.incoming, self.storage))

    def test_processed_content_is_excluded_even_with_another_name(self):
        (self.incoming / 'renamed.png').write_bytes(b'processed')
        self.storage.get_processed_hashes.return_value = {hashlib.sha256(b'processed').hexdigest()}
        self.assertEqual((0, []), pending_images(self.incoming, self.storage))

    def test_part_sidecar_and_directory_are_excluded(self):
        (self.incoming / 'image.png.part').write_bytes(b'partial')
        (self.incoming / 'image.json').write_text('{}')
        (self.incoming / 'directory.png').mkdir()
        self.assertEqual((0, []), pending_images(self.incoming, self.storage))

    def test_same_name_with_new_content_is_pending(self):
        path = self.incoming / 'same.png'
        path.write_bytes(b'old')
        self.storage.get_processed_hashes.return_value = {hashlib.sha256(b'old').hexdigest()}
        self.assertEqual((0, []), pending_images(self.incoming, self.storage))
        path.write_bytes(b'new image')
        self.assertEqual((1, ['same.png']), pending_images(self.incoming, self.storage))

    def test_two_names_with_same_unprocessed_content_count_as_files(self):
        for name in ('a.png', 'b.png'):
            (self.incoming / name).write_bytes(b'same')
        self.assertEqual((2, ['a.png', 'b.png']), pending_images(self.incoming, self.storage))

    def test_unchanged_file_reuses_hash_but_rechecks_database(self):
        (self.incoming / 'image.png').write_bytes(b'image')
        digest = hashlib.sha256(b'image').hexdigest()
        with patch('manager.batch.calculate_file_hash', return_value=digest) as calculate:
            self.assertEqual(1, pending_images(self.incoming, self.storage)[0])
            self.storage.get_processed_hashes.return_value = {digest}
            self.assertEqual(0, pending_images(self.incoming, self.storage)[0])
        calculate.assert_called_once()


class RecordsRefreshAppTests(unittest.TestCase):
    def test_refresh_reloads_records_inspections_and_pending_count(self):
        from streamlit import cache_data, cache_resource
        from streamlit.testing.v1 import AppTest
        from manager.storage import Storage

        app = Path(__file__).resolve().parents[1] / 'app.py'
        cache_data.clear()
        cache_resource.clear()
        self.addCleanup(cache_data.clear)
        self.addCleanup(cache_resource.clear)
        with tempfile.TemporaryDirectory() as directory, chdir(directory):
            incoming = Path(directory) / 'incoming'
            incoming.mkdir()
            image = incoming / 'new.png'
            image.write_bytes(b'new image')
            receiver = {'running': False, 'error': 'test',
                        'server': SimpleNamespace(incoming_dir=str(incoming))}
            with patch('manager.receiver.init_receiver_for_app', return_value=receiver):
                at = AppTest.from_file(str(app), default_timeout=30).run()
                self.assertFalse(at.exception)
                self.assertIn('記録', [tab.label for tab in at.tabs])
                self.assertIn('読み取り中 1枚', [item.value for item in at.info])
                auto = next(c for c in at.checkbox if c.label == '自動更新(5秒ごと)')
                self.assertFalse(auto.value)
                storage = Storage('manager.db')
                storage.save_reading('new meter', str(image),
                    {'stage': 'ok', 'status': 'ok', 'value': 1,
                     'inspection_id': 'new-round', 'inspection_name': 'new round'},
                    image_sha256=hashlib.sha256(b'new image').hexdigest())
                at.button(key='refresh_records').click().run()
                self.assertFalse(at.exception)
                self.assertNotIn('読み取り中 1枚', [item.value for item in at.info])
                self.assertTrue(any('全1件' in item.value for item in at.caption))
                inspection = next(s for s in at.selectbox if s.label == '点検（巡回）')
                self.assertTrue(any('new round' in option for option in inspection.options))
                next(c for c in at.checkbox if c.label == '自動更新(5秒ごと)').check().run()
                self.assertFalse(at.exception)
                self.assertTrue(next(c for c in at.checkbox if c.label == '自動更新(5秒ごと)').value)
