"""複数のgitタグで同一の評価ハーネスを実行し、指標を比較する。"""
from __future__ import print_function

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from typing import Any, Dict, List, Optional


DEFAULT_VERSIONS = ['v0', 'v1', 'v2', 'v3', 'v4', 'v5']


def _format_count(value: Any, total: Any) -> str:
    """分子・母数がそろうときだけ比較表用の件数を返す。"""
    if value is None or total is None:
        return '-'
    return '{} / {}'.format(value, total)


def _format_number(value: Any) -> str:
    """比較表の数値は小数第2位まで、欠損はハイフンで表示する。"""
    if isinstance(value, (int, float)):
        return '{:.2f}'.format(value)
    return '-'


def _format_integer(value: Any) -> str:
    """件数のような整数指標を表示する。"""
    if isinstance(value, int):
        return str(value)
    return '-'


def build_comparison_rows(version_results: List[Dict[str, Any]]) -> List[Dict[str, str]]:
    """評価JSON由来の要約を、比較表に表示する行へ変換する。"""
    rows = []  # type: List[Dict[str, str]]
    for result in version_results:
        summary = result.get('summary') or {}
        total = summary.get('total')
        rows.append({
            'version': str(result.get('version', '-')),
            'read_ok': _format_count(summary.get('read_ok'), total),
            'within_tolerance': _format_count(
                summary.get('within_tolerance'), total),
            'mean_reference_error': _format_number(
                summary.get('mean_reference_error')),
            'median_reference_error': _format_number(
                summary.get('median_reference_error')),
            'catastrophic_count': _format_integer(
                summary.get('catastrophic_count')),
        })
    return rows


def _values_by_image(result: Dict[str, Any],
                     entry_key: str = 'value') -> Optional[Dict[str, Any]]:
    """評価結果から画像ごとの指定値を取り出す。異常なJSONは None。"""
    entries = result.get('results')
    if not isinstance(entries, list):
        return None

    values = {}  # type: Dict[str, Any]
    for entry in entries:
        if not isinstance(entry, dict):
            return None
        image = entry.get('image')
        if image is None or image in values:
            return None
        values[image] = entry.get(entry_key)
    return values


def build_per_image_error_rows(
        version_results: List[Dict[str, Any]]) -> List[Dict[str, str]]:
    """評価JSON由来の画像別引用誤差を、比較表の行へ変換する。"""
    values_by_version = {}  # type: Dict[str, Dict[str, Any]]
    images = set()
    versions = []  # type: List[str]
    for result in version_results:
        version = str(result.get('version', '-'))
        values = _values_by_image(result, 'reference_error')
        versions.append(version)
        values_by_version[version] = values or {}
        if values is not None:
            images.update(values.keys())

    rows = []  # type: List[Dict[str, str]]
    for image in sorted(images):
        row = {'image': str(image)}
        for version in versions:
            row[version] = _format_number(values_by_version[version].get(image))
        rows.append(row)
    return rows


def v4_v5_values_match(v4_result: Dict[str, Any],
                        v5_result: Dict[str, Any]) -> bool:
    """v4/v5で各画像の読み取り値が完全一致するかを返す。"""
    v4_values = _values_by_image(v4_result)
    v5_values = _values_by_image(v5_result)
    if v4_values is None or v5_values is None:
        return False
    return v4_values == v5_values


def print_comparison_table(rows: List[Dict[str, str]]) -> None:
    """比較表を標準出力へ表示する。"""
    print('')
    print('=' * 96)
    print('{:<8} {:>12} {:>16} {:>15} {:>15} {:>12}'.format(
        '版', '読み取り成功', '許容誤差内', '平均引用誤差',
        '中央値引用誤差', '破滅的失敗'))
    print('-' * 96)
    for row in rows:
        print('{:<8} {:>12} {:>16} {:>15} {:>15} {:>12}'.format(
            row['version'], row['read_ok'], row['within_tolerance'],
            row['mean_reference_error'], row['median_reference_error'],
            row['catastrophic_count']))
    print('=' * 96)


def print_per_image_error_table(rows: List[Dict[str, str]],
                                versions: List[str]) -> None:
    """画像ごと・版ごとの引用誤差表を標準出力へ表示する。"""
    image_width = max(
        [len('画像')] + [len(row['image']) for row in rows])
    column_width = 10
    table_width = image_width + 1 + (column_width + 1) * len(versions)
    print('')
    print('=' * table_width)
    print('{:<{}} {}'.format(
        '画像', image_width,
        ' '.join('{:>{}}'.format(version, column_width)
                 for version in versions)))
    print('-' * table_width)
    for row in rows:
        print('{:<{}} {}'.format(
            row['image'], image_width,
            ' '.join('{:>{}}'.format(row[version], column_width)
                     for version in versions)))
    print('=' * table_width)


def _run_command(command: List[str], cwd: str) -> None:
    """失敗時に例外として扱う外部コマンドを実行する。"""
    subprocess.run(command, cwd=cwd, check=True)


def run_version(repo_root: str, version: str) -> Dict[str, Any]:
    """一時worktreeで1タグを評価し、評価JSONを返して必ずworktreeを削除する。"""
    python_path = os.path.join(repo_root, 'venv', 'Scripts', 'python.exe')
    source_evaluate = os.path.join(repo_root, 'evaluate.py')
    source_groundtruth = os.path.join(repo_root, 'eval', 'groundtruth.json')
    if not os.path.isfile(python_path):
        raise RuntimeError('Python実行ファイルが見つかりません: {}'.format(python_path))

    with tempfile.TemporaryDirectory(prefix='sotuken_compare_') as temporary_root:
        worktree_path = os.path.join(temporary_root, 'worktree')
        worktree_added = False
        try:
            _run_command(
                ['git', 'worktree', 'add', '--detach', worktree_path, version],
                repo_root)
            worktree_added = True

            shutil.copy2(source_evaluate, os.path.join(worktree_path, 'evaluate.py'))
            groundtruth_path = os.path.join(
                worktree_path, 'eval', 'groundtruth.json')
            shutil.copy2(source_groundtruth, groundtruth_path)

            result_path = os.path.join(worktree_path, 'compare_result.json')
            _run_command([
                python_path,
                'evaluate.py',
                os.path.join('eval', 'groundtruth.json'),
                '--no-vlm',
                '--scope', 'round',
                '-o', 'compare_result.json',
            ], worktree_path)

            with open(result_path, encoding='utf-8') as result_file:
                result = json.load(result_file)
            if not isinstance(result, dict):
                raise RuntimeError('{} の評価JSONが辞書ではありません'.format(version))
            return result
        finally:
            if worktree_added:
                _run_command(
                    ['git', 'worktree', 'remove', '--force', worktree_path],
                    repo_root)


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description='複数のパイプライン版を同一評価ハーネスで比較する')
    parser.add_argument(
        '--versions', nargs='+', default=DEFAULT_VERSIONS,
        help='比較するgitタグ名（既定: {}）'.format(' '.join(DEFAULT_VERSIONS)))
    parser.add_argument(
        '--per-image', action='store_true',
        help='画像ごと・版ごとの引用誤差表も出力する')
    args = parser.parse_args(argv)

    if len(args.versions) != len(set(args.versions)):
        parser.error('--versions に同じタグを重複して指定できません')

    repo_root = os.path.dirname(os.path.abspath(__file__))
    summaries = []  # type: List[Dict[str, Any]]
    results_by_version = {}  # type: Dict[str, Dict[str, Any]]
    try:
        for version in args.versions:
            print('{} の評価を開始します'.format(version))
            result = run_version(repo_root, version)
            print('{} の評価が完了しました'.format(version))
            results_by_version[version] = result
            summaries.append({
                'version': version,
                'summary': result.get('summary') or {},
            })
    except (OSError, RuntimeError, subprocess.CalledProcessError) as error:
        print('比較に失敗しました: {}'.format(error), file=sys.stderr)
        return 1

    if 'v4' in results_by_version and 'v5' in results_by_version:
        if not v4_v5_values_match(
                results_by_version['v4'], results_by_version['v5']):
            print('v4/v5の読み取り値が一致しません。比較表は出力しません。',
                  file=sys.stderr)
            return 1
        print('v4/v5の読み取り値一致を確認しました')

    print_comparison_table(build_comparison_rows(summaries))
    if args.per_image:
        version_results = []  # type: List[Dict[str, Any]]
        for version in args.versions:
            result = dict(results_by_version[version])
            result['version'] = version
            version_results.append(result)
        print_per_image_error_table(
            build_per_image_error_rows(version_results), args.versions)
    return 0


if __name__ == '__main__':
    sys.exit(main())
