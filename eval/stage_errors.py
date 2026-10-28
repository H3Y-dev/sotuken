"""合成画像の正解座標と、読み取り処理が出した中心・0点・満尺点・針の位置を比べる工程別評価スクリプト。

使い方:
    python eval/stage_errors.py <groundtruth.json> -o <出力パス.jsonl> [オプション]

オプション:
    -o, --output PATH         出力JSONLファイルパス（必須）
    --local-read              局所読み取りを使用する
    --needle-angle {segment,tip}
                              針の角度算出元（既定: segment）
    --limit N                 先頭N件のみ評価（再開時は完了分を含めてカウント）
"""
import argparse
import json
import math
import os
import sys

# リポジトリ直下を sys.path に追加してモジュールを読み込めるようにする
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

import cv2
import numpy as np

import meter_pipeline
import meter_reader


def ang(c, p):
    """中心 c から点 p への偏角（ラジアン）を返す。"""
    return math.atan2(p[1] - c[1], p[0] - c[0])


def angdiff_deg(a, b):
    """2つの角度 a, b（ラジアン）の差の絶対値を度数法（0〜180度）で返す。"""
    d = (a - b + math.pi) % (2 * math.pi) - math.pi
    return abs(math.degrees(d))


def dist(a, b):
    """2点 a, b 間のユークリッド距離を返す。"""
    return math.hypot(a[0] - b[0], a[1] - b[1])


def compute_stage_row(entry, result, pts, image_name, needle=None):
    """1枚分の読み取り結果と正解データから各工程の誤差を計算する。"""
    row = {
        'image': image_name,
        'note': entry.get('note', ''),
        'stage': result.get('stage'),
        'orientation_angle': result.get('orientation_angle'),
        'cropped': result.get('cropped'),
        'category': entry.get('category'),
        'read_method': result.get('read_method'),
        'scale_confident': result.get('scale_confident'),
    }
    span = abs(entry.get('max_value', 0) - entry.get('min_value', 0))
    if result.get('value') is not None and span > 0:
        row['err_fs'] = abs(result['value'] - entry['true_value']) / span * 100

    rotated = result.get('orientation_angle') not in (0, None) or result.get('cropped')
    row['coords_comparable'] = not rotated

    c_true = pts.get('center') if pts else None
    c_pred = result.get('center')
    if c_pred is not None and not rotated and c_true is not None:
        row['center_px'] = dist(c_pred, c_true)
        if 'zero_pt' in pts:
            radius = dist(c_true, pts['zero_pt'])
            if radius > 0:
                row['center_pct_radius'] = row['center_px'] / radius * 100
        for k in ('zero_pt', 'full_pt'):
            if result.get(k) is not None and k in pts:
                row[k + '_deg'] = angdiff_deg(ang(c_true, result[k]), ang(c_true, pts[k]))
        if 'min_value' in entry and 'max_value' in entry:
            row['range_ok'] = (result.get('min_value') == entry['min_value'] and result.get('max_value') == entry['max_value'])

        if needle is None and result.get('processed_img') is not None:
            needle = meter_reader.detect_needle(result['processed_img'], c_pred)

        if needle is not None and 'needle_tip' in pts:
            true_a = ang(c_true, pts['needle_tip'])
            if 'direction' in needle and needle['direction'] is not None:
                row['needle_seg_deg'] = angdiff_deg(math.atan2(needle['direction'][1], needle['direction'][0]), true_a)
            if 'angle_tip' in needle and needle['angle_tip'] is not None:
                row['needle_tip_deg'] = angdiff_deg(needle['angle_tip'], true_a)
            if 'tip' in needle and needle['tip'] is not None:
                row['needle_tip_px'] = dist(needle['tip'], pts['needle_tip'])

    return row


def make_error_row(entry, error_message, image_name):
    """例外発生時のエラー記録行を生成する。"""
    return {
        'image': image_name,
        'note': entry.get('note', ''),
        'stage': 'error',
        'error': str(error_message),
        'orientation_angle': None,
        'cropped': None,
        'category': entry.get('category'),
        'read_method': None,
        'scale_confident': None,
        'coords_comparable': False,
    }


def load_completed_images(output_path):
    """既に出力JSONLに記録された画像ID（basenameまたはfull path）の集合を読み出す。

    既存の出力ファイルを走査し、末尾の不完全行のみを安全に切り詰める（stderrに警告）。
    途中行の破損は例外として拒否する（出力ファイルは変更しない）。
    末尾行に改行が不足している場合は改行を補う。
    """
    completed = set()
    if not os.path.exists(output_path):
        return completed

    with open(output_path, 'rb') as f:
        content = f.read()

    if not content:
        return completed

    raw_lines = content.splitlines(keepends=True)
    content_indices = [i for i, line in enumerate(raw_lines) if line.strip()]
    if not content_indices:
        return completed

    last_content_idx = content_indices[-1]
    last_valid_offset = 0
    needs_truncate = False

    current_offset = 0
    for i, line in enumerate(raw_lines):
        line_len = len(line)
        stripped = line.strip()
        if not stripped:
            current_offset += line_len
            continue

        is_final = (i == last_content_idx)
        try:
            parsed = json.loads(stripped.decode('utf-8'))
            if not isinstance(parsed, dict):
                raise ValueError("JSONL line must be a JSON object")
            if 'image' in parsed:
                completed.add(parsed['image'])
            last_valid_offset = current_offset + line_len
            current_offset += line_len
        except Exception as ex:
            if not is_final:
                raise ValueError(
                    f"Malformed non-final JSONL line at offset {current_offset} in {output_path}: {stripped[:50]!r}"
                ) from ex
            needs_truncate = True
            break

    if needs_truncate:
        sys.stderr.write(
            f"Warning: Truncating incomplete final line in {output_path} to offset {last_valid_offset}\n"
        )
        with open(output_path, 'r+b') as f:
            f.truncate(last_valid_offset)

    with open(output_path, 'rb') as f:
        f.seek(0, os.SEEK_END)
        cur_size = f.tell()
        if cur_size > 0:
            f.seek(cur_size - 1)
            last_byte = f.read(1)
            needs_newline = (last_byte != b'\n')
        else:
            needs_newline = False

    if needs_newline:
        with open(output_path, 'ab') as f:
            f.write(b'\n')

    return completed


def run_stage_errors(gt_path, out_path, *, local_read=False, needle_angle='segment', limit=None):
    """工程別評価のメイン処理。"""
    with open(gt_path, 'r', encoding='utf-8') as f:
        entries = json.load(f)

    base_dir = os.path.dirname(os.path.abspath(gt_path))
    basenames = [os.path.basename(e.get('image', '')) for e in entries]
    has_collision = len(basenames) != len(set(basenames))

    # --limit N: 正解データの先頭N件を対象とする（既に完了している行も含む）
    if limit is not None:
        target_entries = entries[:limit]
    else:
        target_entries = entries

    completed = load_completed_images(out_path)

    out_dir = os.path.dirname(os.path.abspath(out_path))
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)

    with open(out_path, 'a', encoding='utf-8') as out_f:
        for i, e in enumerate(target_entries):
            img_id = e.get('image', '') if has_collision else os.path.basename(e.get('image', ''))
            if img_id in completed:
                print('[%d/%d] %s (already completed, skipping)' % (i + 1, len(target_entries), img_id), flush=True)
                continue

            try:
                pts = e['points']
                if not isinstance(pts, dict) or not pts:
                    raise ValueError('points must be a non-empty dict')
                img_path = os.path.join(base_dir, e['image'])
                if not os.path.exists(img_path):
                    row = make_error_row(e, 'Image file not found: %s' % img_path, img_id)
                else:
                    img = cv2.imdecode(np.fromfile(img_path, dtype=np.uint8), cv2.IMREAD_COLOR)
                    if img is None:
                        row = make_error_row(e, 'Failed to decode image: %s' % img_path, img_id)
                    else:
                        r = meter_pipeline.read_meter(
                            img,
                            use_vlm=False,
                            local_read=local_read,
                            needle_angle=needle_angle,
                        )
                        row = compute_stage_row(e, r, pts, img_id)
            except Exception as ex:
                row = make_error_row(e, str(ex), img_id)

            out_f.write(json.dumps(row, ensure_ascii=False) + '\n')
            out_f.flush()
            completed.add(img_id)

            err_str = ('%.2f' % row['err_fs']) if 'err_fs' in row else '-'
            print('[%d/%d] %s stage=%s err=%s' % (i + 1, len(target_entries), row['image'], row.get('stage'), err_str), flush=True)


def _nonnegative_int(val):
    ival = int(val)
    if ival < 0:
        raise argparse.ArgumentTypeError('limit must be non-negative, got %s' % val)
    return ival


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description='合成画像の工程別誤差評価')
    parser.add_argument('groundtruth', help='正解データJSONファイルパス')
    parser.add_argument('-o', '--output', required=True, help='出力JSONLファイルパス')
    parser.add_argument('--local-read', action='store_true', default=False, help='局所読み取りを使用する')
    parser.add_argument('--needle-angle', choices=('segment', 'tip'), default='segment', help='針の角度検出元 (既定: segment)')
    parser.add_argument('--limit', type=_nonnegative_int, default=None, help='先頭N件のみ評価（完了済みを含む）')
    return parser.parse_args(argv)


def main():
    args = parse_args()
    run_stage_errors(
        args.groundtruth,
        args.output,
        local_read=args.local_read,
        needle_angle=args.needle_angle,
        limit=args.limit,
    )


if __name__ == '__main__':
    main()
