import math
import os
import sys
import unittest

import cv2
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tick_detect import detect_scale_ticks


def _angle_difference(a, b):
    return abs((a - b + math.pi) % (2.0 * math.pi) - math.pi)


def _make_meter_with_ticks():
    """連結しやすい円弧と、等間隔の放射状目盛りを含む合成盤面を作る。"""
    size = 400
    center = (size // 2, size // 2)
    image = np.full((size, size, 3), 235, dtype=np.uint8)
    angles = [2.0 * math.pi * index / 24.0 for index in range(24)]

    # 円弧は従来の輪郭PCA方式で隣接目盛りを融合させる要因を再現する。
    cv2.circle(image, center, 165, (90, 90, 90), 1, cv2.LINE_AA)
    for index, angle in enumerate(angles):
        length = 32 if index % 4 == 0 else 20
        inner = 165 - length
        p0 = (
            int(round(center[0] + inner * math.cos(angle))),
            int(round(center[1] + inner * math.sin(angle))),
        )
        p1 = (
            int(round(center[0] + 166 * math.cos(angle))),
            int(round(center[1] + 166 * math.sin(angle))),
        )
        cv2.line(image, p0, p1, (20, 20, 20), 2, cv2.LINE_AA)

    # 周期性のない、ランダム位置の細長い背景ノイズ。固定シードで再現可能にする。
    random = np.random.default_rng(20260825)
    noise = []
    while len(noise) < 6:
        x, y = random.integers(20, size - 20, size=2)
        radius = math.hypot(x - center[0], y - center[1])
        if 105 < radius < 180:
            continue  # 目盛り帯そのものにはノイズを重ねない
        dx, dy = random.integers(-26, 27, size=2)
        if abs(dx) + abs(dy) < 20:
            continue
        p1 = (int(np.clip(x + dx, 0, size - 1)),
              int(np.clip(y + dy, 0, size - 1)))
        noise.append(((int(x), int(y)), p1))
    for p0, p1 in noise:
        cv2.line(image, p0, p1, (10, 10, 10), 2, cv2.LINE_AA)

    return image, center, angles


class TestDetectScaleTicksPolar(unittest.TestCase):
    def test_recovers_periodic_ticks_despite_connected_arc(self):
        image, center, expected_angles = _make_meter_with_ticks()

        ticks = detect_scale_ticks(image, center)
        detected_angles = [tick['angle'] for tick in ticks]

        self.assertEqual(len(ticks), len(expected_angles))
        for tick in ticks:
            self.assertEqual(
                set(tick), {'angle', 'centroid', 'line_angle', 'length', 'is_major'})
            self.assertIsInstance(tick['centroid'], tuple)
            self.assertIsInstance(tick['is_major'], bool)
        for expected in expected_angles:
            self.assertLess(
                min(_angle_difference(expected, actual) for actual in detected_angles),
                math.radians(2.0),
            )
        self.assertEqual(sum(tick['is_major'] for tick in ticks), 6)

    def test_rejects_non_periodic_elongated_noise(self):
        image, center, expected_angles = _make_meter_with_ticks()

        ticks = detect_scale_ticks(image, center)

        for tick in ticks:
            self.assertLess(
                min(_angle_difference(tick['angle'], angle) for angle in expected_angles),
                math.radians(2.0),
            )


if __name__ == '__main__':
    unittest.main()
