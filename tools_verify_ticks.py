"""T1-3検証用（Claude専用・エージェントには触らせない）。"""
import glob
import math
import os
import sys

import cv2
import numpy as np

REPO = r'C:\卒研\git_stk\sotuken'
sys.path.insert(0, REPO)
os.chdir(REPO)

import tick_detect


def load(p):
    return cv2.imdecode(np.fromfile(p, dtype=np.uint8), cv2.IMREAD_COLOR)


paths = sorted(glob.glob(r'C:\卒研\images\recieved_meter\*.jpg')) + [
    'eval/images/meter1.png', 'eval/images/meter2.jpg', 'eval/images/meter3.png']

print('%-14s %5s %9s %8s %10s' % ('image', 'n', 'r_med/sh', 'CV', 'within10%'))
print('-' * 52)
for i, p in enumerate(paths):
    label = 'company%d' % i if 'recieved' in p else os.path.basename(p)[:14]
    img = load(p)
    if img is None:
        print('%-14s SKIP' % label)
        continue
    c = tick_detect.auto_detect_center(img)
    if c is None:
        print('%-14s center=None' % label)
        continue
    enh = tick_detect.apply_clahe(img, clip_limit=2.0)
    try:
        ticks = tick_detect.detect_scale_ticks(enh, (c[0], c[1]))
    except Exception as exc:
        print('%-14s ERROR %s' % (label, exc))
        continue
    if not ticks:
        print('%-14s %5d' % (label, 0))
        continue
    short = min(img.shape[:2])
    rs = [math.hypot(t['centroid'][0] - c[0], t['centroid'][1] - c[1]) for t in ticks]
    srt = sorted(rs)
    med = srt[len(srt) // 2]
    mean = sum(rs) / len(rs)
    sd = (sum((r - mean) ** 2 for r in rs) / len(rs)) ** 0.5
    w10 = sum(1 for r in rs if abs(r - med) <= med * 0.10)
    print('%-14s %5d %9.3f %8.3f %6d/%d' % (label, len(ticks), med / short,
                                            sd / mean if mean else 0, w10, len(ticks)))
