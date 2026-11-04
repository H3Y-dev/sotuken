"""Evaluate saved synthetic readings by device; never opens the DB for writing."""
import argparse
from collections import Counter, defaultdict
import csv
import json
from pathlib import Path
import shutil
import sqlite3
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from evaluate import is_within_tolerance, reference_error, summarize
from manager.batch import calculate_file_hash


def exclusion_reasons(entry):
    condition = entry["condition"]
    reasons = []
    if condition["blur"] != "none":
        reasons.append("blur")
    if condition["lighting"] != "normal":
        reasons.append("lighting")
    for key in ("camera_yaw", "camera_pitch"):
        if abs(condition[key]) > 30:
            reasons.append(key)
    for name, degradation in entry["degradations"].items():
        if degradation["strength"] > 0.5:
            reasons.append(f"degradation:{name}")
    if entry.get("appearance", {}).get("max_pointer", False):
        reasons.append("max_pointer")
    return reasons


def select_field_set(entries):
    """Return selected entries and excluded entries with every matching reason."""
    selected, excluded = [], []
    for item in entries:
        reasons = exclusion_reasons(item)
        if reasons:
            excluded.append({"entry": item, "reasons": reasons})
        else:
            selected.append(item)
    return selected, excluded


def copy_field_set(entries, destination):
    """Copy original images with their category directories and a full audit CSV."""
    selected, excluded = select_field_set(entries)
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    for item in selected:
        source = Path(item["image"])
        target = destination / source.parent.name / source.name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    with (destination / "_選別結果.csv").open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(["画像名", "残した理由", "除外した理由"])
        for item in entries:
            reasons = exclusion_reasons(item)
            writer.writerow([Path(item["image"]).name,
                             "条件内（ブレなし・通常照明・角度30度以内・劣化強さ0.5以下・置き針なし）" if not reasons else "",
                             ";".join(reasons)])
    return len(selected), len(excluded)


def read_database(path):
    with sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True) as connection:
        connection.row_factory = sqlite3.Row
        return [dict(row) for row in connection.execute("SELECT * FROM meter_readings")]


def build_rows(entries, readings, images_source=None):
    """Join QR-image hashes via the original basename; keep missing rows in totals."""
    by_hash, by_name = defaultdict(list), defaultdict(list)
    for reading in readings:
        by_hash[reading.get("image_sha256")].append(reading)
        by_name[Path(reading["image_path"]).name].append(reading)
    if len({Path(item["image"]).name for item in entries}) != len(entries):
        raise ValueError("Groundtruth image basenames must be unique")
    rows = []
    for item in entries:
        name = Path(item["image"]).name
        image_hash = item.get("image_sha256")
        if images_source is not None:
            image_hash = calculate_file_hash(str(Path(images_source) / name))
        matches = by_hash.get(image_hash, []) if image_hash else []
        if not matches:
            matches = by_name.get(name, [])
        if len(matches) > 1:
            raise ValueError(f"Multiple readings match {name}; use a single-run evaluation DB")
        reading = matches[0] if matches else {}
        raw = json.loads(reading.get("raw_data_json") or "{}")
        stage = raw.get("stage", reading.get("stage", "missing"))
        value = reading.get("value")
        scale_min, scale_max = raw.get("min_value"), raw.get("max_value")
        scale_correct = None
        if scale_min is not None and scale_max is not None:
            scale_correct = (abs(scale_min - item["min_value"]) < 1e-6
                             and abs(scale_max - item["max_value"]) < 1e-6)
        row = dict(image=name, device_id=item["device_id"], category=item["category"],
                   stage=stage, value=value, reference_error=None, within_tolerance=False,
                   scale_correct=scale_correct, imported=bool(reading),
                   observed_device_id=reading.get("device_id"),
                   id_correct=reading.get("device_id") == item["device_id"],
                   id_source=reading.get("device_id_source"),
                   id_issue=reading.get("device_id_issue"))
        if stage == "ok" and value is not None:
            arguments = value, item["true_value"], item["min_value"], item["max_value"]
            row["reference_error"] = reference_error(*arguments)
            row["within_tolerance"] = is_within_tolerance(*arguments)
        rows.append(row)
    return rows


def aggregate(rows, devices):
    groups = defaultdict(list)
    for row in rows:
        groups[row["device_id"]].append(row)
    output = []
    for device_id, items in groups.items():
        summary = summarize(items)
        summary.update(device_id=device_id,
                       device_name=devices.get(device_id, {}).get("device_name", device_id),
                       within_percent=summary["within_tolerance"] / summary["total"] * 100,
                       imported=sum(item["imported"] for item in items),
                       scale_wrong=sum(item["scale_correct"] is False for item in items),
                       scale_unavailable=sum(item["scale_correct"] is None for item in items))
        output.append(summary)
    return sorted(output, key=lambda row: (row["within_percent"],
                                           -(row["mean_reference_error"] or 0), row["device_id"]))


COLUMNS = {
    "device_id": "機器ID", "device_name": "種類・文字盤色", "total": "件数",
    "imported": "取込数", "read_ok": "値算出数", "within_tolerance": "許容内数",
    "within_percent": "許容内率(%)", "mean_reference_error": "平均(%FS)",
    "median_reference_error": "中央値(%FS)", "max_reference_error": "最大(%FS)",
    "scale_wrong": "範囲誤り数", "scale_unavailable": "範囲不明数",
}


def display(value):
    if value is None:
        return "-"
    return f"{value:.2f}" if isinstance(value, float) else str(value)


def markdown_table(rows, columns):
    lines = ["| " + " | ".join(columns.values()) + " |",
             "| " + " | ".join("---" for _ in columns) + " |"]
    lines.extend("| " + " | ".join(display(row[key]).replace("|", "\\|") for key in columns)
                 + " |" for row in rows)
    return "\n".join(lines)


def write_report(path, rows, devices, excluded):
    table = aggregate(rows, devices)
    summary = summarize(rows)
    lines = [f"# {path.stem}", "", f"対象 {len(rows)}枚、取込 {sum(row['imported'] for row in rows)}枚。"
             f"許容内 {summary['within_tolerance']}枚（{summary['within_tolerance']/len(rows)*100:.2f}%）。",
             "", "許容内率の母数は対象画像すべて（未取込・値算出失敗も含む）。"
             "引用誤差の平均・中央値・最大はstage=okで値を算出できた画像のみ。"
             "low_confidenceでもstage=okなら既存evaluate.pyと同じく採点する。",
             "", "許容内は±2.5%FS。範囲誤りは推定上下限が正解と異なる画像、"
             "範囲不明は片方でも推定できなかった画像。種類と文字盤色は正解の機器IDで分類する。",
             "", "並び順は許容内率の低い順、同率は平均引用誤差の大きい順。", "",
             markdown_table(table, COLUMNS), "", "## 値算出失敗の内訳", "",
             markdown_table([dict(stage=key, count=count)
                             for key, count in sorted(summary["failure_stages"].items())],
                            {"stage": "工程", "count": "件数"})]
    if excluded is not None:
        lines += ["", f"## 選別で除外した画像（{len(excluded)}枚）", "",
                  "条件別は画像のcategoryで集計。理由別は重複計上がある。", ""]
        for label, counts in [
            ("条件", Counter(item["entry"]["category"] for item in excluded)),
            ("理由", Counter(reason for item in excluded for reason in item["reasons"]))
        ]:
            lines += [markdown_table([dict(reason=key, count=count) for key, count in sorted(counts.items())],
                                     {"reason": label, "count": "除外数"}), ""]
    path.with_suffix(".md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    with path.with_suffix(".csv").open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(COLUMNS.values())
        writer.writerows([display(row[key]) for key in COLUMNS] for row in table)
    return table


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", required=True)
    parser.add_argument("--qr-db")
    parser.add_argument("--groundtruth", required=True)
    parser.add_argument("--images-source", required=True, help="Imported QR image directory (original filenames)")
    parser.add_argument("--devices", default=str(Path(__file__).with_name("devices.csv")))
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--field-images", help="Also copy selected original images here")
    args = parser.parse_args()
    entries = json.loads(Path(args.groundtruth).read_text(encoding="utf-8"))
    selected, excluded = select_field_set(entries)
    if args.field_images:
        print("field images:", copy_field_set(entries, args.field_images))
    with Path(args.devices).open(encoding="utf-8-sig", newline="") as stream:
        devices = {row["device_id"]: row for row in csv.DictReader(stream)}
    output = Path(args.output_dir)
    output.mkdir(parents=True, exist_ok=True)
    rows = build_rows(entries, read_database(args.db), args.images_source)
    selected_names = {Path(item["image"]).name for item in selected}
    for label, subset, exclusions in [
        ("全部入り", rows, None),
        ("現場想定", [row for row in rows if row["image"] in selected_names], excluded)
    ]:
        table = write_report(output / f"機器別精度_{label}", subset, devices, exclusions)
        print(label, len(subset), "worst:", [(row["device_id"], row["within_percent"]) for row in table[:5]])
    if args.qr_db:
        qr_rows = build_rows(entries, read_database(args.qr_db), args.images_source)
        groups = [("全体", qr_rows)] + [(category, [row for row in qr_rows if row["category"] == category])
                                       for category in sorted({row["category"] for row in qr_rows})]
        qr_table = []
        for category, items in groups:
            correct = sum(row["id_correct"] and row["id_source"] == "pc_qr" for row in items)
            qr_table.append(dict(category=category, total=len(items), correct=correct,
                                 percent=correct/len(items)*100,
                                 wrong=sum(bool(row["observed_device_id"]) and not row["id_correct"] for row in items)))
        report = "# QRのみの機器ID取得率\n\n正解IDとの一致かつdevice_id_source=pc_qrを成功とする。\n\n"
        report += markdown_table(qr_table, dict(category="条件", total="枚数", correct="正解ID取得数",
                                                percent="取得率(%)", wrong="ID不一致数"))
        report += "\n\n未取得の内訳: " + json.dumps(dict(Counter(row["id_issue"] or "missing" for row in qr_rows
                                                                if not row["observed_device_id"])), ensure_ascii=False) + "\n"
        (output / "QRのみ_機器ID取得率.md").write_text(report, encoding="utf-8")
        print(report)


if __name__ == "__main__":
    main()
