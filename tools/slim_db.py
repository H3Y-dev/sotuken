"""Remove a final processed_img field without loading the original JSON into Python."""

import argparse
import json
import re
import sqlite3
from contextlib import closing
from pathlib import Path


_MARKER = ', "processed_img":'
_STRUCTURAL = re.compile(rb'[\[\]{}"\\]')


def _is_final_value(conn, row_id, byte_offset):
    """Scan the suffix in bounded chunks; a top-level comma means another key follows.

    blobopen also reads TEXT columns, so the 200 MB image stays out of Python's
    heap. Only nesting and quoted strings matter here; the retained JSON is
    separately validated with json.loads before any update.
    """
    stack = []
    quoted = False
    escaped_position = -1
    finished = False
    with conn.blobopen("meter_readings", "raw_data_json", row_id, readonly=True) as blob:
        blob.seek(byte_offset)
        while chunk := blob.read(65536):
            previous = 0
            for token in _STRUCTURAL.finditer(chunk):
                segment = chunk[previous:token.start()]
                if finished and segment.strip():
                    return False
                if not quoted and not stack and b"," in segment:
                    return False
                position = byte_offset + token.start()
                char = token.group()
                previous = token.end()
                if quoted:
                    if position == escaped_position:
                        continue
                    if char == b"\\":
                        escaped_position = position + 1
                    elif char == b'"':
                        quoted = False
                    continue
                if finished:
                    return False
                if char == b'"':
                    quoted = True
                elif char in (b"[", b"{"):
                    stack.append(char)
                elif char in (b"]", b"}"):
                    if stack:
                        if stack.pop() != (b"[" if char == b"]" else b"{"):
                            return False
                    elif char == b"}":
                        finished = True
                    else:
                        return False
                else:
                    return False
            remainder = chunk[previous:]
            if finished and remainder.strip():
                return False
            if not quoted and not stack and b"," in remainder:
                return False
            byte_offset += len(chunk)
    return finished and not quoted and not stack


def slim_db(db_path, dry_run=False):
    path = Path(db_path).resolve()
    mode = "ro" if dry_run else "rw"  # Never create a DB for a mistyped path.
    with closing(sqlite3.connect(path.as_uri() + f"?mode={mode}", uri=True)) as conn:
        conn.execute("BEGIN" if dry_run else "BEGIN IMMEDIATE")
        rows = conn.execute(
            "SELECT id, length(CAST(raw_data_json AS BLOB)), instr(raw_data_json, ?) "
            "FROM meter_readings ORDER BY id", (_MARKER,),
        ).fetchall()
        changed = 0
        for row_id, original_size, marker_pos in rows:
            prefix = f"id={row_id} bytes={original_size or 0}"
            if not marker_pos:
                print(f"{prefix} skipped: marker not found")
                continue
            candidate, byte_offset = conn.execute(
                "SELECT substr(raw_data_json, 1, ? - 1) || '}', "
                "length(CAST(substr(raw_data_json, 1, ? + ? - 1) AS BLOB)) "
                "FROM meter_readings WHERE id = ?",
                (marker_pos, marker_pos, len(_MARKER), row_id),
            ).fetchone()
            try:
                retained = json.loads(candidate)
            except (ValueError, TypeError):
                print(f"{prefix} skipped: truncated JSON is invalid")
                continue
            if not isinstance(retained, dict) or "processed_img" in retained:
                print(f"{prefix} skipped: ambiguous processed_img field")
                continue
            if not _is_final_value(conn, row_id, byte_offset):
                print(f"{prefix} skipped: processed_img is not the final key")
                continue
            new_size = len(candidate.encode("utf-8"))
            print(f"{prefix} -> {new_size} ({'dry-run' if dry_run else 'updated'})")
            if not dry_run:
                conn.execute(
                    "UPDATE meter_readings SET raw_data_json = "
                    "substr(raw_data_json, 1, ? - 1) || '}' WHERE id = ?",
                    (marker_pos, row_id),
                )
            changed += 1
        conn.commit()
        if not dry_run:
            conn.execute("VACUUM")
            print("VACUUM complete")
        print(f"{'Eligible' if dry_run else 'Updated'}: {changed}; skipped: {len(rows) - changed}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("db_path", help="Existing SQLite database path")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    slim_db(args.db_path, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
