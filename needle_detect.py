"""Houghで得た針候補から、指示針を色で選ぶ補助関数。"""
import math

import cv2
import numpy as np


def _line_length(line):
    """線分の長さを返す。"""
    x1, y1, x2, y2 = line
    return math.hypot(x2 - x1, y2 - y1)


def _is_red_candidate(hsv, line):
    """線分周辺で赤色が十分な割合を占めるかを返す。"""
    h, w = hsv.shape[:2]
    x1, y1, x2, y2 = line

    line_mask = np.zeros((h, w), dtype=np.uint8)
    # Hough線が針の輪郭上に出ることもあるため、中心線の両側2pxも調べる。
    cv2.line(line_mask, (x1, y1), (x2, y2), 255, 5)
    sampled = line_mask > 0
    if not np.any(sampled):
        return False

    hue = hsv[:, :, 0]
    saturation = hsv[:, :, 1]
    value = hsv[:, :, 2]
    # OpenCVのHは0〜179（1単位=2度）。赤は0度をまたぐため0〜10/170〜179
    # （±20度）とし、S>=100（約39%）で白・黒・灰色を除外する。V>=50は
    # 暗部の色相ノイズを除きつつ、暗い赤塗装は残すための下限である。
    red = (((hue <= 10) | (hue >= 170)) &
           (saturation >= 100) & (value >= 50))
    # 5px幅の標本帯では細い針でも赤画素が帯全体の約1割になる。8%未満なら
    # 赤い文字や圧縮ノイズの偶然の混入として扱う。
    return float(np.count_nonzero(red & sampled)) / np.count_nonzero(sampled) >= 0.08


def select_indicator_candidate(img, candidates):
    """
    針候補から指示針を選ぶ。

    候補が1本なら色を見ずに返す。複数候補では赤くない候補を優先し、
    赤以外が無ければ赤針だけの計器とみなして従来どおり最長候補を返す。
    """
    normalized = [tuple(int(v) for v in line) for line in candidates]
    if not normalized:
        return None
    if len(normalized) == 1:
        return normalized[0]

    longest = max(normalized, key=_line_length)
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    if not _is_red_candidate(hsv, longest):
        return longest

    # 針は同じ中心から目盛り帯まで伸びるため、別の針なら最長候補とほぼ
    # 同じ長さになる。ここでは95%以上を「同程度」とし、短い文字・目盛りの
    # 線分を第2の針と誤認して既存の赤針計器を変えないようにする。
    comparable_length = _line_length(longest) * 0.95
    non_red = [line for line in normalized
               if _line_length(line) >= comparable_length and
               not _is_red_candidate(hsv, line)]
    return max(non_red, key=_line_length) if non_red else longest
