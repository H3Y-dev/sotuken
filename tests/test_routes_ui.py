from contextlib import chdir
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from manager.storage import Storage
from manager.routes import save_route, save_manifest, list_routes
from tests import test_routes_manifest as fixtures


class RoutesAppTest(unittest.TestCase):
    def test_route_tab_save_edit_delete_and_manifest_only_round(self):
        from streamlit import cache_data, cache_resource
        from streamlit.testing.v1 import AppTest
        cache_data.clear()
        cache_resource.clear()
        self.addCleanup(cache_data.clear)
        self.addCleanup(cache_resource.clear)
        app = Path(__file__).resolve().parents[1] / 'app.py'
        with tempfile.TemporaryDirectory() as directory, chdir(directory), patch(
                'manager.receiver.init_receiver_for_app', return_value={'running': False, 'error': 'test'}):
            storage = Storage('manager.db')
            route = save_route(storage, '巡回A', [dict(id='A', name='計器A'), dict(id='B', name='計器B')])
            save_manifest(storage, 'I-1', dict(fixtures.RoutesManifestTest.manifest(self), route_id=route['route_id'], missing=['B']))
            at = AppTest.from_file(str(app), default_timeout=30).run()
            self.assertFalse(at.exception)
            self.assertEqual([t.label for t in at.tabs], ['読み取り', '記録', '点検結果', '点検ルート'])
            next(s for s in at.selectbox if s.label == '点検（巡回）').select('I-1').run()
            self.assertFalse(at.exception)
            self.assertIn('点検の受信状態: 不足あり', [h.value for h in at.subheader])
            self.assertIn('a.jpg', at.warning[0].value)
            self.assertEqual(at.dataframe[0].value['撮影状態'].tolist(), ['未撮影', '未撮影'])
            next(s for s in at.selectbox if s.label == '編集・配布するルート').select(route['route_id']).run()
            next(t for t in at.text_input if t.label == 'ルート名').set_value('編集済み')
            next(b for b in at.button if b.label == 'ルートを保存').click().run()
            self.assertFalse(at.exception)
            self.assertEqual(list_routes(storage)['routes'][0]['name'], '編集済み')
            next(c for c in at.checkbox if c.label == 'このルートを削除することを確認しました').check().run()
            next(b for b in at.button if b.label == 'ルートを削除').click().run()
            self.assertFalse(at.exception)
            self.assertEqual(list_routes(storage)['routes'], [])
            next(t for t in at.text_input if t.label == 'ルート名').set_value('新ルート')
            next(t for t in at.text_input if t.label == '機器ID（手入力）').set_value('C')
            next(t for t in at.text_input if t.label == '機器名（手入力）').set_value('計器C')
            next(b for b in at.button if b.label == '手入力で追加').click().run()
            next(b for b in at.button if b.label == 'ルートを保存').click().run()
            self.assertFalse(at.exception)
            self.assertEqual(list_routes(storage)['routes'][0]['count'], 1)
