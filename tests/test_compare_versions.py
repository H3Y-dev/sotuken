"""比較評価スクリプトの副作用を持たない処理を固定するテスト。"""
import os
import sys
import unittest


sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import compare_versions


class TestBuildComparisonRows(unittest.TestCase):

    def test_builds_display_rows_from_evaluation_summaries(self):
        results = [
            {
                'version': 'v4',
                'summary': {
                    'total': 10,
                    'read_ok': 8,
                    'within_tolerance': 6,
                    'mean_reference_error': 2.345,
                    'median_reference_error': 1.5,
                    'catastrophic_count': 1,
                },
            },
        ]

        rows = compare_versions.build_comparison_rows(results)

        self.assertEqual([
            {
                'version': 'v4',
                'read_ok': '8 / 10',
                'within_tolerance': '6 / 10',
                'mean_reference_error': '2.35',
                'median_reference_error': '1.50',
                'catastrophic_count': '1',
            },
        ], rows)

    def test_missing_metrics_are_rendered_as_hyphens(self):
        rows = compare_versions.build_comparison_rows([
            {'version': 'v0', 'summary': {}},
        ])

        self.assertEqual('-', rows[0]['read_ok'])
        self.assertEqual('-', rows[0]['within_tolerance'])
        self.assertEqual('-', rows[0]['mean_reference_error'])
        self.assertEqual('-', rows[0]['median_reference_error'])
        self.assertEqual('-', rows[0]['catastrophic_count'])


class TestBuildPerImageErrorRows(unittest.TestCase):

    def test_builds_rows_for_each_image_and_version(self):
        results = [
            {
                'version': 'v1',
                'results': [
                    {'image': 'b.jpg', 'reference_error': 1.234},
                    {'image': 'a.jpg', 'reference_error': None},
                ],
            },
            {
                'version': 'v2',
                'results': [
                    {'image': 'a.jpg', 'reference_error': 2.0},
                    {'image': 'b.jpg', 'reference_error': 12.345},
                ],
            },
        ]

        rows = compare_versions.build_per_image_error_rows(results)

        self.assertEqual([
            {'image': 'a.jpg', 'v1': '-', 'v2': '2.00'},
            {'image': 'b.jpg', 'v1': '1.23', 'v2': '12.35'},
        ], rows)


class TestV4V5ValuesMatch(unittest.TestCase):

    def test_returns_true_when_each_image_has_the_same_reading(self):
        v4 = {
            'results': [
                {'image': 'a.jpg', 'value': 1.25},
                {'image': 'b.jpg', 'value': None},
            ],
        }
        v5 = {
            'results': [
                {'image': 'b.jpg', 'value': None},
                {'image': 'a.jpg', 'value': 1.25},
            ],
        }

        self.assertTrue(compare_versions.v4_v5_values_match(v4, v5))

    def test_returns_false_when_a_reading_differs(self):
        v4 = {'results': [{'image': 'a.jpg', 'value': 1.25}]}
        v5 = {'results': [{'image': 'a.jpg', 'value': 1.50}]}

        self.assertFalse(compare_versions.v4_v5_values_match(v4, v5))


if __name__ == '__main__':
    unittest.main()
