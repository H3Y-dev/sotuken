import math
import json
import unittest
from pathlib import Path

from scale_value_detect import _find_agreeing_result


class TestCandidateSelection(unittest.TestCase):
    def test_field_candidates_32_and_58_select_observed_fifty(self):
        fixtures = json.loads((Path(__file__).parent / 'fixtures' /
                               'ocr_candidates' / 'intermediate.json').read_text(encoding='utf-8'))
        self.assertEqual([f['index'] for f in fixtures], [32, 58])
        for fixture in fixtures:
            with self.subTest(index=fixture['index']):
                selected = _find_agreeing_result(fixture['candidates'], fixture['center'])
                values = [value for angle, value in selected['calibration']]
                self.assertIn(50, values)
                self.assertNotIn(5, values)

    @staticmethod
    def candidate(values, angles=(120, 220, 320, 420)):
        radians = [math.radians(a) for a in angles]
        return dict(min_value=0, max_value=150, n_used=len(values),
                    zero_pt=(math.cos(radians[0]), math.sin(radians[0])),
                    full_pt=(math.cos(radians[-1]), math.sin(radians[-1])),
                    calibration=list(zip(radians, values)))

    def test_split_fifty_loses_to_observed_fifty(self):
        bad = self.candidate([0, 5, 100, 150])
        good = self.candidate([0, 50, 100, 150])
        self.assertIs(_find_agreeing_result([bad, good, bad], (0, 0)), good)

    def test_fewer_points_can_win_with_extrapolated_zero(self):
        bad = self.candidate([0, 5, 100, 150])
        good = self.candidate([0, 50, 100, 150])
        good.update(calibration=good['calibration'][1:], n_used=3)
        self.assertIs(_find_agreeing_result([bad, good], (0, 0)), good)

    def test_nonlinear_scale_is_preserved_without_consistent_alternative(self):
        nonlinear = self.candidate([0, 5, 100, 150])
        other = self.candidate([0, 10, 100, 150])
        self.assertIs(_find_agreeing_result([nonlinear, other], (0, 0)), nonlinear)

    def test_different_endpoint_position_does_not_replace_candidate(self):
        bad = self.candidate([0, 5, 100, 150])
        other = self.candidate([0, 50, 100, 150], (150, 240, 330, 420))
        self.assertIs(_find_agreeing_result([bad, other], (0, 0)), bad)

    def test_no_range_agreement_still_returns_none(self):
        self.assertIsNone(_find_agreeing_result([self.candidate([0, 50, 100, 150])], (0, 0)))

    def test_clockwise_scale_selects_consistent_candidate(self):
        bad = self.candidate([0, 5, 100, 150], (420, 320, 220, 120))
        good = self.candidate([0, 50, 100, 150], (420, 320, 220, 120))
        self.assertIs(_find_agreeing_result([bad, good], (0, 0)), good)

    def test_endpoint_rounding_across_zero_does_not_reject_good_candidate(self):
        bad = self.candidate([0, 5, 100, 150])
        good = self.candidate([0, 50, 100, 150])
        angle, value = good['calibration'][0]
        good['calibration'][0] = (angle - 0.0001, value)
        self.assertIs(_find_agreeing_result([bad, good], (0, 0)), good)
