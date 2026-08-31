"""GUIへ渡すOCR/VLM診断表示の、画面に依存しない部分をテストする。"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scale_debug_view import build_scale_debug_view, build_scale_flow_model


class TestBuildScaleDebugView(unittest.TestCase):

    def test_shows_each_candidate_and_per_endpoint_source(self):
        auto_scale = {
            'min_value': 0.0,
            'max_value': 100.0,
            'source': 'hybrid',
            'is_confident': True,
            'diagnostics': {
                'ocr': {
                    'available': True,
                    'stable': True,
                    'min_value': 0.0,
                    'max_value': 108.0,
                },
                'vlm': {
                    'enabled': True,
                    'available': True,
                    'min_value': 0.0,
                    'max_value': 100.0,
                },
                'decision': {
                    'relation': 'disagree',
                    'fallback_used': True,
                    'min_source': 'ocr',
                    'max_source': 'vlm',
                    'reason': '最大値だけVLM候補の位置を確認して採用',
                },
            },
        }
        numbers = [
            {'value': 0.0, 'score': 0.95, 'x': 10.0, 'y': 20.0},
            {'value': 108.0, 'score': 0.82, 'x': 30.0, 'y': 40.0},
        ]

        view = build_scale_debug_view(auto_scale, numbers)

        self.assertEqual('OCR', view['decision_rows'][0][0])
        self.assertEqual('0', view['decision_rows'][0][1])
        self.assertEqual('108', view['decision_rows'][0][2])
        self.assertEqual('LLM', view['decision_rows'][1][0])
        self.assertIn('最小=OCR', view['summary'])
        self.assertIn('最大=LLM', view['summary'])
        self.assertIn('あり', view['summary'])
        self.assertEqual(('1', '0', '0.95', '(10, 20)'), view['ocr_rows'][0])
        self.assertTrue(any('不一致' in line for line in view['trace_lines']))
        self.assertTrue(any('最大値だけVLM候補' in line for line in view['trace_lines']))

    def test_shows_vlm_disabled_without_claiming_it_was_wrong(self):
        auto_scale = {
            'min_value': 0.0,
            'max_value': 100.0,
            'source': 'ocr_tick',
            'is_confident': True,
            'diagnostics': {
                'ocr': {'available': True, 'stable': True,
                        'min_value': 0.0, 'max_value': 100.0},
                'vlm': {'enabled': False, 'available': False,
                        'min_value': None, 'max_value': None},
                'decision': {'relation': 'disabled', 'fallback_used': False,
                             'min_source': 'ocr', 'max_source': 'ocr',
                             'reason': 'LLMを無効化してOCRのみで判定'},
            },
        }

        view = build_scale_debug_view(auto_scale, [])

        self.assertIn('未実行', view['decision_rows'][1][3])
        self.assertNotIn('誤り', view['decision_rows'][1][3])


class TestBuildScaleFlowModel(unittest.TestCase):
    """OCRとVLMを別ノードにし、実際に通った条件分岐を示す。"""

    @staticmethod
    def _active_edges(model):
        return {edge['id'] for edge in model['edges'] if edge['active']}

    @staticmethod
    def _diagnostics(ocr_available=True, ocr_stable=True,
                     vlm_enabled=True, vlm_available=True,
                     relation='agree', min_source='ocr', max_source='ocr',
                     fallback_used=False):
        return {
            'ocr': {
                'available': ocr_available,
                'stable': ocr_stable,
                'min_value': 0.0 if ocr_available else None,
                'max_value': 108.0 if ocr_available else None,
                'numbers': [{'value': 0.0}, {'value': 108.0}]
                if ocr_available else [],
            },
            'vlm': {
                'enabled': vlm_enabled,
                'available': vlm_available,
                'min_value': 0.0 if vlm_available else None,
                'max_value': 100.0 if vlm_available else None,
            },
            'decision': {
                'relation': relation,
                'fallback_used': fallback_used,
                'min_source': min_source,
                'max_source': max_source,
            },
        }

    def test_has_separate_ocr_and_vlm_detection_nodes(self):
        model = build_scale_flow_model(
            {'source': 'ocr_tick'}, self._diagnostics())
        labels = {node['id']: node['label'] for node in model['nodes']}

        self.assertIn('OCR数字検出', labels['ocr_detect'])
        self.assertIn('VLM検出', labels['vlm_detect'])
        self.assertNotEqual(labels['ocr_detect'], labels['vlm_detect'])
        self.assertTrue(any('OCR安定' in note and 'フォールバック' in note
                            for note in model['condition_notes']))
        self.assertTrue(any('VLM未取得' in note and '手動選択' in note
                            for note in model['condition_notes']))

    def test_highlights_stable_ocr_then_hybrid_fallback_path(self):
        diagnostics = self._diagnostics(
            relation='disagree', min_source='ocr', max_source='vlm',
            fallback_used=True)

        model = build_scale_flow_model({'source': 'hybrid'}, diagnostics)

        self.assertEqual(
            {'ocr_to_check', 'check_stable_to_vlm', 'vlm_stable_to_compare',
             'compare_disagree_to_verify', 'verify_ok_to_vlm'},
            self._active_edges(model))
        labels = {edge['label'] for edge in model['edges']}
        self.assertIn('不一致', labels)
        self.assertIn('位置確認OK', labels)
        nodes = {node['id']: node for node in model['nodes']}
        self.assertEqual(('一部採用', 'active'),
                         (nodes['adopt_ocr']['status'],
                          nodes['adopt_ocr']['state']))
        self.assertEqual(('一部採用', 'active'),
                         (nodes['adopt_vlm']['status'],
                          nodes['adopt_vlm']['state']))

    def test_highlights_unstable_ocr_to_vlm_fallback_path(self):
        diagnostics = self._diagnostics(
            ocr_stable=False, relation='disagree',
            min_source='vlm', max_source='vlm', fallback_used=True)

        model = build_scale_flow_model({'source': 'vlm'}, diagnostics)

        self.assertEqual(
            {'ocr_to_check', 'check_unstable_to_vlm',
             'vlm_fallback_to_verify', 'verify_ok_to_vlm'},
            self._active_edges(model))

    def test_vlm_unavailable_branches_to_existing_ocr_candidate(self):
        diagnostics = self._diagnostics(
            vlm_available=False, relation='vlm_unavailable')

        model = build_scale_flow_model({'source': 'ocr_tick'}, diagnostics)

        self.assertIn('vlm_unavailable_to_ocr', self._active_edges(model))
        edge = next(edge for edge in model['edges']
                    if edge['id'] == 'vlm_unavailable_to_ocr')
        self.assertIn('OCR候補あり', edge['label'])

    def test_both_detection_failures_branch_to_manual_selection(self):
        diagnostics = self._diagnostics(
            ocr_available=False, ocr_stable=False,
            vlm_available=False, relation='no_result',
            min_source=None, max_source=None)

        model = build_scale_flow_model(None, diagnostics)

        self.assertIn('vlm_unavailable_to_manual', self._active_edges(model))
        manual = next(node for node in model['nodes'] if node['id'] == 'manual')
        self.assertEqual('active', manual['state'])


if __name__ == '__main__':
    unittest.main()
