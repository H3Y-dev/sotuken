import unittest
from label_tool import build_label_record

class TestLabelTool(unittest.TestCase):
    def test_build_label_record_normal(self):
        image_path = 'C:/sotuken/sample/meter1.png'
        image_size = (337, 330)
        points = {
            'center': (168, 165),
            'zero': (80, 260),
            'full': (260, 260),
            'needle': (60, 150)
        }
        numbered_ticks = [{'value': 0, 'x': 80, 'y': 260}]
        form = {
            'labeler': 'SR',
            'labeled_at': '2026-10-28T13:05:00',
            'meter_id': 'meter1',
            'condition': '正面',
            'scope': 'round',
            'unit': '℃',
            'major_step': 10,
            'min_value': 0.0,
            'max_value': 150.0,
            'eye_value': None,
            'unlabelable': False
        }
        computed = {'true_value': 21.0}

        record = build_label_record(image_path, image_size, points, numbered_ticks, form, computed)
        self.assertIsNotNone(record)
        self.assertEqual(record['labeler'], 'SR')
        self.assertEqual(record['true_value'], 21.0)
        self.assertFalse(record['unlabelable'])
        self.assertEqual(record['points']['center'], [168, 165])
        self.assertEqual(record['points']['zero_pt'], [80, 260])
        self.assertEqual(record['points']['full_pt'], [260, 260])
        self.assertEqual(record['points']['needle_tip'], [60, 150])
        self.assertEqual(record['points']['numbered_ticks'], [{'value': 0, 'x': 80, 'y': 260}])

    def test_build_label_record_unlabelable(self):
        image_path = 'C:/sotuken/sample/meter1.png'
        image_size = (337, 330)
        points = {'center': (168, 165)}
        numbered_ticks = []
        form = {
            'labeler': 'SR',
            'unlabelable': True
        }
        computed = {'true_value': 21.0}

        record = build_label_record(image_path, image_size, points, numbered_ticks, form, computed)
        self.assertIsNotNone(record)
        self.assertTrue(record['unlabelable'])
        self.assertIsNone(record['true_value'])
        self.assertIsNone(record['points'])

    def test_build_label_record_empty_labeler(self):
        form = {'labeler': '   ', 'unlabelable': False}
        record = build_label_record('dummy.png', (100, 100), {}, [], form, {})
        self.assertIsNone(record)

if __name__ == '__main__':
    unittest.main()
