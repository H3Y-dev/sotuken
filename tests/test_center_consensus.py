# -*- coding: utf-8 -*-
"""
tests/test_center_consensus.py

resolve_center_consensus に渡す3候補の実際の形式(run_three_candidates.pyより):
- hough:      {'center': (x, y), 'radius': r}
- estimate:   (x, y) のタプル、失敗時 None
- fit_result: {'center': (x, y), 'radius': r, 'method': str}
- ticks:      [{'centroid': (x, y)}, ...] のリスト(グローバル座標系)

img_shape は img.shape そのまま((h, w, ch))を渡している。
"""
import math
import unittest

from center_consensus import resolve_center_consensus

IMG_SHAPE = (480, 640, 3)  # h, w, ch の合成データ用ダミー値


def make_hough(cx, cy, r):
    return {"center": (cx, cy), "radius": r}


def make_fit(cx, cy, r, method="taubin"):
    return {"center": (cx, cy), "radius": r, "method": method}


def make_ticks_around(cx, cy, r, n=8):
    """中心(cx, cy)・半径r の円周上にn個の目盛り重心を合成する"""
    ticks = []
    for i in range(n):
        theta = 2 * math.pi * i / n
        tx = cx + r * math.cos(theta)
        ty = cy + r * math.sin(theta)
        ticks.append({"centroid": (tx, ty)})
    return ticks


class TestResolveCenterConsensus(unittest.TestCase):

    def test_three_candidates_agree_returns_consensus(self):
        """3候補がほぼ一致 -> 'consensus'"""
        hough = make_hough(320, 240, 100)
        estimate = (321, 241)
        fit_result = make_fit(319, 239, 99)
        ticks = make_ticks_around(320, 240, 100)

        center, source = resolve_center_consensus(
            hough, estimate, fit_result, IMG_SHAPE, ticks=ticks
        )
        self.assertIsNotNone(center)
        self.assertEqual(source, "consensus")

    def test_hough_outlier_screw_suspected_returns_fallback_2_agree(self):
        """Hough1つだけ大きく外れる(ネジ誤検出疑い) -> 残り2候補で 'fallback_2_agree'"""
        hough = make_hough(50, 50, 20)  # 盤面中心から大きく離れた小さい円(ネジを想定)
        estimate = (320, 240)
        fit_result = make_fit(321, 241, 100)
        ticks = make_ticks_around(320, 240, 100)

        center, source = resolve_center_consensus(
            hough, estimate, fit_result, IMG_SHAPE, ticks=ticks
        )
        self.assertIsNotNone(center)
        self.assertEqual(source, "fallback_2_agree")

    def test_tick_based_candidates_disagree_returns_none(self):
        """目盛りベース2候補(estimate/fit)が食い違う -> None, None(棄却)"""
        hough = make_hough(320, 240, 100)
        estimate = (100, 100)
        fit_result = make_fit(500, 400, 100)
        ticks = make_ticks_around(320, 240, 100)

        center, source = resolve_center_consensus(
            hough, estimate, fit_result, IMG_SHAPE, ticks=ticks
        )
        self.assertIsNone(center)
        self.assertIsNone(source)

    def test_hough_radius_mismatch_rejects_hough_candidate(self):
        """Hough半径とfit半径が大きく違う -> Hough候補が棄却される"""
        hough = make_hough(320, 240, 250)  # fit側(半径100)と大きく食い違う
        estimate = (321, 241)
        fit_result = make_fit(319, 239, 100)
        ticks = make_ticks_around(320, 240, 100)

        center, source = resolve_center_consensus(
            hough, estimate, fit_result, IMG_SHAPE, ticks=ticks
        )
        self.assertIsNotNone(center)
        self.assertNotEqual(source, "hough")


if __name__ == "__main__":
    unittest.main()
