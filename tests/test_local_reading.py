import math
import unittest

from local_reading import cross_check_diff_fs, read_local


def point(degrees, value, score=0.9, synthetic=False):
    return dict(angle=math.radians(degrees), value=value, score=score,
                synthetic=synthetic)


class LocalReadingTest(unittest.TestCase):
    def test_cw_bracket_across_angle_wrap(self):
        points = [point(135, 0), point(225, 50), point(315, 100), point(45, 150)]
        reading = read_local(points, math.radians(270))
        self.assertTrue(reading['cw'])
        self.assertEqual(reading['value'], 75)
        self.assertEqual(reading['bracket']['a']['value'], 50)
        self.assertEqual(reading['bracket']['b']['value'], 100)

    def test_ccw(self):
        reading = read_local([point(135, 100), point(225, 50), point(315, 0)], math.pi)
        self.assertFalse(reading['cw'])
        self.assertAlmostEqual(reading['value'], 75)

    def test_two_points(self):
        for points in ([point(10, 0), point(90, 100)],
                       [point(90, 0), point(10, 100)]):
            self.assertAlmostEqual(read_local(points, math.radians(50))['value'], 50)

    def test_no_extrapolation(self):
        points = [point(20, 0), point(80, 50), point(140, 100)]
        for angle in (10, 150, 300):
            self.assertIsNone(read_local(points, math.radians(angle)))

    def test_last_number_has_no_next_bracket(self):
        points = [point(20, 0), point(80, 50), point(140, 100)]
        self.assertIsNone(read_local(points, math.radians(140)))

    def test_on_number_uses_next_and_snaps_within_tick_tolerance(self):
        points = [point(20, 0), point(80, 50), point(140, 100)]
        for angle in (79.9, 80, 80.1):
            reading = read_local(points, math.radians(angle), tick_spacing=math.radians(5))
            self.assertEqual(reading['value'], 50)
            self.assertEqual(reading['bracket']['a']['value'], 50)
            self.assertEqual(reading['bracket']['b']['value'], 100)

    def test_survivors_preferred_and_duplicate_uses_highest_score(self):
        points = [point(20, 0), point(80, 50, .3), point(82, 50, .95),
                  point(140, 100), point(100, 123)]
        reading = read_local(points, math.radians(110), calibration=[
            (math.radians(20), 0), (math.radians(82), 50), (math.radians(140), 100)])
        self.assertEqual(reading['bracket']['a']['score'], .95)
        self.assertEqual(reading['bracket']['b']['value'], 100)

    def test_tied_direction_and_insufficient_points_fail(self):
        self.assertIsNone(read_local([], 0))
        self.assertIsNone(read_local([point(20, 0)], 0))
        self.assertIsNone(read_local([point(20, 0), point(80, 100), point(140, 50)], 1))

    def test_missing_labels_do_not_move_calibrated_seam(self):
        for points, needle in (([point(135, 0), point(225, 50), point(45, 150)], 270),
                               ([point(45, 0), point(315, 50), point(135, 150)], 270)):
            reading = read_local(points, math.radians(needle),
                                 calibration=[(p['angle'], p['value']) for p in points])
            self.assertAlmostEqual(reading['value'], 75)
            self.assertEqual(reading['bracket']['a']['value'], 50)
            self.assertEqual(reading['bracket']['b']['value'], 150)

    def test_bound_points_use_tick_arc_when_labels_are_sparse(self):
        points = [point(135, 0), point(225, 50), point(45, 150)]
        ticks = [math.radians(a) for a in range(135, 406, 15)]
        reading = read_local(points, math.radians(270), tick_angles=ticks)
        self.assertAlmostEqual(reading['value'], 75)
        self.assertIsNone(read_local(points, math.radians(90), tick_angles=ticks))

    def test_calibration_keeps_coordinate_metadata_over_other_duplicate(self):
        points = [point(20, 0), point(80, 50, .6, True), point(100, 50, .99), point(140, 100)]
        reading = read_local(points, math.radians(110), calibration=[
            (math.radians(20), 0), (math.radians(80), 50), (math.radians(140), 100)])
        self.assertEqual(reading['bracket']['a'], points[1])

    def test_duplicate_bound_values_use_highest_ocr_score(self):
        points = [point(20, 0), point(60, 50, .3), point(80, 50, .95), point(140, 100)]
        reading = read_local(points, math.radians(110))
        self.assertAlmostEqual(reading['value'], 75)
        self.assertEqual(reading['bracket']['a'], points[2])

    def test_first_endpoint_and_non_finite_input(self):
        points = [point(20, 0), point(80, 50), point(140, 100)]
        self.assertEqual(read_local(points, math.radians(20))['value'], 0)
        self.assertIsNone(read_local(points, math.nan))
        self.assertAlmostEqual(read_local(points + [point(100, math.inf)], math.radians(50))['value'], 25)

    def test_unknown_minor_tick_spacing_does_not_snap_to_label(self):
        points = [point(20, 0), point(80, 50), point(140, 100)]
        reading = read_local(points, math.radians(75))
        self.assertAlmostEqual(reading['value'], 50 * 55 / 60)

    def test_cross_check_is_percent_of_full_span(self):
        self.assertEqual(cross_check_diff_fs(52.5, 50, 0, 100), 2.5)
        self.assertGreater(cross_check_diff_fs(52.5001, 50, 0, 100), 2.5)
        self.assertEqual(cross_check_diff_fs(1, 2, -10, 10), 5)
        self.assertIsNone(cross_check_diff_fs(1, 2, 0, 0))
