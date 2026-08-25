import math
import os
import sys
import unittest
from unittest.mock import patch

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


def _make_meter_with_ticks_and_numerals():
    """周期的な数字より、放射状に続く目盛りを選ぶ合成盤面を作る。"""
    size = 480
    center = (size // 2, size // 2)
    image = np.full((size, size, 3), 235, dtype=np.uint8)
    tick_radius = 190
    angles = []

    # 実写真と同様に、目盛りの両端を結ぶ2本の円弧を描く。
    cv2.circle(image, center, tick_radius, (90, 90, 90), 1, cv2.LINE_AA)
    cv2.circle(image, center, tick_radius - 32, (90, 90, 90), 1, cv2.LINE_AA)

    # 外周の目盛りは、実写で針や反射に隠れる状況を再現して一部を欠落させる。
    for index in range(24):
        if index % 4 == 3:
            continue
        angle = 2.0 * math.pi * index / 24.0
        angles.append(angle)
        length = 44 if index % 4 == 0 else 32
        inner = tick_radius - length
        p0 = (
            int(round(center[0] + inner * math.cos(angle))),
            int(round(center[1] + inner * math.sin(angle))),
        )
        p1 = (
            int(round(center[0] + tick_radius * math.cos(angle))),
            int(round(center[1] + tick_radius * math.sin(angle))),
        )
        cv2.line(image, p0, p1, (130, 130, 130), 1, cv2.LINE_AA)

    # 内側の濃い数字も角度方向に周期性を持ち、現行実装ではこちらが勝つ。
    for index, value in enumerate(range(0, 160, 10)):
        angle = 2.0 * math.pi * index / 16.0 - math.pi / 2.0
        label_radius = 130
        x = int(round(center[0] + label_radius * math.cos(angle)))
        y = int(round(center[1] + label_radius * math.sin(angle)))
        label = str(value)
        (text_width, text_height), _ = cv2.getTextSize(
            label, cv2.FONT_HERSHEY_SIMPLEX, 1.0, 2)
        cv2.putText(
            image, label, (x - text_width // 2, y + text_height // 2),
            cv2.FONT_HERSHEY_SIMPLEX, 1.0, (10, 10, 10), 2, cv2.LINE_AA,
        )

    return image, center, angles, tick_radius


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

    def test_prefers_radial_ticks_over_periodic_numerals(self):
        image, center, expected_angles, tick_radius = (
            _make_meter_with_ticks_and_numerals())

        # Hough円の成否ではなく、同じ探索範囲にある2つの周期帯を比較する。
        with patch('tick_detect._dial_radius', return_value=205.0):
            ticks = detect_scale_ticks(image, center)
        detected_angles = [tick['angle'] for tick in ticks]
        detected_radii = [
            math.hypot(tick['centroid'][0] - center[0],
                       tick['centroid'][1] - center[1])
            for tick in ticks
        ]

        self.assertEqual(len(ticks), len(expected_angles))
        self.assertGreater(np.median(detected_radii), tick_radius - 30)
        self.assertEqual(sum(tick['is_major'] for tick in ticks), 6)
        for expected in expected_angles:
            self.assertLess(
                min(_angle_difference(expected, actual)
                    for actual in detected_angles),
                math.radians(2.0),
            )


if __name__ == '__main__':
    unittest.main()
