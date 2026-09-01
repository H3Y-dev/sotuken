#!/usr/bin/env python
"""loop/check_exit.py — evaluate.py が出した report.json を機械的に判定する。

これが「検証者」の実体。LLMの判断は挟まず、report.json の数値を閾値と比較するだけ。
mean_reference_error < THRESHOLD なら PASS (exit 0)、それ以外は FAIL (exit 1)。
report.json が壊れている/読めない場合は ERROR (exit 2)。

使い方:
  python loop/check_exit.py <report.json> <threshold>
"""
import json
import sys


def main() -> int:
    if len(sys.argv) != 3:
        print("usage: check_exit.py <report.json> <threshold>", file=sys.stderr)
        return 2

    report_path, threshold_str = sys.argv[1], sys.argv[2]
    try:
        threshold = float(threshold_str)
    except ValueError:
        print(f"ERROR: threshold が数値ではありません: {threshold_str}", file=sys.stderr)
        return 2

    try:
        with open(report_path, encoding="utf-8") as f:
            report = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        print(f"ERROR: {report_path} を読めません: {e}", file=sys.stderr)
        return 2

    summary = report.get("summary", {})
    mean_err = summary.get("mean_reference_error")
    within = summary.get("within_tolerance")
    total = summary.get("total")

    if mean_err is None:
        print(f"ERROR: summary.mean_reference_error が report.json にありません", file=sys.stderr)
        return 2

    passed = mean_err < threshold
    verdict = "PASS" if passed else "FAIL"
    print(f"{verdict} mean_reference_error={mean_err:.4f} threshold={threshold:.4f} "
          f"within_tolerance={within}/{total}")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
