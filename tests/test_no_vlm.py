"""--no-vlm 時にVLMへ問い合わせず、結果を再現できることの回帰テスト。"""
import os
import sys
import unittest
from unittest import mock

import cv2
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import meter_pipeline


class TestNoVlmRegression(unittest.TestCase):

    def test_reading_the_same_image_twice_without_vlm_is_reproducible(self):
        image_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            'eval', 'images', 'meter1.png')
        img = cv2.imdecode(np.fromfile(image_path, dtype=np.uint8), cv2.IMREAD_COLOR)
        self.assertIsNotNone(img)

        # --no-vlm の再現性は、内部の補助処理からもVLMを呼ばないことが前提になる。
        with mock.patch('vlm_scale_value.read_min_max') as read_min_max:
            with mock.patch(
                    'vlm_scale_value.check_needle_overlaps_zero') as check_overlap:
                first = meter_pipeline.read_meter(img, use_vlm=False)
                second = meter_pipeline.read_meter(img, use_vlm=False)

        self.assertEqual(0, read_min_max.call_count)
        self.assertEqual(0, check_overlap.call_count)
        for key in ('stage', 'n_ticks', 'min_value', 'max_value', 'value'):
            self.assertEqual(first[key], second[key], key)


if __name__ == '__main__':
    unittest.main()
