"""指示針と赤い管理指針を色で区別する小さな単体テスト。"""
import os
import sys
import unittest

import cv2
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from needle_detect import select_indicator_candidate


class TestSelectIndicatorCandidate(unittest.TestCase):

    def test_prefers_non_red_candidate_when_white_and_red_needles_exist(self):
        """複数候補なら、赤い管理指針より白い指示針を選ぶ。"""
        img = np.zeros((160, 160, 3), dtype=np.uint8)
        white_line = (80, 80, 10, 80)
        red_line = (80, 80, 130, 30)
        cv2.line(img, white_line[:2], white_line[2:], (255, 255, 255), 5)
        cv2.line(img, red_line[:2], red_line[2:], (0, 0, 255), 5)

        chosen = select_indicator_candidate(img, [red_line, white_line])

        self.assertEqual(chosen, white_line)

    def test_keeps_a_single_red_candidate(self):
        """赤針だけの計器では、色を理由に針を捨てない。"""
        img = np.zeros((160, 160, 3), dtype=np.uint8)
        red_line = (80, 80, 130, 30)
        cv2.line(img, red_line[:2], red_line[2:], (0, 0, 255), 5)

        chosen = select_indicator_candidate(img, [red_line])

        self.assertEqual(chosen, red_line)


if __name__ == '__main__':
    unittest.main()
