"""範囲一致による信頼度の上書きと、0点補完の退行を防ぐ。"""
from contextlib import ExitStack
import unittest
from unittest.mock import patch

import scale_value_detect as scale


class ScaleResidualTests(unittest.TestCase):
    def detect(self, candidate, zero=None):
        with ExitStack() as stack:
            stack.enter_context(patch.object(scale.tick_detect, 'apply_clahe',
                                             side_effect=lambda img, _clip: img))
            stack.enter_context(patch.object(scale.tick_detect, 'detect_scale_ticks', return_value=[]))
            stack.enter_context(patch.object(scale, '_run_ocr_tick', return_value=candidate))
            stack.enter_context(patch.object(scale, 'read_scale_numbers', return_value=[]))
            stack.enter_context(patch.object(scale, 'refine_major_ticks_from_numbers', return_value=[]))
            stack.enter_context(patch.object(scale, '_recheck_primary_scale', return_value=(None, None, None)))
            stack.enter_context(patch.object(scale, '_resolve_scale_position', return_value=(zero, False)))
            return scale.detect_scale_values(object(), [], (0, 0), use_vlm=False)

    def candidate(self, confident=False, minimum=0):
        return dict(zero_pt=(10, 20), full_pt=(30, 40), min_value=minimum,
                    max_value=400, n_used=4, n_total=4, is_confident=confident)

    def test_matching_ranges_preserve_low_confidence(self):
        result = self.detect(self.candidate())
        self.assertFalse(result['is_confident'])
        self.assertEqual((0, 400), (result['min_value'], result['max_value']))

    def test_matching_ranges_preserve_verified_confidence(self):
        result = self.detect(self.candidate(confident=True))
        self.assertTrue(result['is_confident'])

    def test_missing_confidence_is_not_promoted(self):
        candidate = self.candidate()
        candidate.pop('is_confident')
        self.assertFalse(self.detect(candidate)['is_confident'])
