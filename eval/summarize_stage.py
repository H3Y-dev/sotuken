"""stage_errors.py の出力（JSONL）を条件ごと・工程ごとに集計し、Markdown形式で出力するスクリプト。

使い方:
    python eval/summarize_stage.py <results.jsonl>
"""
import argparse
import json
import statistics as st
from collections import defaultdict


def load_rows(path):
    """JSONLファイルから行データを読み出す。"""
    rows = []
    with open(path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def cond(r):
    """note から meter, camera, light, blur 条件を抽出する。"""
    parts = r.get('note', '').split()
    meter, _, cam, light, blur = (parts + ['', '', '', '', ''])[:5]
    return {'meter': meter, 'camera': cam, 'light': light, 'blur': blur}


def summary(rs):
    """行リストに対する要約統計量を計算する（元スクリプトの計算式を完全保持）。"""
    errs = [r['err_fs'] for r in rs if 'err_fs' in r and r['err_fs'] is not None]
    out = {
        'n': len(rs),
        'ok': sum(1 for r in rs if r.get('stage') == 'ok'),
        'within2.5': sum(1 for e in errs if e <= 2.5),
        'mean': round(st.mean(errs), 2) if errs else None,
        'median': round(st.median(errs), 2) if errs else None,
        'max': round(max(errs), 2) if errs else None,
        'cat25': sum(1 for e in errs if e > 25),
    }
    for k in ('center_pct_radius', 'zero_pt_deg', 'full_pt_deg', 'needle_seg_deg'):
        v = [r[k] for r in rs if k in r and r[k] is not None]
        out[k + '_med'] = round(st.median(v), 2) if v else None
    rng = [r['range_ok'] for r in rs if 'range_ok' in r and r['range_ok'] is not None]
    out['range_ok'] = '%d/%d' % (sum(rng), len(rng)) if rng else None
    return out


def _fmt(val, fmt=None):
    if val is None:
        return '-'
    if fmt:
        return fmt % val
    return str(val)


def generate_markdown(rows):
    """集計結果をMarkdown表形式の文字列として生成する。"""
    if not rows:
        return '# 工程別評価集計レポート\n\n対象データが空です。\n'

    lines = []
    lines.append('# 工程別評価集計レポート\n')

    # 1. 条件別集計表
    lines.append('## 条件別集計 (Condition Summary)\n')
    headers = [
        'カテゴリ', 'グループ', '件数(N)', '成功(OK)', '≤2.5%FS',
        '平均%FS', '中央値%FS', '最大%FS', '>25%FS',
        '中心%R(中央)', '0点°(中央)', '満尺°(中央)', '針角°(中央)', '目盛範囲'
    ]
    align = [':---', ':---', '---:', '---:', '---:', '---:', '---:', '---:', '---:', '---:', '---:', '---:', '---:', ':---']
    lines.append('| ' + ' | '.join(headers) + ' |')
    lines.append('| ' + ' | '.join(align) + ' |')

    # ALL 全体
    all_sum = summary(rows)
    lines.append('| ' + ' | '.join([
        'ALL', '全体',
        str(all_sum['n']),
        str(all_sum['ok']),
        str(all_sum['within2.5']),
        _fmt(all_sum['mean'], '%.2f'),
        _fmt(all_sum['median'], '%.2f'),
        _fmt(all_sum['max'], '%.2f'),
        str(all_sum['cat25']),
        _fmt(all_sum['center_pct_radius_med'], '%.2f'),
        _fmt(all_sum['zero_pt_deg_med'], '%.2f'),
        _fmt(all_sum['full_pt_deg_med'], '%.2f'),
        _fmt(all_sum['needle_seg_deg_med'], '%.2f'),
        _fmt(all_sum['range_ok']),
    ]) + ' |')

    # 各キー (meter, camera, light, blur)
    for key in ('meter', 'camera', 'light', 'blur'):
        groups = defaultdict(list)
        for r in rows:
            groups[cond(r)[key]].append(r)
        for g in sorted(groups):
            s = summary(groups[g])
            lines.append('| ' + ' | '.join([
                key, str(g) if g else '(none)',
                str(s['n']),
                str(s['ok']),
                str(s['within2.5']),
                _fmt(s['mean'], '%.2f'),
                _fmt(s['median'], '%.2f'),
                _fmt(s['max'], '%.2f'),
                str(s['cat25']),
                _fmt(s['center_pct_radius_med'], '%.2f'),
                _fmt(s['zero_pt_deg_med'], '%.2f'),
                _fmt(s['full_pt_deg_med'], '%.2f'),
                _fmt(s['needle_seg_deg_med'], '%.2f'),
                _fmt(s['range_ok']),
            ]) + ' |')

    lines.append('')

    # 2. 工程別内訳
    lines.append('## 工程別内訳 (Stages)\n')
    stages = defaultdict(int)
    for r in rows:
        stages[r.get('stage', 'unknown')] += 1

    lines.append('| 判定工程 (Stage) | 件数 | 割合 |')
    lines.append('|:---|---:|---:|')
    for stage_name in sorted(stages, key=lambda s: -stages[s]):
        cnt = stages[stage_name]
        pct = (cnt / len(rows) * 100) if rows else 0.0
        lines.append('| %s | %d | %.1f%% |' % (stage_name, cnt, pct))

    lines.append('')
    not_comp = sum(1 for r in rows if not r.get('coords_comparable', True))
    not_comp_pct = (not_comp / len(rows) * 100) if rows else 0.0
    lines.append('- **座標比較不能 (rotated / cropped)**: %d 件 / %d 件 (%.1f%%)\n' % (
        not_comp, len(rows), not_comp_pct))

    # 3. ワースト症例
    lines.append('## 引用誤差 ワースト症例 (最大8件)\n')
    worst = sorted([r for r in rows if 'err_fs' in r and r['err_fs'] is not None],
                   key=lambda r: -r['err_fs'])[:8]
    if worst:
        lines.append('| 画像 (Image) | %FS 誤差 | 目盛範囲 | 中心%R | 針角誤差° | 工程 | ノート |')
        lines.append('|:---|---:|:---|---:|---:|:---|:---|')
        for r in worst:
            lines.append('| ' + ' | '.join([
                str(r.get('image', '-')),
                _fmt(r.get('err_fs'), '%.2f'),
                _fmt(r.get('range_ok')),
                _fmt(r.get('center_pct_radius'), '%.2f'),
                _fmt(r.get('needle_seg_deg'), '%.2f'),
                str(r.get('stage', '-')),
                str(r.get('note', '-')),
            ]) + ' |')
    else:
        lines.append('引用誤差が計算された項目はありません。\n')

    lines.append('')
    return '\n'.join(lines)


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description='工程別評価結果（JSONL）の集計・Markdown出力')
    parser.add_argument('input', help='集計対象のJSONLファイルパス')
    return parser.parse_args(argv)


def main():
    args = parse_args()
    rows = load_rows(args.input)
    md = generate_markdown(rows)
    print(md)


if __name__ == '__main__':
    main()
