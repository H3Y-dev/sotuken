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
            stack.enter_context(patch.object(scale, 'locate_value_on_ticks', return_value=zero))
            stack.enter_context(patch.object(scale, 'locate_value_by_extrapolation', return_value=None))
            stack.enter_context(patch.object(scale, '_predict_angle_for_value', return_value=None))
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

    def test_zero_recovery_cannot_reuse_fullscale_point(self):
        result = self.detect(self.candidate(minimum=100), zero=(30, 40))
        self.assertEqual(100, result['min_value'])
        self.assertEqual((10, 20), result['zero_pt'])
        self.assertNotEqual(result['zero_pt'], result['full_pt'])

    def test_zero_recovery_keeps_a_distinct_verified_point(self):
        result = self.detect(self.candidate(minimum=100), zero=(50, 60))
        self.assertEqual(0, result['min_value'])
        self.assertEqual((50, 60), result['zero_pt'])


class ScalePositionExclusionTests(unittest.TestCase):
    def resolve(self, point, *, direct=True, extrapolated=None, synthetic=None):
        import math
        ticks = [dict(angle=math.radians(i * 10)) for i in range(36)]
        with patch.object(scale, 'locate_value_on_ticks', return_value=point if direct else None), \
             patch.object(scale, 'locate_value_by_extrapolation', return_value=extrapolated), \
             patch.object(scale, '_verify_label_near_position', return_value=True), \
             patch.object(scale, '_predict_angle_for_value', return_value=1.0), \
             patch.object(scale, '_synthesize_tick_point', return_value=synthetic), \
             patch.object(scale, '_verify_label_near_position_multi', return_value=True):
            return scale._resolve_scale_position(None, [], ticks, (0, 0), [], 0,
                                                 is_zero=True, exclude_point=(100, 0))

    def test_rejects_same_angle_at_another_radius(self):
        self.assertEqual((None, False), self.resolve((50, 0)))

    def test_rejects_points_within_half_a_tick_across_angle_wrap(self):
        import math
        for angle in (-4, 4):
            with self.subTest(angle=angle):
                point = (100 * math.cos(math.radians(angle)), 100 * math.sin(math.radians(angle)))
                self.assertEqual((None, False), self.resolve(point))

    def test_keeps_distinct_tick(self):
        self.assertEqual(((100, 20), False), self.resolve((100, 20)))

    def test_extrapolation_cannot_reuse_excluded_tick(self):
        self.assertEqual((None, False), self.resolve(None, direct=False, extrapolated=(50, 0)))

    def test_synthesis_cannot_reuse_excluded_tick(self):
        self.assertEqual((None, False), self.resolve(None, direct=False, synthetic=(50, 0)))
