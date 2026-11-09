"""目視確認の一覧CSVを集計し、Markdown表で標準出力に表示する。

使い方:
    venv\\Scripts\\python.exe eval\\aggregate_review.py eval\\review_sheets\\SR_一覧.csv
    venv\\Scripts\\python.exe eval\\aggregate_review.py a.csv b.csv --out report.md

CSVは複数指定でき、行をまとめて集計する。列が足りないCSVでも止まらず、
その列を使う集計だけをスキップする。標準ライブラリだけで動作する。
"""
from __future__ import annotations

import argparse
import csv
from pathlib import Path
import statistics as st
import sys

TOLERANCE_PERCENT_FS = 5.0

COL_NUMBER = "番号"
COL_FILE = "ファイル名"
COL_CONDITION = "条件"
COL_STAGE = "止まった段階"
COL_EXPECTED_RANGE = "正解の範囲"
COL_EXPECTED_VALUE = "正解の値"
COL_READ_RANGE = "読んだ範囲"
COL_READ_VALUE = "読んだ値"
COL_ERROR = "誤差%FS"
COL_JUDGEMENT = "人の総合判定"
COL_REASON = "いちばんの原因"

# 「無い」を表す表記。数値として計算しない。
NONE_TEXTS = {
    "", "-", "ー", "—", "−", "－", "–", "n/a", "na", "なし", "無し",
}

# 「いちばんの原因」の分類ルール。上から順に最初に一致した分類を採用する。
# 分類語は eval/review_sheets/SR_一覧.csv の文章を読んで決めた。
REASON_RULES = (
    ("数字の検出", ("数字の検出", "数字検出", "数字が検出", "数字が読", "OCR", "文字の検出")),
    ("針", ("針",)),
    ("目盛り(メモリ)", ("メモリ", "目盛")),
    ("ずれ", ("ずれ", "はみ出")),
    ("範囲(最小・最大)", ("範囲", "0以下", "０以下", "負の", "マイナス", "最小", "最大")),
    ("画像が粗い", ("画像が粗い", "粗い", "画質", "解像", "低画質")),
    ("汚れ・ブレ", ("汚れ", "ブレ", "ぶれ", "ぼやけ", "かすれ", "薄い", "反射", "光", "ゴミ")),
)
UNWRITTEN_REASON = "記入なし"
OTHER_REASON = "その他"
REASON_CATEGORIES = tuple(label for label, _ in REASON_RULES) + (UNWRITTEN_REASON, OTHER_REASON)

SOURCE_KEY = "__source__"


def clean(value):
    """セル値を文字列にして前後の空白を除く。None は空文字にする。"""
    if value is None:
        return ""
    return str(value).strip()


def is_blank(value):
    """「-」や空欄など、値が無いことを表す表記かどうか。"""
    return clean(value).lower() in NONE_TEXTS


def parse_number(value):
    """数値として読める場合だけ float を返す。「-」や空欄、未検出は None。"""
    text = clean(value)
    if text.lower() in NONE_TEXTS:
        return None
    text = text.replace("%", "").replace("％", "").replace(",", "")
    try:
        return float(text)
    except ValueError:
        return None


def load_rows(paths):
    """複数のCSVを読み、ヘッダー名をキーにした行のリストを返す。

    文字コードは UTF-8（BOM付きを含む）を想定する。空行は読み飛ばす。
    各行には出典CSV名を SOURCE_KEY として持たせる。
    """
    rows = []
    for path in paths:
        path = Path(path)
        with path.open("r", encoding="utf-8-sig", newline="") as stream:
            reader = csv.DictReader(stream)
            for raw in reader:
                row = {}
                for key, value in raw.items():
                    if key is None:  # ヘッダーより列が多い行の余り
                        continue
                    row[clean(key)] = clean(value)
                if all(is_blank(value) for value in row.values()):
                    continue
                row[SOURCE_KEY] = path.name
                rows.append(row)
    return rows


def has_column(rows, name):
    return any(name in row for row in rows)


def stage_of(row):
    """止まった段階を小文字で返す。列や値が無ければ None。"""
    if COL_STAGE not in row:
        return None
    text = clean(row.get(COL_STAGE)).lower()
    if text in NONE_TEXTS:
        return None
    return text


def classify_reason(text):
    """「いちばんの原因」の文章を、キーワードで1つの分類に割り当てる。"""
    text = clean(text)
    if text.lower() in NONE_TEXTS:
        return UNWRITTEN_REASON
    lowered = text.lower()
    for label, keywords in REASON_RULES:
        if any(keyword.lower() in lowered for keyword in keywords):
            return label
    return OTHER_REASON


def summarize(rows):
    """行のリストから (a)〜(e) の集計に必要な値を計算する。"""
    summary = {
        "total": len(rows),
        "has_stage": has_column(rows, COL_STAGE),
        "has_condition": has_column(rows, COL_CONDITION),
        "has_error": has_column(rows, COL_ERROR),
        "has_reason": has_column(rows, COL_REASON),
        "ok_count": None,
        "stopped_count": None,
        "stage_counts": {},
        "conditions": None,
        "reason_counts": None,
        "reason_total": None,
        "worst": [],
    }

    if summary["has_stage"]:
        counts = {}
        for row in rows:
            stage = stage_of(row)
            if stage is None:
                continue
            counts[stage] = counts.get(stage, 0) + 1
        summary["stage_counts"] = counts
        summary["ok_count"] = counts.get("ok", 0)
        summary["stopped_count"] = sum(count for stage, count in counts.items() if stage != "ok")

    if summary["has_condition"]:
        groups = {}
        for row in rows:
            name = clean(row.get(COL_CONDITION)) or "（未記入）"
            group = groups.setdefault(
                name, {"total": 0, "unreadable": 0, "within": 0, "errors": []})
            group["total"] += 1
            stage = stage_of(row)
            if stage is not None and stage != "ok":
                group["unreadable"] += 1
            error = parse_number(row.get(COL_ERROR))
            if error is not None:
                group["errors"].append(error)
                if error <= TOLERANCE_PERCENT_FS:
                    group["within"] += 1
        summary["conditions"] = groups

    if summary["has_reason"]:
        reasons = {}
        reason_total = 0
        for row in rows:
            if COL_REASON not in row:
                continue  # 列が無いCSVの行は (d) の対象外
            reason_total += 1
            label = classify_reason(row.get(COL_REASON))
            reasons[label] = reasons.get(label, 0) + 1
        summary["reason_counts"] = reasons
        summary["reason_total"] = reason_total

    worst = []
    for row in rows:
        error = parse_number(row.get(COL_ERROR))
        if error is None:
            continue
        worst.append({
            "file": clean(row.get(COL_FILE)) or "（未記入）",
            "condition": clean(row.get(COL_CONDITION)) or "（未記入）",
            "error": error,
            "source": row.get(SOURCE_KEY, ""),
        })
    worst.sort(key=lambda item: (-item["error"], item["file"]))
    summary["worst"] = worst[:3]
    return summary


def _fmt_mean(errors):
    if not errors:
        return "-"
    return f"{st.mean(errors):.2f}"


def _ordered_stages(counts):
    order = {"ok": 0, "scale": 1, "center": 2}
    return sorted(counts.items(), key=lambda item: (order.get(item[0], 99), item[0]))


def render_markdown(summary, sources=None):
    """集計結果をMarkdown文字列にする。"""
    lines = ["# 目視確認 集計レポート", ""]
    if sources:
        names = "、".join(f"`{Path(source).name}`" for source in sources)
        lines.append(f"対象ファイル: {names}")
        lines.append("")
    lines.append(f"画像の総数: {summary['total']} 件")
    lines.append("")
    if summary["total"] == 0:
        lines.append("対象データがありません。")
        lines.append("")
        return "\n".join(lines)

    # (a) 全体
    lines.extend(["## (a) 全体", "", "| 項目 | 件数 |", "|:---|---:|"])
    lines.append(f"| 画像の数 | {summary['total']} |")
    if summary["has_stage"]:
        counts = summary["stage_counts"]
        lines.append(f"| 最後まで読めた (ok) | {summary['ok_count']} |")
        lines.append(f"| 止まった (ok以外) | {summary['stopped_count']} |")
        lines.append(f"| 　うち scale | {counts.get('scale', 0)} |")
        lines.append(f"| 　うち center | {counts.get('center', 0)} |")
        other = {stage: count for stage, count in counts.items()
                 if stage not in ("ok", "scale", "center")}
        for stage, count in _ordered_stages(other):
            lines.append(f"| 　うち {stage} | {count} |")
    else:
        lines.append("")
        lines.append("※「止まった段階」列がないため、ok/停止の内訳はスキップしました。")
    lines.append("")

    # (b) 条件ごと
    lines.extend(["## (b) 条件ごと", ""])
    if not summary["has_condition"]:
        lines.append("※「条件」列がないため、この集計はスキップしました。")
        lines.append("")
    else:
        headers = ["条件", "画像の数"]
        aligns = [":---", "---:"]
        if summary["has_stage"]:
            headers.append("読めなかった数")
            aligns.append("---:")
        if summary["has_error"]:
            headers.extend(["許容内 (5%FS以下)", "誤差平均 (%FS)"])
            aligns.extend(["---:", "---:"])
        lines.append("| " + " | ".join(headers) + " |")
        lines.append("| " + " | ".join(aligns) + " |")

        totals = {"total": 0, "unreadable": 0, "within": 0, "errors": []}
        for name, group in summary["conditions"].items():
            cells = [name, str(group["total"])]
            if summary["has_stage"]:
                cells.append(str(group["unreadable"]))
            if summary["has_error"]:
                cells.append(str(group["within"]))
                cells.append(_fmt_mean(group["errors"]))
            lines.append("| " + " | ".join(cells) + " |")
            totals["total"] += group["total"]
            totals["unreadable"] += group["unreadable"]
            totals["within"] += group["within"]
            totals["errors"].extend(group["errors"])

        cells = ["合計", str(totals["total"])]
        if summary["has_stage"]:
            cells.append(str(totals["unreadable"]))
        if summary["has_error"]:
            cells.append(str(totals["within"]))
            cells.append(_fmt_mean(totals["errors"]))
        lines.append("| " + " | ".join(cells) + " |")
        lines.append("")

    # (c) 止まった段階ごとの件数
    lines.extend(["## (c) 止まった段階ごとの件数", ""])
    if not summary["has_stage"]:
        lines.append("※「止まった段階」列がないため、この集計はスキップしました。")
        lines.append("")
    elif not summary["stage_counts"]:
        lines.append("止まった段階が記入された行はありません。")
        lines.append("")
    else:
        staged = sum(summary["stage_counts"].values())
        lines.append("| 止まった段階 | 件数 | 割合 |")
        lines.append("|:---|---:|---:|")
        for stage, count in _ordered_stages(summary["stage_counts"]):
            lines.append(f"| {stage} | {count} | {count / staged * 100:.1f}% |")
        lines.append("")

    # (d) いちばんの原因の分類
    lines.extend(["## (d) 「いちばんの原因」の分類", ""])
    if not summary["has_reason"]:
        lines.append("※「いちばんの原因」列がないため、この集計はスキップしました。")
        lines.append("")
    else:
        if summary["reason_total"] != summary["total"]:
            lines.append(
                f"※「いちばんの原因」列がある {summary['reason_total']} 件のみを対象にしています。")
            lines.append("")
        lines.append("| 分類 | 件数 |")
        lines.append("|:---|---:|")
        for label in REASON_CATEGORIES:
            count = summary["reason_counts"].get(label, 0)
            lines.append(f"| {label} | {count} |")
        lines.append("")

    # (e) 誤差が大きい画像ワースト3
    lines.extend(["## (e) 誤差が大きい画像 ワースト3", ""])
    if not summary["has_error"]:
        lines.append("※「誤差%FS」列がないため、この集計はスキップしました。")
        lines.append("")
    elif not summary["worst"]:
        lines.append("誤差%FSを数値として読めた画像はありません。")
        lines.append("")
    else:
        lines.append("| 順位 | ファイル名 | 条件 | 誤差%FS | 出典 |")
        lines.append("|:---:|:---|:---|---:|:---|")
        for rank, item in enumerate(summary["worst"], start=1):
            lines.append(
                f"| {rank} | {item['file']} | {item['condition']} | "
                f"{item['error']:.2f} | {item['source']} |")
        lines.append("")

    return "\n".join(lines)


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="目視確認の一覧CSVを集計し、Markdown表で出力する")
    parser.add_argument("csv_files", nargs="+", help="集計するCSVファイル（複数指定可）")
    parser.add_argument("--out", help="Markdownを書き出すファイルパス")
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    rows = load_rows(args.csv_files)
    text = render_markdown(summarize(rows), args.csv_files)
    if not text.endswith("\n"):
        text += "\n"
    if args.out:
        output = Path(args.out)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(text, encoding="utf-8")
    sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
