"""合成画像の読み取り結果を目視確認するための確認用画像と確認シートを生成するスクリプト。

主な機能:
1. 不合格画像抽出 (--pick):
   stage_errors.jsonl から条件(category)が均等になるよう N 枚を選定して出力する。
2. 目視確認用オーバーレイ描画・確認シート作成:
   正解と検出結果を画像に重ねて描画し（検出物それぞれに N1, N2..., T1, T2... などの番号を付与）、
   1枚ごとの個別確認シート `<番号3桁>_<元のファイル名>_確認.csv` と、
   全体の一覧シート `確認シート一覧.csv` を生成する。
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import os
import random
import sys
from collections import Counter
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

# リポジトリ直下を sys.path に追加
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

import meter_pipeline
import meter_reader
import scale_value_detect
import tick_detect
from manager.overlay import imread_ja

SUMMARY_COLUMNS = [
    "番号",
    "ファイル名",
    "条件",
    "止まった段階",
    "正解の範囲",
    "正解の値",
    "読んだ範囲",
    "読んだ値",
    "誤差%FS",
    "人の総合判定(○×)",
    "いちばんの原因",
]

INDIVIDUAL_COLUMNS = [
    "段階",
    "項目",
    "検出した内容",
    "位置",
    "スコア",
    "対応目盛り",
    "範囲判定への使用",
    "人が読んだもの",
    "合っているか(○×)",
    "メモ",
]


def imwrite_ja(path: str, img: np.ndarray) -> bool:
    """全角パス対応の画像書き込み。"""
    ext = os.path.splitext(path)[1] or ".png"
    ok, buf = cv2.imencode(ext, img)
    if ok:
        buf.tofile(path)
    return bool(ok)


def is_failure(row: Dict[str, Any]) -> bool:
    """外れた画像（範囲が誤り、または誤差2.5%FS超、または値が出ない）かどうかを判定。"""
    # 値が出ない（stage != 'ok' または err_fs is None）
    if row.get("stage") != "ok" or row.get("err_fs") is None:
        return True
    # 範囲が誤り
    if row.get("range_ok") is False:
        return True
    # 誤差2.5%FS超
    err_fs = row.get("err_fs")
    if err_fs is not None and err_fs > 2.5:
        return True
    return False


def _load_exclude_set(exclude_args: Optional[Sequence[str]]) -> Set[str]:
    """--exclude 引数から除外ファイル名（basename）のセットを構築する。"""
    exclude_set: Set[str] = set()
    if not exclude_args:
        return exclude_set

    for item in exclude_args:
        if os.path.isfile(item):
            with open(item, "r", encoding="utf-8") as f:
                for line in f:
                    name = line.strip()
                    if name:
                        exclude_set.add(os.path.basename(name))
        else:
            for part in item.split(","):
                part = part.strip()
                if part:
                    exclude_set.add(os.path.basename(part))
    return exclude_set


def _load_exclude_categories(exclude_cat_args: Optional[Sequence[str]]) -> Set[str]:
    """--exclude-category 引数から除外カテゴリ名のセットを構築する。"""
    exclude_cats: Set[str] = set()
    if not exclude_cat_args:
        return exclude_cats

    for item in exclude_cat_args:
        for part in item.split(","):
            part = part.strip()
            if part:
                exclude_cats.add(part)
    return exclude_cats


def pick_review_images(
    jsonl_paths: Sequence[str],
    n: int = 20,
    seed: int = 1,
    exclude: Optional[Sequence[str]] = None,
    exclude_categories: Optional[Sequence[str]] = None,
) -> Tuple[List[str], Dict[str, int]]:
    """stage_errors.jsonl群から失敗画像を条件(category)ごとに均等に選出する。

    戻り値:
        (選出されたファイル名(basename)のリスト, 条件ごとの枚数辞書)
    """
    exclude_files = _load_exclude_set(exclude)
    exclude_cats = _load_exclude_categories(exclude_categories)

    # 複数ファイルは後勝ちで上書き統合する
    combined: Dict[str, Dict[str, Any]] = {}
    for path in jsonl_paths:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                row = json.loads(line)
                img_key = os.path.basename(row.get("image", ""))
                if img_key:
                    combined[img_key] = row

    # 失敗かつ除外対象外の行を抽出
    candidates_by_cat: Dict[str, List[Dict[str, Any]]] = {}
    for img_key, row in combined.items():
        if img_key in exclude_files:
            continue
        cat = row.get("category") or "unknown"
        if cat in exclude_cats:
            continue
        if is_failure(row):
            candidates_by_cat.setdefault(cat, []).append(row)

    categories = sorted(candidates_by_cat.keys())
    rng = random.Random(seed)
    for cat in categories:
        candidates_by_cat[cat].sort(key=lambda r: os.path.basename(r.get("image", "")))
        rng.shuffle(candidates_by_cat[cat])

    selected_rows: List[Dict[str, Any]] = []
    cat_indices = {cat: 0 for cat in categories}

    while len(selected_rows) < n and any(
        cat_indices[cat] < len(candidates_by_cat[cat]) for cat in categories
    ):
        for cat in categories:
            if len(selected_rows) >= n:
                break
            idx = cat_indices[cat]
            if idx < len(candidates_by_cat[cat]):
                selected_rows.append(candidates_by_cat[cat][idx])
                cat_indices[cat] += 1

    selected_names = [os.path.basename(r.get("image", "")) for r in selected_rows]
    category_counts = dict(Counter(r.get("category", "unknown") for r in selected_rows))

    return selected_names, category_counts


def _get_font(size: int) -> ImageFont.ImageFont:
    """Windows標準のMeiryoフォント（なければ代替フォント）を読み込む。"""
    font_candidates = [
        r"C:\Windows\Fonts\meiryo.ttc",
        r"C:\Windows\Fonts\msgothic.ttc",
        r"C:\Windows\Fonts\msmincho.ttc",
        "meiryo.ttc",
        "Arial.ttf",
    ]
    for font_path in font_candidates:
        if os.path.exists(font_path):
            try:
                return ImageFont.truetype(font_path, size)
            except Exception:
                pass
    try:
        return ImageFont.load_default()
    except Exception:
        return None


def _draw_text_with_outline(
    draw: ImageDraw.ImageDraw,
    pos: Tuple[float, float],
    text: str,
    font: Any,
    fill: Tuple[int, int, int],
    outline: Tuple[int, int, int] = (0, 0, 0),
    outline_width: int = 2,
) -> None:
    """縁取り付きでテキストを描画する。"""
    x, y = pos
    if outline_width > 0:
        for dx in range(-outline_width, outline_width + 1):
            for dy in range(-outline_width, outline_width + 1):
                if dx != 0 or dy != 0:
                    draw.text((x + dx, y + dy), text, font=font, fill=outline)
    draw.text((x, y), text, font=font, fill=fill)


def analyze_stage_intermediates(
    image: np.ndarray,
    result: Dict[str, Any],
    ocr_numbers: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """読み取り処理の段階ごとの中間結果を整理する。

    戻り値:
        ticks: 目盛りリスト (各要素に _id: 'T1'.. を付与)
        ocr_items: OCR数字リスト (各要素に id: 'N1'.., bound_tick_id, used_in_range を付与)
        needle: 針検出結果 dict
    """
    center = result.get("center")
    ticks = list(result.get("ticks") or [])
    if not ticks and center is not None:
        try:
            enhanced = tick_detect.apply_clahe(image, clip_limit=2.0)
            ticks = tick_detect.detect_scale_ticks(enhanced, center)
        except Exception:
            ticks = []

    for i, t in enumerate(ticks):
        t["_id"] = f"T{i + 1}"

    if ocr_numbers is None:
        try:
            ocr_numbers = scale_value_detect.read_scale_numbers(image)
        except Exception:
            ocr_numbers = []

    pairs = []
    if center is not None and ticks and ocr_numbers:
        try:
            pairs = scale_value_detect._bind_number_tick_indices(
                ocr_numbers, ticks, center, max_angle_deg=12.0, major_bonus_deg=4.0
            )
        except Exception:
            pairs = []

    num_to_tick_idx: Dict[Tuple[float, float, float], int] = {}
    for n_dict, t_idx in pairs:
        key = (float(n_dict.get("value", 0)), round(float(n_dict.get("x", 0)), 1), round(float(n_dict.get("y", 0)), 1))
        num_to_tick_idx[key] = t_idx

    # 範囲に使われた数字の推定
    min_v = result.get("min_value")
    max_v = result.get("max_value")
    used_values = set()
    if min_v is not None and max_v is not None:
        used_values.add(min_v)
        used_values.add(max_v)
        if pairs:
            try:
                bound_objs = [
                    {"value": n["value"], "tick": ticks[t_idx], "angle": ticks[t_idx]["angle"]}
                    for n, t_idx in pairs
                ]
                n_ocr_unique = len({n["value"] for n in ocr_numbers})
                det = scale_value_detect.determine_min_max(
                    bound_objs, min_points=3, n_ocr_unique=n_ocr_unique, ticks=ticks
                )
                if det and det.get("min_value") == min_v and det.get("max_value") == max_v:
                    n_used = det.get("n_used", 1)
                    if n_used > 1:
                        step = (max_v - min_v) / (n_used - 1)
                        for n, _ in pairs:
                            v = n["value"]
                            if min_v <= v <= max_v and (abs((v - min_v) % step) < 1e-4 or abs((v - min_v) % step - step) < 1e-4):
                                used_values.add(v)
            except Exception:
                pass

    ocr_items = []
    for idx, num in enumerate(ocr_numbers, start=1):
        n_id = f"N{idx}"
        val = num.get("value")
        score = num.get("score", 0.0)
        nx = float(num.get("x", 0))
        ny = float(num.get("y", 0))
        key = (float(val), round(nx, 1), round(ny, 1))
        t_idx = num_to_tick_idx.get(key)
        bound_tick_id = f"T{t_idx + 1}" if t_idx is not None else "なし"

        if min_v is None:
            used_str = "不明" if result.get("stage") == "scale" else "×"
        elif val in used_values and bound_tick_id != "なし":
            used_str = "○"
        else:
            used_str = "×"

        ocr_items.append({
            "id": n_id,
            "value": val,
            "x": nx,
            "y": ny,
            "score": score,
            "bound_tick_id": bound_tick_id,
            "used_in_range": used_str,
        })

    needle = None
    if center is not None:
        try:
            needle = meter_reader.detect_needle(image, center)
        except Exception:
            needle = None

    return {
        "ticks": ticks,
        "ocr_items": ocr_items,
        "needle": needle,
    }


def render_review_overlay(
    image: np.ndarray,
    entry: Dict[str, Any],
    result: Dict[str, Any],
    ocr_numbers: Optional[List[Dict[str, Any]]] = None,
    intermediates: Optional[Dict[str, Any]] = None,
) -> np.ndarray:
    """元の画像に正解（緑）と検出（赤・青・黄）および検出番号ラベル(N1, T1...)を描画した画像を返す。"""
    out = image.copy()
    h, w = out.shape[:2]

    if intermediates is None:
        intermediates = analyze_stage_intermediates(image, result, ocr_numbers)

    ticks = intermediates.get("ticks") or []
    ocr_items = intermediates.get("ocr_items") or []
    needle = intermediates.get("needle")

    center = result.get("center")

    # --- 1. 検出目盛り線（青）と目盛り番号(T1, T2...) ---
    bound_tick_ids = {item["bound_tick_id"] for item in ocr_items}
    tick_draw_positions = []
    if ticks:
        for tick in ticks:
            centroid = tick.get("centroid")
            if centroid is None:
                continue
            cx, cy = float(centroid[0]), float(centroid[1])
            line_angle = tick.get("line_angle")
            if line_angle is None:
                line_angle = tick.get("angle", 0.0)
            length = max(float(tick.get("length", 12.0)), 10.0)
            dx = math.cos(line_angle) * (length / 2.0)
            dy = math.sin(line_angle) * (length / 2.0)
            p1 = (int(round(cx - dx)), int(round(cy - dy)))
            p2 = (int(round(cx + dx)), int(round(cy + dy)))
            is_major = tick.get("is_major", False)
            thickness = 3 if is_major else 1
            cv2.line(out, p1, p2, (255, 0, 0), thickness)  # 青(BGR)

            t_id = tick.get("_id", "")
            # 主目盛り、またはOCRに対応付けられた目盛りには番号T1..を描画
            if is_major or t_id in bound_tick_ids:
                # 外側端点寄りにラベル配置
                lx = int(round(cx + dx * 1.4))
                ly = int(round(cy + dy * 1.4))
                tick_draw_positions.append((lx, ly, t_id, is_major))

    # --- 2. 検出中心（赤の十字） ---
    if center is not None:
        cx, cy = int(round(center[0])), int(round(center[1]))
        cv2.drawMarker(out, (cx, cy), (0, 0, 255), cv2.MARKER_CROSS, 36, 3)

    # --- 3. 検出0点・満尺点（赤の点） ---
    if result.get("zero_pt") is not None:
        zx, zy = int(round(result["zero_pt"][0])), int(round(result["zero_pt"][1]))
        cv2.circle(out, (zx, zy), 8, (0, 0, 255), -1)
    if result.get("full_pt") is not None:
        fx, fy = int(round(result["full_pt"][0])), int(round(result["full_pt"][1]))
        cv2.circle(out, (fx, fy), 8, (0, 0, 255), -1)

    # --- 4. 検出針（赤の線） ---
    if needle is not None and center is not None:
        if needle.get("line") is not None:
            x1, y1, x2, y2 = [int(round(v)) for v in needle["line"]]
            cv2.line(out, (x1, y1), (x2, y2), (0, 0, 255), 3)
        elif needle.get("tip") is not None:
            tx, ty = int(round(needle["tip"][0])), int(round(needle["tip"][1]))
            cv2.line(out, (int(round(center[0])), int(round(center[1]))), (tx, ty), (0, 0, 255), 3)

    # --- 5. 正解情報の描画（緑） ---
    gt_pts = entry.get("points", {})
    gt_c = gt_pts.get("center")
    if gt_c is not None:
        gx, gy = int(round(gt_c[0])), int(round(gt_c[1]))
        cv2.drawMarker(out, (gx, gy), (0, 255, 0), cv2.MARKER_CROSS, 44, 2)

    for k in ("zero_pt", "full_pt"):
        pt = gt_pts.get(k)
        if pt is not None:
            px, py = int(round(pt[0])), int(round(pt[1]))
            cv2.circle(out, (px, py), 8, (0, 255, 0), -1)

    gt_needle_tip = gt_pts.get("needle_tip")
    if gt_needle_tip is not None:
        nx, ny = int(round(gt_needle_tip[0])), int(round(gt_needle_tip[1]))
        cv2.circle(out, (nx, ny), 8, (0, 255, 0), -1)

    for nt in gt_pts.get("numbered_ticks", []):
        tx, ty = int(round(nt["x"])), int(round(nt["y"]))
        cv2.circle(out, (tx, ty), 4, (0, 255, 0), -1)

    # --- 6. PILによる文字描画（アンチエイリアス・日本語・番号ラベル） ---
    header_h = min(150, max(120, int(h * 0.16)))
    overlay = out.copy()
    cv2.rectangle(overlay, (0, 0), (w, header_h), (20, 20, 20), -1)
    cv2.addWeighted(overlay, 0.8, out, 0.2, 0, out)

    pil_img = Image.fromarray(cv2.cvtColor(out, cv2.COLOR_BGR2RGB))
    draw = ImageDraw.Draw(pil_img)

    font_header = _get_font(18)
    font_small = _get_font(13)
    font_num = _get_font(15)
    font_tick = _get_font(12)

    # 目盛り番号(T1, T2...)の描画
    for lx, ly, t_id, is_maj in tick_draw_positions:
        color = (180, 230, 255) if is_maj else (130, 190, 255)
        _draw_text_with_outline(draw, (lx - 8, ly - 8), t_id, font_tick, fill=color, outline=(0, 0, 0), outline_width=1)

    # 正解数字付き目盛りの値（緑文字）
    for nt in gt_pts.get("numbered_ticks", []):
        tx, ty = float(nt["x"]), float(nt["y"])
        val_str = f"{nt['value']:g}"
        _draw_text_with_outline(draw, (tx + 6, ty - 12), f"正解:{val_str}", font_num, fill=(0, 255, 0), outline=(0, 0, 0), outline_width=2)

    # OCR数字の位置と番号ラベル（黄文字 N1: 50 など）
    for item in ocr_items:
        nx, ny = item["x"], item["y"]
        val_str = f"{item['value']:g}"
        label_text = f"{item['id']}: {val_str}"
        draw.ellipse([(nx - 3, ny - 3), (nx + 3, ny + 3)], fill=(255, 255, 0), outline=(0, 0, 0))
        _draw_text_with_outline(draw, (nx + 5, ny - 14), label_text, font_num, fill=(255, 255, 0), outline=(0, 0, 0), outline_width=2)

    # 検出物の補助文字（中心、0点、満尺点、針）
    if center is not None:
        _draw_text_with_outline(draw, (center[0] + 8, center[1] - 8), "中心", font_tick, fill=(255, 100, 100), outline=(0, 0, 0), outline_width=1)
    if result.get("zero_pt") is not None:
        _draw_text_with_outline(draw, (result["zero_pt"][0] + 8, result["zero_pt"][1] - 8), "0点", font_tick, fill=(255, 100, 100), outline=(0, 0, 0), outline_width=1)
    if result.get("full_pt") is not None:
        _draw_text_with_outline(draw, (result["full_pt"][0] + 8, result["full_pt"][1] - 8), "満尺", font_tick, fill=(255, 100, 100), outline=(0, 0, 0), outline_width=1)
    if needle is not None and needle.get("tip") is not None:
        _draw_text_with_outline(draw, (needle["tip"][0] + 8, needle["tip"][1] - 8), "針", font_tick, fill=(255, 100, 100), outline=(0, 0, 0), outline_width=1)

    # 上部テキスト（日本語3〜4行 + 凡例1行）
    gt_min = entry.get("min_value")
    gt_max = entry.get("max_value")
    gt_range_str = f"{gt_min:g}〜{gt_max:g}" if (gt_min is not None and gt_max is not None) else "-"
    pred_min = result.get("min_value")
    pred_max = result.get("max_value")
    pred_range_str = f"{pred_min:g}〜{pred_max:g}" if (pred_min is not None and pred_max is not None) else "-"

    gt_val = entry.get("true_value")
    gt_val_str = f"{gt_val:g}" if gt_val is not None else "-"
    pred_val = result.get("value")
    span = abs(gt_max - gt_min) if (gt_min is not None and gt_max is not None) else 0.0

    if pred_val is not None and gt_val is not None and span > 0:
        err_fs = abs(pred_val - gt_val) / span * 100.0
        val_line = f"正解の値 {gt_val_str} / 読んだ値 {pred_val:.2f} (誤差 {err_fs:.2f}%FS)"
    else:
        pred_str = f"{pred_val:.2f}" if pred_val is not None else "-"
        val_line = f"正解の値 {gt_val_str} / 読んだ値 {pred_str} (誤差 -)"

    stage_str = result.get("stage") or "-"
    cat_str = entry.get("category") or "-"
    note_str = entry.get("note") or ""
    cond_detail = f"条件: {cat_str}" + (f" ({note_str})" if note_str else "")

    line1 = f"正解の範囲 {gt_range_str} / 読んだ範囲 {pred_range_str}"
    line2 = val_line
    line3 = f"止まった段階: {stage_str}    {cond_detail}"
    line4 = "凡例: [緑]正解(十字=中心,点=0/満/針先,文字=正解値)  [赤]検出(十字=中心,点=0/満,線=針)  [青]検出目盛りT1..  [黄]OCR数字N1.."

    lines = [
        (line1, (255, 255, 255), font_header),
        (line2, (255, 255, 255), font_header),
        (line3, (255, 255, 200), font_header),
        (line4, (180, 230, 255), font_small),
    ]

    y_offset = 8
    line_step = max(24, int(header_h / (len(lines) + 0.5)))
    for text, color, font in lines:
        if font is not None:
            _draw_text_with_outline(draw, (14, y_offset), text, font, fill=color, outline=(0, 0, 0), outline_width=2)
        y_offset += line_step

    final_img = cv2.cvtColor(np.array(pil_img), cv2.COLOR_RGB2BGR)
    return final_img


def build_individual_sheet_rows(
    entry: Dict[str, Any],
    result: Dict[str, Any],
    intermediates: Dict[str, Any],
    error_msg: Optional[str] = None,
) -> List[Dict[str, str]]:
    """1枚の画像に対する段階ごとの確認シート行を生成する。"""
    rows: List[Dict[str, str]] = []

    def _make_row(
        stage: str,
        item: str,
        content: str,
        pos: str = "-",
        score: str = "-",
        bound_tick: str = "-",
        used: str = "-",
        memo: str = "",
    ) -> Dict[str, str]:
        return {
            "段階": stage,
            "項目": item,
            "検出した内容": content,
            "位置": pos,
            "スコア": score,
            "対応目盛り": bound_tick,
            "範囲判定への使用": used,
            "人が読んだもの": "",
            "合っているか(○×)": "",
            "メモ": memo,
        }

    if error_msg:
        rows.append(_make_row("エラー", "例外発生", "読み取り処理中に例外が発生しました", memo=error_msg))
        return rows

    center = result.get("center")
    ticks = intermediates.get("ticks") or []
    ocr_items = intermediates.get("ocr_items") or []
    needle = intermediates.get("needle")

    # 1. 段階①中心
    if center is not None:
        c_str = f"({center[0]:.1f}, {center[1]:.1f})"
        rows.append(_make_row("段階①中心", "中心座標", c_str, pos=c_str))
    else:
        rows.append(_make_row("段階①中心", "中心座標", "未検出"))

    # 2. 段階②目盛り
    if ticks:
        n_maj = sum(1 for t in ticks if t.get("is_major"))
        tick_content = f"全体: {len(ticks)}本, 主目盛り: {n_maj}本"
        rows.append(_make_row("段階②目盛り", "目盛り本数", tick_content))
    else:
        rows.append(_make_row("段階②目盛り", "目盛り本数", "未検出"))

    # 3. 段階③数字（OCR）
    if ocr_items:
        for item in ocr_items:
            pos_str = f"({item['x']:.1f}, {item['y']:.1f})"
            val_str = f"{item['value']:g}" if item["value"] is not None else "-"
            score_str = f"{item['score']:.3f}"
            rows.append(_make_row(
                "段階③数字(OCR)",
                item["id"],
                val_str,
                pos=pos_str,
                score=score_str,
                bound_tick=item["bound_tick_id"],
                used=item["used_in_range"],
            ))
    else:
        rows.append(_make_row("段階③数字(OCR)", "OCR検出", "未検出"))

    # 「OCRが読まなかった目盛りの数字」を書く空欄の行を1行
    rows.append(_make_row("段階③数字(OCR)", "OCRが読まなかった目盛りの数字", "-"))

    # 4. 段階④範囲
    pred_min = result.get("min_value")
    pred_max = result.get("max_value")
    if pred_min is not None and pred_max is not None:
        range_content = f"{pred_min:g}〜{pred_max:g}"
    else:
        range_content = "未検出"

    zero_pt = result.get("zero_pt")
    full_pt = result.get("full_pt")
    z_str = f"({zero_pt[0]:.1f}, {zero_pt[1]:.1f})" if zero_pt is not None else "未検出"
    f_str = f"({full_pt[0]:.1f}, {full_pt[1]:.1f})" if full_pt is not None else "未検出"
    pos_range = f"0点: {z_str}, 満尺点: {f_str}"
    rows.append(_make_row("段階④範囲", "最小値・最大値", range_content, pos=pos_range))

    # 5. 段階⑤針
    angle_deg = result.get("angle_deg")
    if angle_deg is None and needle is not None:
        angle_deg = needle.get("angle_deg")
    angle_content = f"{angle_deg:.1f}度" if angle_deg is not None else "未検出"

    tip = None
    if needle is not None:
        tip = needle.get("tip")
    tip_str = f"針先: ({tip[0]:.1f}, {tip[1]:.1f})" if tip is not None else "針先: 未検出"
    rows.append(_make_row("段階⑤針", "針角度・針先", angle_content, pos=tip_str))

    # 6. 段階⑥値
    pred_val = result.get("value")
    gt_val = entry.get("true_value")
    gt_min = entry.get("min_value")
    gt_max = entry.get("max_value")
    span = abs(gt_max - gt_min) if (gt_min is not None and gt_max is not None) else 0.0
    gt_val_str = f"{gt_val:g}" if gt_val is not None else "-"

    if pred_val is not None and gt_val is not None and span > 0:
        err_fs = abs(pred_val - gt_val) / span * 100.0
        val_content = f"読んだ値: {pred_val:.2f} (正解: {gt_val_str}, 誤差: {err_fs:.2f}%FS)"
    elif pred_val is not None:
        val_content = f"読んだ値: {pred_val:.2f} (正解: {gt_val_str})"
    else:
        val_content = f"読んだ値: 未検出 (正解: {gt_val_str})"
    rows.append(_make_row("段階⑥値", "読み取り値", val_content))

    return rows


def write_csv_utf8_sig(csv_path: str, columns: Sequence[str], rows: List[Dict[str, Any]]) -> None:
    """CSVを utf-8-sig (Excel互換) で出力する。"""
    with open(csv_path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(columns)
        for r in rows:
            writer.writerow([r.get(col, "") for col in columns])


def generate_review_artifacts(
    gt_path: str,
    images_list_path: Optional[str] = None,
    out_dir: str = "eval/review_overlays",
    local_read: bool = False,
) -> Tuple[int, List[Dict[str, Any]]]:
    """指定された正解JSONと画像群から確認用オーバーレイ画像と確認シート群を生成する。

    戻り値:
        (生成成功枚数, 全体確認シート一覧の行データリスト)
    """
    os.makedirs(out_dir, exist_ok=True)

    with open(gt_path, "r", encoding="utf-8") as f:
        entries = json.load(f)

    # ターゲット画像リストの絞り込み
    target_names: Optional[Set[str]] = None
    ordered_target_names: Optional[List[str]] = None
    if images_list_path is not None:
        ordered_target_names = []
        with open(images_list_path, "r", encoding="utf-8") as f:
            for line in f:
                name = line.strip()
                if name:
                    base = os.path.basename(name)
                    ordered_target_names.append(base)
        target_names = set(ordered_target_names)

    # 画像名から entry を引くマップ
    entry_map: Dict[str, Dict[str, Any]] = {}
    for e in entries:
        base = os.path.basename(e.get("image", ""))
        if base:
            entry_map[base] = e

    if ordered_target_names is not None:
        target_entries = [entry_map[name] for name in ordered_target_names if name in entry_map]
    else:
        target_entries = entries

    base_dir = os.path.dirname(os.path.abspath(gt_path))
    summary_rows: List[Dict[str, Any]] = []
    success_count = 0

    for idx, entry in enumerate(target_entries, start=1):
        num_str = f"{idx:03d}"
        img_rel_or_abs = entry.get("image", "")
        file_name = os.path.basename(img_rel_or_abs)
        cat = entry.get("category", "")
        gt_min = entry.get("min_value")
        gt_max = entry.get("max_value")
        gt_val = entry.get("true_value")
        span = abs(gt_max - gt_min) if (gt_min is not None and gt_max is not None) else 0.0

        gt_range_str = f"{gt_min:g}〜{gt_max:g}" if (gt_min is not None and gt_max is not None) else "-"
        gt_val_str = f"{gt_val:g}" if gt_val is not None else "-"

        # 画像パスの解決
        img_path = img_rel_or_abs
        if not os.path.isabs(img_path):
            img_path = os.path.normpath(os.path.join(base_dir, img_path))
        if not os.path.exists(img_path):
            candidate = os.path.join(base_dir, file_name)
            if os.path.exists(candidate):
                img_path = candidate

        base_without_ext = os.path.splitext(file_name)[0]
        indiv_csv_name = f"{num_str}_{base_without_ext}_確認.csv"
        indiv_csv_path = os.path.join(out_dir, indiv_csv_name)

        try:
            img = imread_ja(img_path)
            if img is None:
                raise FileNotFoundError(f"Image not found or unreadable: {img_path}")

            # 読み取り処理実行
            res = meter_pipeline.read_meter(img, use_vlm=False, local_read=local_read)

            pred_min = res.get("min_value")
            pred_max = res.get("max_value")
            pred_range_str = f"{pred_min:g}〜{pred_max:g}" if (pred_min is not None and pred_max is not None) else "-"

            pred_val = res.get("value")
            if pred_val is not None and gt_val is not None and span > 0:
                err_fs = abs(pred_val - gt_val) / span * 100.0
                err_fs_str = f"{err_fs:.2f}"
                pred_val_str = f"{pred_val:.2f}"
            else:
                err_fs_str = "-"
                pred_val_str = f"{pred_val:.2f}" if pred_val is not None else "-"

            stage_str = res.get("stage") or "error"

            # 中間結果の取得
            intermediates = analyze_stage_intermediates(img, res)

            # オーバーレイ画像の保存
            overlay_img = render_review_overlay(img, entry, res, intermediates=intermediates)
            out_img_name = f"{num_str}_{file_name}"
            out_img_path = os.path.join(out_dir, out_img_name)
            imwrite_ja(out_img_path, overlay_img)
            success_count += 1

            # 個別確認シートの出力
            indiv_rows = build_individual_sheet_rows(entry, res, intermediates)
            write_csv_utf8_sig(indiv_csv_path, INDIVIDUAL_COLUMNS, indiv_rows)

            summary_rows.append({
                "番号": num_str,
                "ファイル名": file_name,
                "条件": cat,
                "止まった段階": stage_str,
                "正解の範囲": gt_range_str,
                "正解の値": gt_val_str,
                "読んだ範囲": pred_range_str,
                "読んだ値": pred_val_str,
                "誤差%FS": err_fs_str,
                "人の総合判定(○×)": "",
                "いちばんの原因": "",
            })

        except Exception as ex:
            indiv_rows = build_individual_sheet_rows(entry, {}, {}, error_msg=str(ex))
            write_csv_utf8_sig(indiv_csv_path, INDIVIDUAL_COLUMNS, indiv_rows)

            summary_rows.append({
                "番号": num_str,
                "ファイル名": file_name,
                "条件": cat,
                "止まった段階": "error",
                "正解の範囲": gt_range_str,
                "正解の値": gt_val_str,
                "読んだ範囲": "-",
                "読んだ値": "-",
                "誤差%FS": "-",
                "人の総合判定(○×)": "",
                "いちばんの原因": f"例外発生: {ex}",
            })

    # 全体一覧シートの出力
    summary_csv_path = os.path.join(out_dir, "確認シート一覧.csv")
    write_csv_utf8_sig(summary_csv_path, SUMMARY_COLUMNS, summary_rows)

    return success_count, summary_rows


def main() -> None:
    parser = argparse.ArgumentParser(
        description="目視確認用の確認用画像と確認シートを生成するスクリプト"
    )
    # --pick モード
    parser.add_argument("--pick", nargs="+", default=None, help="stage_errors.jsonl のパス（複数指定可）")
    parser.add_argument("--n", type=int, default=20, help="選ぶ枚数（既定: 20）")
    parser.add_argument("--seed", type=int, default=1, help="乱数シード（既定: 1）")
    parser.add_argument("--exclude", nargs="*", default=None, help="除外するファイル名またはリストファイルのパス")
    parser.add_argument("--exclude-category", nargs="*", default=None, help="除外する条件（category）のリスト")

    # 生成モード
    parser.add_argument("groundtruth", nargs="?", default=None, help="正解JSONのパス")
    parser.add_argument("--images", type=str, default=None, help="画像のファイル名を並べたテキストファイル（無指定なら全件）")
    parser.add_argument("--out", type=str, default="eval/review_overlays", help="出力フォルダ")
    parser.add_argument("--local-read", action="store_true", help="局所読み取りを使用する")

    args = parser.parse_args()

    # 1. --pick モード
    if args.pick:
        selected_names, category_counts = pick_review_images(
            args.pick,
            n=args.n,
            seed=args.seed,
            exclude=args.exclude,
            exclude_categories=args.exclude_category,
        )
        sys.stderr.write(f"選定枚数: {len(selected_names)}枚\n条件ごとの枚数:\n")
        for cat, cnt in sorted(category_counts.items()):
            sys.stderr.write(f"  {cat}: {cnt}枚\n")

        for name in selected_names:
            print(name)
        return

    # 2. 生成モード
    if not args.groundtruth:
        parser.error("正解JSONのパス (groundtruth) または --pick を指定してください。")

    count, rows = generate_review_artifacts(
        args.groundtruth,
        images_list_path=args.images,
        out_dir=args.out,
        local_read=args.local_read,
    )
    print(f"完了: {count}枚の画像、個別確認シート、および {args.out}/確認シート一覧.csv を生成しました。")


if __name__ == "__main__":
    main()
