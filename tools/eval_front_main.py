"""正面メインデータセット（3D正面QR付き＋企業提供JSW）の検証・評価ツール。

用途:
- 3D正面（degradationsなし）と企業提供JSWのエントリーを抽出し、
  QRデコード結果および eval/devices.csv との対応を検証する（--check-qr-only）。
- 結合データセットを --out-dataset で書き出すか、一時ファイル経由で
  evaluate.evaluate_entry を実行してグループ別サマリーを出力する（--evaluate）。
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
import statistics
import sys
import tempfile
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from manager.qr_decode import read_device_qr

DEFAULT_SYNTHETIC_GT = Path(r"C:\卒研\合成画像\テスト用QR付き_20261030\正解_QR付き.json")
DEFAULT_REAL_GT = REPO_ROOT / "eval" / "groundtruth.json"
DEFAULT_DEVICES_CSV = REPO_ROOT / "eval" / "devices.csv"


def load_devices_csv(csv_path: Path) -> dict[str, dict[str, str]]:
    """devices.csv を読み込み、device_id -> row の辞書を返す。"""
    devices: dict[str, dict[str, str]] = {}
    with csv_path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            dev_id = (row.get("device_id") or "").strip()
            if dev_id:
                devices[dev_id] = row
    return devices


def load_json_entries(json_path: Path) -> list[dict[str, Any]]:
    """正解JSON（list または {'entries': [...]}）を読み込む。"""
    with json_path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        return list(data.get("entries") or data.get("images") or [])
    return []


def filter_synthetic_front(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """3D合成画像から正面かつ劣化なし（degradationsなし）のエントリーを抽出する。"""
    result: list[dict[str, Any]] = []
    for entry in entries:
        cond = entry.get("condition") or {}
        if cond.get("category") != "正面":
            continue
        if entry.get("degradations") or cond.get("degradations"):
            continue
        tagged = dict(entry)
        tagged.setdefault("dataset_group", "3d_front")
        result.append(tagged)
    return result


def filter_jsw_entries(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """実写データセットから企業提供（日本製鋼所 / JSW）のエントリーを抽出する。"""
    result: list[dict[str, Any]] = []
    for entry in entries:
        dev_id = str(entry.get("device_id") or "")
        image = str(entry.get("image") or "")
        note = str(entry.get("note") or "")
        if "企業提供_日本製鋼所" in image or "企業提供_日本製鋼所" in note or dev_id.startswith("JSW"):
            tagged = dict(entry)
            tagged.setdefault("dataset_group", "jsw")
            result.append(tagged)
    return result


def verify_dataset(
    syn_entries: list[dict[str, Any]],
    jsw_entries: list[dict[str, Any]],
    devices: dict[str, dict[str, str]],
    *,
    check_qr: bool = True,
) -> dict[str, Any]:
    """QRデコード結果と devices.csv の整合性を検証する。"""
    syn_qr_ok = 0
    syn_id_match = 0
    syn_name_match = 0
    syn_errors: list[str] = []

    for entry in syn_entries:
        img_path = str(entry.get("image") or "")
        gt_id = str(entry.get("device_id") or "")
        dev_row = devices.get(gt_id)
        if not dev_row:
            syn_errors.append(f"devices.csv に未登録: {gt_id} ({img_path})")
            continue

        if not check_qr:
            syn_id_match += 1
            syn_name_match += 1
            continue

        qr = read_device_qr(img_path)
        if qr.status == "found":
            syn_qr_ok += 1
        else:
            syn_errors.append(f"QR読取失敗 ({qr.status}): {img_path}")
            continue

        if qr.device_id == gt_id:
            syn_id_match += 1
        else:
            syn_errors.append(f"device_id不一致: qr={qr.device_id} gt={gt_id} ({img_path})")

        csv_name = (dev_row.get("device_name") or "").strip()
        if qr.device_name == csv_name or (not qr.device_name and csv_name):
            # QRペイロードがIDのみの場合は devices.csv 側の名前と照合できればOK
            syn_name_match += 1
        elif qr.device_name != csv_name:
            syn_errors.append(
                f"device_name不一致: qr={qr.device_name!r} csv={csv_name!r} ({img_path})"
            )

    jsw_csv_ok = 0
    jsw_errors: list[str] = []
    for entry in jsw_entries:
        gt_id = str(entry.get("device_id") or "")
        if gt_id in devices:
            jsw_csv_ok += 1
        else:
            jsw_errors.append(f"JSW device_id が devices.csv に未登録: {gt_id}")

    return {
        "synthetic": {
            "total": len(syn_entries),
            "qr_ok": syn_qr_ok,
            "id_match": syn_id_match,
            "name_match": syn_name_match,
            "errors": syn_errors,
        },
        "jsw": {
            "total": len(jsw_entries),
            "csv_ok": jsw_csv_ok,
            "errors": jsw_errors,
        },
        "ok": len(syn_errors) == 0 and len(jsw_errors) == 0,
    }


def compute_group_metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """evaluate_entry の結果行リストからグループ別メトリクスを集計する。"""
    total = len(rows)
    read_ok_rows = [r for r in rows if r.get("value") is not None]
    fs_errors: list[float] = []
    within_2_5 = 0
    within_5_0 = 0
    for r in read_ok_rows:
        err = r.get("reference_error")
        if err is None:
            err = r.get("relative_error")
        if err is None:
            continue
        pct = abs(float(err)) * 100.0
        fs_errors.append(pct)
        if pct <= 2.5:
            within_2_5 += 1
        if pct <= 5.0:
            within_5_0 += 1

    return {
        "total": total,
        "read_ok": len(read_ok_rows),
        "within_2_5_fs": within_2_5,
        "within_5_0_fs": within_5_0,
        "mean_fs": round(statistics.mean(fs_errors), 3) if fs_errors else None,
        "median_fs": round(statistics.median(fs_errors), 3) if fs_errors else None,
        "max_fs": round(max(fs_errors), 3) if fs_errors else None,
    }


def print_verification_summary(verif: dict[str, Any]) -> None:
    syn = verif["synthetic"]
    jsw = verif["jsw"]
    print("=== QR & devices.csv 検証サマリー ===")
    print(
        f"[3D正面] total={syn['total']}, qr_ok={syn['qr_ok']}/{syn['total']}, "
        f"device_id_match={syn['id_match']}/{syn['total']}, "
        f"device_name_match={syn['name_match']}/{syn['total']}"
    )
    print(f"[JSW]    total={jsw['total']}, devices_csv_ok={jsw['csv_ok']}/{jsw['total']}")
    for err in syn["errors"][:10]:
        print(f"  ERROR(3D正面): {err}")
    for err in jsw["errors"][:10]:
        print(f"  ERROR(JSW):    {err}")


def print_eval_summary(label: str, metrics: dict[str, Any]) -> None:
    print(
        f"[{label}] total={metrics['total']}, read_ok={metrics['read_ok']}/{metrics['total']}, "
        f"±2.5%FS={metrics['within_2_5_fs']}, ±5.0%FS={metrics['within_5_0_fs']}, "
        f"mean={metrics['mean_fs']}%FS, median={metrics['median_fs']}%FS, max={metrics['max_fs']}%FS"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="正面メインデータセット（3D正面QR付き＋JSW）検証・評価ツール")
    parser.add_argument("--synthetic-gt", type=Path, default=DEFAULT_SYNTHETIC_GT)
    parser.add_argument("--real-gt", type=Path, default=DEFAULT_REAL_GT)
    parser.add_argument("--devices-csv", type=Path, default=DEFAULT_DEVICES_CSV)
    parser.add_argument("--out-dataset", type=Path, default=None)
    parser.add_argument("--check-qr-only", action="store_true")
    parser.add_argument("--evaluate", action="store_true")
    parser.add_argument("--no-vlm", action="store_true", default=True)
    parser.add_argument("--local-read", dest="local_read", action="store_true", default=False)
    parser.add_argument("--no-local-read", dest="local_read", action="store_false")
    parser.add_argument("--report", type=Path, default=None)
    args = parser.parse_args(argv)

    devices = load_devices_csv(args.devices_csv)
    syn_entries = filter_synthetic_front(load_json_entries(args.synthetic_gt))
    jsw_entries = filter_jsw_entries(load_json_entries(args.real_gt))
    combined = syn_entries + jsw_entries

    if args.out_dataset is not None:
        args.out_dataset.parent.mkdir(parents=True, exist_ok=True)
        args.out_dataset.write_text(
            json.dumps(combined, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    verif = verify_dataset(syn_entries, jsw_entries, devices, check_qr=True)
    print_verification_summary(verif)

    if args.check_qr_only or not args.evaluate:
        return 0 if verif["ok"] else 1

    import evaluate as eval_mod

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_gt = Path(tmpdir) / "front_main_gt.json"
        tmp_gt.write_text(json.dumps(combined, ensure_ascii=False, indent=2), encoding="utf-8")

        syn_rows: list[dict[str, Any]] = []
        jsw_rows: list[dict[str, Any]] = []
        for entry in combined:
            row = eval_mod.evaluate_entry(
                entry,
                str(REPO_ROOT),
                use_vlm=not args.no_vlm,
                local_read=args.local_read,
            )
            row["dataset_group"] = entry.get("dataset_group")
            if entry.get("dataset_group") == "3d_front":
                syn_rows.append(row)
            else:
                jsw_rows.append(row)

    syn_metrics = compute_group_metrics(syn_rows)
    jsw_metrics = compute_group_metrics(jsw_rows)
    print("=== 評価サマリー ===")
    print_eval_summary("3D正面", syn_metrics)
    print_eval_summary("JSW   ", jsw_metrics)

    if args.report is not None:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        report_data = {
            "verification": verif,
            "metrics": {"3d_front": syn_metrics, "jsw": jsw_metrics},
            "rows": syn_rows + jsw_rows,
        }
        args.report.write_text(
            json.dumps(report_data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    return 0 if verif["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
