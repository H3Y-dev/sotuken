"""
版間比較（O-09）: 複数の pipeline_version で同じ画像集合を再処理し、1つの表にまとめる。

本研究の主張は「失敗を捨てず、版を重ねた再処理で改善を測れる」ことなので、
版ごとの誤差を並べた表そのものが実験結果になる。

## 設計上の約束

1. **評価ハーネスは全版で同一のものを使う。** 旧コミットを丸ごと展開して旧 evaluate.py を
   走らせる方式は取れない（--scope が 81ef30c より前に存在しない）。そこで各版のworktreeへ
   「現在の evaluate.py と正解データ」を持ち込んで実行する。比べたいのはパイプラインの
   実力であって、評価コードの違いではない。
2. **作業ツリーには一切触らない。** 各版は git worktree でテンポラリへ展開する。
   実行前後で git status の出力が変わっていないことを最後に検証する。
3. **v4 と v5 は一致するはずである（対照）。** この2版の差は可視化だけで、値の算出に
   関与しない。一致しなければハーネス側が汚染されているので、表を出さずに失敗として報告する。
4. **良い表が出るまで版の選び方を変えない。** 非単調な結果は実験の失敗ではなく所見である。

使い方:
    venv\\Scripts\\python.exe tools_compare_versions.py --no-vlm
    venv\\Scripts\\python.exe tools_compare_versions.py --versions v3 v4 v5 -o compare.json
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile

REPO_ROOT = os.path.dirname(os.path.abspath(__file__))

# tasks/plan-android-sprints.md の「版の対応表」と一致させること。
DEFAULT_VERSIONS = ['v0', 'v1', 'v2', 'v3', 'v4', 'v5']

# 値の算出に関与しない差分しか無い版の対。ここが一致しなければハーネスを疑う。
DEFAULT_CONTROL_PAIR = ('v4', 'v5')

# 浮動小数の比較幅。同じコードなら本来は完全一致する。
VALUE_MATCH_EPSILON = 1e-9

# 各版へ持ち込むハーネス。リポジトリルートからの相対パスで書く。
HARNESS_FILES = ['evaluate.py', 'eval/groundtruth.json']


def run_git(args, cwd=REPO_ROOT):
    """gitを呼び、標準出力を返す。失敗したらそのまま例外にする"""
    result = subprocess.run(
        ['git'] + args, cwd=cwd, capture_output=True, text=True,
        encoding='utf-8', errors='replace')
    if result.returncode != 0:
        raise RuntimeError('git {} が失敗しました:\n{}'.format(
            ' '.join(args), result.stderr.strip()))
    return result.stdout


def working_tree_snapshot():
    """
    追跡下のPythonファイルの変更状態。実行前後で変わっていないことの確認に使う。

    見る範囲を絞ってあるのは、確かめたいのが「パイプラインを書き換えていないこと」
    だけだからである。当初は git status の全出力を比べていたが、比較中に別作業で
    メモやプロンプトが増えただけで誤検知した（2026-09-02に実際に2回起きた。
    1回目は未追跡のプロンプト4本、2回目は追跡下の計画書の更新）。
    """
    changed = run_git(['status', '--porcelain', '--untracked-files=no']).splitlines()
    return '\n'.join(sorted(
        line for line in changed if line.strip().endswith('.py')))


def verify_tags(versions):
    existing = set(run_git(['tag']).split())
    missing = [v for v in versions if v not in existing]
    if missing:
        raise SystemExit(
            'タグが見つかりません: {}\n'
            'O-08（版へのタグ付け）を先に済ませてください。'.format(', '.join(missing)))


def prepare_worktree(version, base_dir):
    """指定した版をテンポラリへ展開し、現在のハーネスを上書きで持ち込む"""
    worktree = os.path.join(base_dir, version)
    run_git(['worktree', 'add', '--detach', '--quiet', worktree, version])

    for rel in HARNESS_FILES:
        src = os.path.join(REPO_ROOT, rel)
        dst = os.path.join(worktree, rel.replace('/', os.sep))
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copyfile(src, dst)

    return worktree


def run_evaluation(worktree, scope, use_vlm, tolerance):
    """worktree上で評価を1回実行し、evaluate.py が書いたJSONを読んで返す"""
    out_path = os.path.join(worktree, '_compare_result.json')
    argv = [
        sys.executable, 'evaluate.py',
        os.path.join('eval', 'groundtruth.json'),
        '--scope', scope,
        '--tolerance', str(tolerance),
        '-o', out_path,
    ]
    if not use_vlm:
        argv.append('--no-vlm')

    # 出力の文字化けを避ける。付けないとcp932で読めなくなる。
    env = dict(os.environ, PYTHONIOENCODING='utf-8')
    result = subprocess.run(argv, cwd=worktree, capture_output=True,
                            text=True, encoding='utf-8', errors='replace',
                            env=env)
    if result.returncode != 0 or not os.path.exists(out_path):
        raise RuntimeError(
            '評価の実行に失敗しました（終了コード {}）:\n{}'.format(
                result.returncode, (result.stderr or '').strip()[-2000:]))

    with open(out_path, encoding='utf-8') as f:
        return json.load(f)


def values_by_image(payload):
    """画像ごとの (stage, 読み取り値) を取り出す。対照の突き合わせに使う"""
    table = {}
    for row in payload['results']:
        table[row['image']] = (row.get('stage'), row.get('value'))
    return table


def check_control_pair(results, pair):
    """
    値の算出に差が無いはずの2版が一致するかを確かめる。
    一致しない場合は比較表を出さない。表より先にハーネスを疑うべきだからである。
    """
    left, right = pair
    if left not in results or right not in results:
        return ['対照の版（{} と {}）が実行対象に含まれていないため、'
                '対照チェックを行っていない'.format(left, right)]

    a = values_by_image(results[left])
    b = values_by_image(results[right])

    problems = []
    if set(a) != set(b):
        problems.append('{} と {} で評価した画像集合が異なる'.format(left, right))

    for image in sorted(set(a) & set(b)):
        stage_a, value_a = a[image]
        stage_b, value_b = b[image]
        if stage_a != stage_b:
            problems.append('{}: stage が異なる（{}={} / {}={}）'.format(
                os.path.basename(image), left, stage_a, right, stage_b))
            continue
        if value_a is None and value_b is None:
            continue
        if value_a is None or value_b is None:
            problems.append('{}: 片方だけ読み取り値が無い'.format(
                os.path.basename(image)))
            continue
        if abs(value_a - value_b) > VALUE_MATCH_EPSILON:
            problems.append('{}: 読み取り値が異なる（{}={} / {}={}）'.format(
                os.path.basename(image), left, value_a, right, value_b))

    return problems


def _fmt(value, spec='{:.2f}'):
    return '-' if value is None else spec.format(value)


def print_table(versions, results, scope, use_vlm, tolerance):
    header = '版     読取成功   許容内   平均引用誤差    中央値   破滅的失敗   最大誤差'
    print()
    print('=' * 72)
    print('版間比較（scope={} / VLM={} / 許容誤差={}%FS）'.format(
        scope, '有効' if use_vlm else '無効', tolerance))
    print('=' * 72)
    print(header)
    print('-' * 72)
    for version in versions:
        s = results[version]['summary']
        total = s['total']
        print('{:<6} {:>4}/{:<4} {:>4}/{:<4} {:>11} {:>9} {:>10} {:>10}'.format(
            version,
            s['read_ok'], total,
            s['within_tolerance'], total,
            _fmt(s['mean_reference_error']),
            _fmt(s['median_reference_error']),
            s['catastrophic_count'],
            _fmt(s['max_reference_error']),
        ))
    print('-' * 72)
    print('誤差の単位は %FS（引用誤差）。許容内は JIS 2.5級の判定件数。')
    print('平均だけで判断しない。中央値と破滅的失敗の件数を必ず併せて見る。')


def main(argv=None):
    parser = argparse.ArgumentParser(
        description='複数の pipeline_version を同一の評価ハーネスで比較する')
    parser.add_argument('--versions', nargs='+', default=DEFAULT_VERSIONS,
                        help='比較する版（gitタグ名）。既定: ' +
                             ' '.join(DEFAULT_VERSIONS))
    parser.add_argument('--scope', default='round',
                        help='評価対象の形状。既定: round')
    parser.add_argument('--no-vlm', action='store_true',
                        help='全版でVLMを無効にして比較する（版間で条件をそろえる）')
    parser.add_argument('--tolerance', type=float, default=2.5,
                        help='許容誤差[%%FS]。既定: JIS 2.5級の2.5')
    parser.add_argument('--control', nargs=2, metavar=('版A', '版B'),
                        default=list(DEFAULT_CONTROL_PAIR),
                        help='値が一致するはずの対照の版の対。既定: v4 v5')
    parser.add_argument('-o', '--output', help='比較結果をJSONで保存するパス')
    parser.add_argument('--keep-worktrees', action='store_true',
                        help='実行後にworktreeを消さない（失敗時の調査用）')
    args = parser.parse_args(argv)

    verify_tags(args.versions)
    before = working_tree_snapshot()

    base_dir = tempfile.mkdtemp(prefix='meter_version_compare_')
    results = {}
    worktrees = []
    try:
        for version in args.versions:
            print('[{}] worktreeを展開して評価します ...'.format(version))
            worktree = prepare_worktree(version, base_dir)
            worktrees.append(worktree)
            results[version] = run_evaluation(
                worktree, args.scope, not args.no_vlm, args.tolerance)
            s = results[version]['summary']
            print('[{}] 読取成功 {}/{}  許容内 {}/{}  平均 {} %FS'.format(
                version, s['read_ok'], s['total'],
                s['within_tolerance'], s['total'],
                _fmt(s['mean_reference_error'])))

        problems = check_control_pair(results, tuple(args.control))
        if problems:
            print()
            print('対照チェックに失敗しました。比較表は出しません。')
            print('ハーネスが版ごとに違うものになっていないかを先に疑ってください。')
            for p in problems:
                print('  - {}'.format(p))
            return 1

        print_table(args.versions, results, args.scope,
                    not args.no_vlm, args.tolerance)

        if args.output:
            payload = {
                'scope': args.scope,
                'use_vlm': not args.no_vlm,
                'tolerance_percent': args.tolerance,
                'control_pair': list(args.control),
                'versions': {v: results[v] for v in args.versions},
            }
            with open(args.output, 'w', encoding='utf-8') as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
            print('比較結果を保存しました: {}'.format(args.output))
    finally:
        if not args.keep_worktrees:
            for worktree in worktrees:
                run_git(['worktree', 'remove', '--force', worktree])
            shutil.rmtree(base_dir, ignore_errors=True)
        else:
            print('worktreeを残しました: {}'.format(base_dir))

    after = working_tree_snapshot()
    if before != after:
        print()
        print('作業ツリーの状態が実行前後で変わっています。')
        print('パイプラインを書き換えていないか確認してください。')
        return 1

    return 0


if __name__ == '__main__':
    sys.exit(main())
