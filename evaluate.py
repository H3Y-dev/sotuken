"""
読み取り精度を自動で測る評価スクリプト。

正解値を書いた一覧ファイルを読み、各画像を自動読み取りにかけて、
結果との誤差を集計する。アルゴリズムを変更したときに、
良くなったのか悪くなったのかを数値で判断するために使う。

使い方:
    venv\\Scripts\\python.exe evaluate.py eval/groundtruth.json
    venv\\Scripts\\python.exe evaluate.py eval/groundtruth.json --no-vlm
    venv\\Scripts\\python.exe evaluate.py eval/groundtruth.json -o eval/report.json

正解ファイル（JSON）の形式:
    [
      {
        "image": "images/panel_01.jpg",   # このファイルからの相対パス or 絶対パス
        "true_value": 3.05,               # 人が目視で読んだ値
        "min_value": 0.0,                 # 目盛りの最小値
        "max_value": 5.0,                 # 目盛りの最大値
        "tolerance_percent": 2.5,         # 任意。JIS階級（省略時は既定値2.5）
        "note": "冷却塔 0.6kW 電流計"      # 任意。メモ
      }
    ]

指標について:
    引用誤差（基準誤差）を主指標にしている。相対誤差は真値が0付近だと
    発散して比較できなくなるのに対し、引用誤差はフルスケール基準なので
    レンジ全域で扱えるため。計器の確度階級（JIS C 1102の2.5級など）も
    フルスケール基準で定義されており、そのまま合否判定に使える。
"""
from __future__ import print_function

import argparse
import json
import os
import sys
import time

import cv2
import numpy as np

import meter_pipeline

# JIS C 1102 の確度階級。2.5級＝フルスケールの±2.5%
DEFAULT_TOLERANCE_PERCENT = 2.5


# ── 指標 ──────────────────────────────────────────────────────
def absolute_error(measured, true_value):
    """絶対誤差（測定値と同じ単位）"""
    return abs(measured - true_value)


def relative_error(measured, true_value):
    """
    相対誤差[%]（真値に対する誤差の割合）。
    真値が0のときは定義できないので None を返す。
    """
    if true_value == 0:
        return None
    return abs(measured - true_value) / abs(true_value) * 100.0


def reference_error(measured, true_value, val_min, val_max):
    """
    引用誤差[%]（フルスケール幅に対する誤差の割合）。
    計器の確度階級と同じ基準なので、こちらを主指標にする。
    """
    span = abs(val_max - val_min)
    if span == 0:
        return None
    return abs(measured - true_value) / span * 100.0


def is_within_tolerance(measured, true_value, val_min, val_max,
                        tolerance_percent=DEFAULT_TOLERANCE_PERCENT):
    """引用誤差が許容範囲（既定はJIS 2.5級）に収まっているか"""
    err = reference_error(measured, true_value, val_min, val_max)
    if err is None:
        return False
    return err <= tolerance_percent


# ── 集計 ──────────────────────────────────────────────────────
def summarize(rows):
    """
    評価結果の一覧から全体の要約を作る。

    真値が未記入（unlabeled）の項目は母数から除く。読み取り失敗と
    同じ扱いにすると、ラベルを付けていないだけなのに精度が悪いように
    見えてしまうため。
    """
    rows = [r for r in rows if r.get('stage') != 'unlabeled']
    total = len(rows)
    ok_rows = [r for r in rows if r.get('stage') == meter_pipeline.STAGE_OK]
    errors = [r['reference_error'] for r in ok_rows
              if r.get('reference_error') is not None]

    failure_stages = {}
    for r in rows:
        stage = r.get('stage')
        if stage != meter_pipeline.STAGE_OK:
            failure_stages[stage] = failure_stages.get(stage, 0) + 1

    return {
        'total': total,
        'read_ok': len(ok_rows),
        'within_tolerance': sum(1 for r in rows if r.get('within_tolerance')),
        'mean_reference_error': (sum(errors) / len(errors)) if errors else None,
        'max_reference_error': max(errors) if errors else None,
        'failure_stages': failure_stages,
    }


# ── 実行 ──────────────────────────────────────────────────────
def _resolve_path(path, base_dir):
    if os.path.isabs(path):
        return path
    return os.path.normpath(os.path.join(base_dir, path))


def evaluate_entry(entry, base_dir, use_vlm=True):
    """正解データ1件を読み取り、誤差を計算して1行分の結果を返す"""
    image_path = _resolve_path(entry['image'], base_dir)
    row = {
        'image': entry['image'],
        'note': entry.get('note', ''),
        'true_value': entry['true_value'],
        'true_min': entry['min_value'],
        'true_max': entry['max_value'],
        'value': None,
        'stage': None,
        'absolute_error': None,
        'relative_error': None,
        'reference_error': None,
        'within_tolerance': False,
        'scale_correct': None,
        'elapsed_sec': None,
    }

    # 真値が未記入の項目は評価できない。黙って0点扱いにすると
    # 「精度が悪い」と誤読してしまうので、未ラベルとして明示的に分ける。
    if entry.get('true_value') is None:
        row['stage'] = 'unlabeled'
        return row

    if not os.path.exists(image_path):
        row['stage'] = 'image_not_found'
        return row

    img = cv2.imdecode(np.fromfile(image_path, dtype=np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        row['stage'] = 'image_unreadable'
        return row

    started = time.time()
    result = meter_pipeline.read_meter(img, use_vlm=use_vlm)
    row['elapsed_sec'] = round(time.time() - started, 2)

    row['stage'] = result['stage']
    row['n_ticks'] = result['n_ticks']
    row['scale_source'] = result['scale_source']
    row['center_source'] = result['center_source']
    row['detected_min'] = result['min_value']
    row['detected_max'] = result['max_value']

    # 目盛りの最小/最大を正しく検出できたか（値の誤差とは別の失敗要因なので分けて見る）
    if result['min_value'] is not None:
        row['scale_correct'] = (
            abs(result['min_value'] - entry['min_value']) < 1e-6 and
            abs(result['max_value'] - entry['max_value']) < 1e-6)

    if result['stage'] != meter_pipeline.STAGE_OK:
        return row

    tolerance = entry.get('tolerance_percent', DEFAULT_TOLERANCE_PERCENT)
    measured = result['value']
    row['value'] = measured
    row['absolute_error'] = absolute_error(measured, entry['true_value'])
    row['relative_error'] = relative_error(measured, entry['true_value'])
    row['reference_error'] = reference_error(
        measured, entry['true_value'], entry['min_value'], entry['max_value'])
    row['within_tolerance'] = is_within_tolerance(
        measured, entry['true_value'], entry['min_value'], entry['max_value'],
        tolerance)
    return row


def _fmt(value, spec='{:.3f}'):
    return spec.format(value) if value is not None else '-'


def print_report(rows, summary, tolerance_percent):
    print('')
    print('=' * 78)
    print(' 読み取り精度 評価結果')
    print('=' * 78)
    header = '{:<24} {:>8} {:>8} {:>9} {:>6} {:>7}'.format(
        '画像', '正解', '読取', '引用誤差%', '合否', '秒')
    print(header)
    print('-' * 78)
    for r in rows:
        name = os.path.basename(r['image'])
        if len(name) > 23:
            name = name[:20] + '...'
        if r['stage'] == meter_pipeline.STAGE_OK:
            verdict = 'OK' if r['within_tolerance'] else 'NG'
        else:
            verdict = r['stage']  # どの段階で落ちたか
        print('{:<24} {:>8} {:>8} {:>9} {:>6} {:>7}'.format(
            name,
            _fmt(r['true_value'], '{:.2f}'),
            _fmt(r['value'], '{:.2f}'),
            _fmt(r['reference_error'], '{:.2f}'),
            verdict,
            _fmt(r['elapsed_sec'], '{:.1f}')))

    print('-' * 78)
    print('画像数            : {}'.format(summary['total']))
    print('読み取り成功      : {} / {}'.format(summary['read_ok'], summary['total']))
    print('許容誤差内(±{}%FS): {} / {}'.format(
        tolerance_percent, summary['within_tolerance'], summary['total']))
    print('平均引用誤差      : {} %FS'.format(_fmt(summary['mean_reference_error'], '{:.2f}')))
    print('最大引用誤差      : {} %FS'.format(_fmt(summary['max_reference_error'], '{:.2f}')))
    if summary['failure_stages']:
        print('失敗の内訳        : ' + ', '.join(
            '{}={}'.format(k, v) for k, v in sorted(summary['failure_stages'].items())))

    # 目盛りの最小/最大の誤検出は、値の誤差とは別に見ておきたい
    scale_checked = [r for r in rows if r.get('scale_correct') is not None]
    if scale_checked:
        wrong = [r for r in scale_checked if not r['scale_correct']]
        print('目盛り範囲の誤検出: {} / {}'.format(len(wrong), len(scale_checked)))
        for r in wrong:
            print('    {} : 検出 {}〜{} / 正解 {}〜{}'.format(
                os.path.basename(r['image']),
                r.get('detected_min'), r.get('detected_max'),
                r['true_min'], r['true_max']))
    print('=' * 78)


def main(argv=None):
    parser = argparse.ArgumentParser(
        description='アナログメーター読み取りの精度を評価する')
    parser.add_argument('groundtruth', help='正解データのJSONファイル')
    parser.add_argument('--no-vlm', action='store_true',
                        help='VLMによる盤面クロップを使わない（Ollama無しでも動かす場合）')
    parser.add_argument('-o', '--output',
                        help='結果をJSONで保存するパス')
    parser.add_argument('--tolerance', type=float,
                        default=DEFAULT_TOLERANCE_PERCENT,
                        help='許容誤差[%%FS]（既定: JIS 2.5級の2.5）')
    args = parser.parse_args(argv)

    with open(args.groundtruth, encoding='utf-8') as f:
        entries = json.load(f)

    base_dir = os.path.dirname(os.path.abspath(args.groundtruth))

    rows = []
    for i, entry in enumerate(entries, 1):
        if entry.get('true_value') is None:
            print('[{}/{}] {} — 真値が未記入のためスキップ'.format(
                i, len(entries), entry['image']))
        else:
            print('[{}/{}] {} ...'.format(i, len(entries), entry['image']))
        entry.setdefault('tolerance_percent', args.tolerance)
        rows.append(evaluate_entry(entry, base_dir, use_vlm=not args.no_vlm))

    summary = summarize(rows)
    print_report(rows, summary, args.tolerance)

    unlabeled = [r for r in rows if r.get('stage') == 'unlabeled']
    if unlabeled:
        print('※ 真値が未記入で評価対象外: {} 件'.format(len(unlabeled)))
        for r in unlabeled:
            print('    {}  {}'.format(os.path.basename(r['image']), r['note']))

    if args.output:
        with open(args.output, 'w', encoding='utf-8') as f:
            json.dump({'summary': summary, 'results': rows},
                      f, ensure_ascii=False, indent=2)
        print('結果を保存しました: {}'.format(args.output))

    return 0


if __name__ == '__main__':
    sys.exit(main())
