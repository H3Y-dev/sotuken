"""
評価データの全画像について、検出の中間結果を画像に描き込んで保存する。

## なぜ必要か

2026-08-25、引用誤差0.11%FSで「最も優秀」と評価していた画像
（気密試験_昇圧前圧力計）が、実際にはスケール最大値を150ではなく100と
誤検出し、ゼロ点を盤面外の黒いベゼル上に置いていたことが、人がGUIで
動かして目視したことで発覚した。

**針がたまたま0付近を指していたため引用誤差に現れなかっただけで、
針が中央付近を指す状況では大きく外れる。** 誤差の数値だけを見ていると、
この種の「条件次第で表面化する不具合」を見逃す。

そこで、**誤差の大小にかかわらず全画像の中間結果を描画して並べ**、
毎回の検証で目視できるようにする。

## 使い方

    venv\\Scripts\\python.exe tools_render_overlays.py
    venv\\Scripts\\python.exe tools_render_overlays.py --scope all -o out/

出力される画像に描かれるもの:

  黄色い十字   中心点
  緑の点       目盛り（副目盛り）
  マゼンタの点 目盛り（主目盛り）
  マゼンタの輪 目盛り（格子から合成した主目盛り）
  黄色い丸     ゼロ点
  マゼンタの丸 フルスケール点
  赤い線       検出した針
  左上のテキスト  検出値・真値・引用誤差・検出したスケール範囲

**見るべき点**（過去に実際に見逃した箇所）:

  - ゼロ点・フルスケール点が、盤面外（ベゼルや背景）に乗っていないか
  - 検出された目盛りが、実際の目盛り線の上にあるか（文字・シール・
    配管の上に乗っていないか）
  - 検出したスケール範囲が銘板の表記と一致しているか
  - 針が0付近を指している画像で、ゼロ点が隣の目盛りへずれていないか
"""
from __future__ import print_function

import argparse
import json
import math
import os
import sys

import cv2

import meter_pipeline
from manager.overlay import draw_detection_overlay, imread_ja

DEFAULT_OUT_DIR = 'eval/overlays'


def imwrite_ja(path, img):
    ext = os.path.splitext(path)[1] or '.jpg'
    ok, buf = cv2.imencode(ext, img)
    if ok:
        buf.tofile(path)
    return ok


def _put_lines(img, lines, origin=(20, 40), scale=1.0):
    """背景に黒フチを付けて読みやすくテキストを描く"""
    x, y = origin
    step = int(42 * scale)
    for i, text in enumerate(lines):
        pos = (x, y + i * step)
        cv2.putText(img, text, pos, cv2.FONT_HERSHEY_SIMPLEX, scale,
                    (0, 0, 0), int(6 * scale), cv2.LINE_AA)
        cv2.putText(img, text, pos, cv2.FONT_HERSHEY_SIMPLEX, scale,
                    (255, 255, 255), max(1, int(2 * scale)), cv2.LINE_AA)


def render(entry, base_dir, use_vlm):
    """1枚分の検出結果を描画した画像を返す。読み込めなければ None"""
    path = entry['image']
    if not os.path.isabs(path):
        path = os.path.normpath(os.path.join(base_dir, path))
    img = imread_ja(path)
    if img is None:
        return None, 'image not found'

    result = meter_pipeline.read_meter(img, use_vlm=use_vlm)
    # center/zero_pt/full_pt等の座標は、read_meter内部でクロップ・向き補正
    # した「後」の画像を基準にしている。呼び出し元のimg（クロップ・回転前）
    # にそのまま描画すると座標がズレるため、processed_imgを使う。
    out = draw_detection_overlay(img, result)

    span = abs(entry['max_value'] - entry['min_value'])
    value = result.get('value')
    true_value = entry.get('true_value')
    if value is not None and true_value is not None and span:
        err = abs(value - true_value) / span * 100.0
        err_text = '%.2f %%FS' % err
    else:
        err_text = '-'

    range_ok = (result.get('min_value') == entry['min_value'] and
                result.get('max_value') == entry['max_value'])
    lines = [
        'stage=%s  value=%s  true=%s  err=%s' % (
            result.get('stage'),
            '%.2f' % value if value is not None else '-',
            '%.2f' % true_value if true_value is not None else '-',
            err_text),
        'range detected=%s-%s  true=%s-%s  %s' % (
            result.get('min_value'), result.get('max_value'),
            entry['min_value'], entry['max_value'],
            'OK' if range_ok else '<<< RANGE MISMATCH'),
    ]
    scale_factor = max(1.0, min(out.shape[:2]) / 700.0)
    _put_lines(out, lines, scale=scale_factor)

    return out, None


def main(argv=None):
    parser = argparse.ArgumentParser(
        description='検出の中間結果を全画像分描画して保存する')
    parser.add_argument('groundtruth', nargs='?', default='eval/groundtruth.json')
    parser.add_argument('-o', '--out-dir', default=DEFAULT_OUT_DIR)
    parser.add_argument('--scope', default='round',
                        help='形状で絞る（既定 round、all で全件）')
    parser.add_argument('--no-vlm', action='store_true',
                        help='VLMによる盤面クロップを使わない')
    parser.add_argument('--max-width', type=int, default=1100,
                        help='保存時の最大幅（既定1100）')
    args = parser.parse_args(argv)

    with open(args.groundtruth, encoding='utf-8') as f:
        entries = json.load(f)
    if args.scope != 'all':
        entries = [e for e in entries if e.get('scope', 'round') == args.scope]

    base_dir = os.path.dirname(os.path.abspath(args.groundtruth))
    if not os.path.isdir(args.out_dir):
        os.makedirs(args.out_dir)

    for i, entry in enumerate(entries, 1):
        name = os.path.basename(entry['image'].replace('\\', '/'))
        out, err = render(entry, base_dir, use_vlm=not args.no_vlm)
        if out is None:
            print('[%d/%d] %s : %s' % (i, len(entries), name, err))
            continue
        h, w = out.shape[:2]
        if w > args.max_width:
            s = args.max_width / float(w)
            out = cv2.resize(out, (int(w * s), int(h * s)),
                             interpolation=cv2.INTER_AREA)
        dst = os.path.join(args.out_dir, '%02d_%s.jpg' % (i, os.path.splitext(name)[0]))
        imwrite_ja(dst, out)
        print('[%d/%d] %s -> %s' % (i, len(entries), name, dst))

    print('保存先: %s' % os.path.abspath(args.out_dir))
    return 0


if __name__ == '__main__':
    sys.exit(main())
