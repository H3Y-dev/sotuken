"""Preview an explicit CSV device import; write only with --apply.

CSV columns: device_id, device_name, kind, unit, min_value, max_value,
provisional, note (UTF-8, optional BOM). Existing values are never overwritten.
"""

import argparse
import csv
import json
from pathlib import Path
import sqlite3
import sys

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from manager.devices import import_devices_csv, list_devices
from manager.storage import Storage


def sync_devices(csv_path, db_path="manager.db", *, apply=False):
    """Return a preview and optionally import, rejecting the whole CSV on errors."""
    with open(csv_path, encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        if not {"device_id", "device_name"}.issubset(reader.fieldnames or []):
            raise ValueError("CSV requires device_id and device_name columns")
        csv_ids = {row["device_id"] for row in reader if row.get("device_id")}

    preview = Storage(":memory:")
    try:
        path = Path(db_path).resolve()
        if path.exists():
            # Read-only backup avoids Storage's on-disk schema initialization in dry-run.
            source = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)
            try:
                source.backup(preview._conn)
            finally:
                source.close()
        before = {row["device_id"]: row for row in list_devices(preview)}
        result = import_devices_csv(preview, csv_path)
        after = {row["device_id"]: row for row in list_devices(preview)}
        result["new"] = sorted(after.keys() - before.keys())
        result["csv_only"] = sorted(csv_ids - before.keys())
        result["db_only"] = sorted(before.keys() - csv_ids)
        result["changed"] = {}
        result["unchanged"] = []
        for device_id in sorted(csv_ids & before.keys()):
            changes = {
                key: {"old": value, "new": after[device_id][key]}
                for key, value in before[device_id].items()
                if key != "updated_at" and value != after[device_id][key]
            }
            if changes:
                result["changed"][device_id] = changes
            else:
                result["unchanged"].append(device_id)
        result["applied"] = False
        if apply and not result["errors"]:
            actual = import_devices_csv(Storage(str(path)), csv_path)
            result["errors"] = actual["errors"]
            result["applied"] = not actual["errors"]
        return result
    finally:
        preview._conn.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("csv_path", type=Path)
    parser.add_argument("--db", default="manager.db", type=Path)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="Preview only (default)")
    mode.add_argument("--apply", action="store_true", help="Fill empty fields and register new devices")
    args = parser.parse_args(argv)
    try:
        result = sync_devices(args.csv_path, args.db, apply=args.apply)
    except (OSError, ValueError, sqlite3.Error) as exc:
        parser.exit(1, f"{exc}\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 1 if result["errors"] else 0


if __name__ == "__main__":
    sys.exit(main())
