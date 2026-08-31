"""GUIへ渡すOCR/VLM診断表示の、画面に依存しない部分をテストする。"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scale_debug_view import build_scale_debug_view


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


if __name__ == '__main__':
    unittest.main()
