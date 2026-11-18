"""デモ用機器カタログの読み込み・一意性検査・履歴検査モジュール。

仕様: tasks/design/デモ用3Dメーターと機器カタログ.md
"""

from __future__ import annotations

import argparse
import csv
import math
from pathlib import Path
import re
import sys

from manager.qr_label import build_payload

DEFAULT_CATALOG_PATH = Path(__file__).resolve().parent.parent / "eval" / "demo_devices.csv"

EXPECTED_COLUMNS = [
    "device_id",
    "device_name",
    "kind",
    "unit",
    "min_value",
    "max_value",
    "meter_key",
    "sweep_deg",
    "dial_color",
    "number_position",
    "font",
    "needle_shape",
    "needle_color",
    "bezel_color",
    "danger_band",
    "max_pointer",
    "acceptable_min",
    "acceptable_max",
]

APPEARANCE_KEYS = (
    "meter_key",
    "sweep_deg",
    "dial_color",
    "number_position",
    "font",
    "needle_shape",
    "needle_color",
    "bezel_color",
    "danger_band",
    "max_pointer",
    "unit",
    "min_value",
    "max_value",
)

METER_SCALES: dict[str, tuple[str, float, float]] = {
    "pressure-150": ("MPa", 0.0, 150.0),
    "pressure-400": ("MPa", 0.0, 400.0),
    "pressure-1.0": ("MPa", 0.0, 1.0),
    "pressure-1.6": ("MPa", 0.0, 1.6),
    "pressure-250": ("kPa", 0.0, 250.0),
    "pressure-16": ("bar", 0.0, 16.0),
    "pressure--0.1:0.5": ("MPa", -0.1, 0.5),
    "temperature-100": ("℃", 0.0, 100.0),
    "temperature-60": ("℃", 0.0, 60.0),
    "temperature--20:120": ("℃", -20.0, 120.0),
}

VALID_KINDS = ("pressure", "temperature")
VALID_SWEEP_DEG = (270, 240, 300)
VALID_DIAL_COLOR = ("white", "black", "cream")
VALID_NUMBER_POSITION = ("inside", "outside")
VALID_FONT = ("sans", "serif", "mono")
VALID_NEEDLE_SHAPE = ("lance", "arrow", "counterweight")
VALID_NEEDLE_COLOR = ("black", "red")
VALID_BEZEL_COLOR = ("black", "silver", "brass")

DEVICE_ID_RE = re.compile(r"^DMO-(\d{3})$")
INT_RE = re.compile(r"^-?\d+$")


def _parse_device_num(device_id: str) -> int:
    m = DEVICE_ID_RE.fullmatch(device_id)
    if not m:
        raise ValueError(f"device_id の形式が不正です: {device_id!r}")
    num = int(m.group(1))
    if num < 1 or num > 999:
        raise ValueError(f"device_id の番号が範囲外です (001..999): {device_id!r}")
    return num


def _parse_finite_float(raw: str, col: str, line_no: int) -> float:
    try:
        val = float(raw)
    except ValueError as exc:
        raise ValueError(f"{line_no}行目: {col} が数値ではありません ({raw!r})") from exc
    if not math.isfinite(val):
        raise ValueError(f"{line_no}行目: {col} が有限数ではありません ({raw!r})")
    return val


def _parse_bool(raw: str, col: str, line_no: int) -> bool:
    if raw == "true":
        return True
    if raw == "false":
        return False
    raise ValueError(f"{line_no}行目: {col} が真偽値 (true/false) ではありません ({raw!r})")


def appearance_key(device: dict) -> tuple:
    """1台の機器から外観と目盛りの一意性判定用タプルを返す。"""
    return tuple(device[k] for k in APPEARANCE_KEYS)


def load_catalog(path: Path) -> list[dict]:
    """デモ用機器カタログCSVを読み込み、全行の形式・一意性・QRペイロードを検証して返す。"""
    path = Path(path)
    with path.open("r", encoding="utf-8", newline="") as f:
        text = f.read()
    if text.startswith("\ufeff"):
        raise ValueError("1行目: UTF-8 BOM は許可されていません")

    rows = list(csv.reader(text.splitlines()))
    if not rows:
        raise ValueError("1行目: ヘッダーがありません")
    if rows[0] != EXPECTED_COLUMNS:
        raise ValueError(f"1行目: ヘッダー列順が不正です ({rows[0]!r})")

    devices: list[dict] = []
    seen_ids: set[str] = set()
    seen_names: set[str] = set()
    seen_appearances: dict[tuple, str] = {}
    prev_num = 0

    for line_no, raw_row in enumerate(rows[1:], start=2):
        if len(raw_row) != len(EXPECTED_COLUMNS):
            raise ValueError(
                f"{line_no}行目: 列数が不正です (期待 {len(EXPECTED_COLUMNS)}, 実際 {len(raw_row)})"
            )
        raw = dict(zip(EXPECTED_COLUMNS, raw_row))

        device_id = raw["device_id"]
        try:
            num = _parse_device_num(device_id)
        except ValueError as exc:
            raise ValueError(f"{line_no}行目: {exc}") from exc

        if device_id in seen_ids:
            raise ValueError(f"{line_no}行目: device_id が重複しています ({device_id})")
        if num <= prev_num:
            raise ValueError(f"{line_no}行目: device_id が昇順ではありません ({device_id})")
        seen_ids.add(device_id)
        prev_num = num

        device_name = raw["device_name"]
        if not device_name or device_name != device_name.strip():
            raise ValueError(f"{line_no}行目: device_name が空または前後空白を含みます ({device_name!r})")
        if device_name in seen_names:
            raise ValueError(f"{line_no}行目: device_name が重複しています ({device_name!r})")
        seen_names.add(device_name)

        kind = raw["kind"]
        if kind not in VALID_KINDS:
            raise ValueError(f"{line_no}行目: kind が不正です ({kind!r})")

        meter_key = raw["meter_key"]
        if meter_key not in METER_SCALES:
            raise ValueError(f"{line_no}行目: 未定義の meter_key です ({meter_key!r})")
        if not meter_key.startswith(f"{kind}-"):
            raise ValueError(f"{line_no}行目: kind ({kind}) と meter_key ({meter_key}) が不整合です")

        unit = raw["unit"]
        min_value = _parse_finite_float(raw["min_value"], "min_value", line_no)
        max_value = _parse_finite_float(raw["max_value"], "max_value", line_no)
        expected_unit, expected_min, expected_max = METER_SCALES[meter_key]
        if (unit, min_value, max_value) != (expected_unit, expected_min, expected_max):
            raise ValueError(
                f"{line_no}行目: {meter_key} の単位/範囲が定義と一致しません "
                f"(期待 {(expected_unit, expected_min, expected_max)}, 実際 {(unit, min_value, max_value)})"
            )

        if not INT_RE.fullmatch(raw["sweep_deg"]):
            raise ValueError(f"{line_no}行目: sweep_deg が整数ではありません ({raw['sweep_deg']!r})")
        sweep_deg = int(raw["sweep_deg"])
        if sweep_deg not in VALID_SWEEP_DEG:
            raise ValueError(f"{line_no}行目: sweep_deg が許可値外です ({sweep_deg})")

        enum_checks = (
            ("dial_color", VALID_DIAL_COLOR),
            ("number_position", VALID_NUMBER_POSITION),
            ("font", VALID_FONT),
            ("needle_shape", VALID_NEEDLE_SHAPE),
            ("needle_color", VALID_NEEDLE_COLOR),
            ("bezel_color", VALID_BEZEL_COLOR),
        )
        for col, allowed in enum_checks:
            if raw[col] not in allowed:
                raise ValueError(f"{line_no}行目: {col} が許可値外です ({raw[col]!r})")

        danger_band = _parse_bool(raw["danger_band"], "danger_band", line_no)
        max_pointer = _parse_bool(raw["max_pointer"], "max_pointer", line_no)
        if danger_band is not False:
            raise ValueError(f"{line_no}行目: danger_band は false のみ許可されます")
        if max_pointer is not False:
            raise ValueError(f"{line_no}行目: max_pointer は false のみ許可されます")

        raw_acc_min = raw["acceptable_min"]
        raw_acc_max = raw["acceptable_max"]
        if (raw_acc_min == "") != (raw_acc_max == ""):
            raise ValueError(f"{line_no}行目: acceptable_min と acceptable_max は片側だけ指定できません")
        if raw_acc_min == "":
            acceptable_min = None
            acceptable_max = None
        else:
            acceptable_min = _parse_finite_float(raw_acc_min, "acceptable_min", line_no)
            acceptable_max = _parse_finite_float(raw_acc_max, "acceptable_max", line_no)
            if not (min_value <= acceptable_min < acceptable_max <= max_value):
                raise ValueError(
                    f"{line_no}行目: 許容範囲が不正です "
                    f"({acceptable_min}..{acceptable_max}, 目盛り {min_value}..{max_value})"
                )

        try:
            build_payload(device_id, device_name, unit, min_value, max_value)
        except ValueError as exc:
            raise ValueError(f"{line_no}行目: QRペイロード検査に失敗しました: {exc}") from exc

        device = {
            "device_id": device_id,
            "device_name": device_name,
            "kind": kind,
            "unit": unit,
            "min_value": min_value,
            "max_value": max_value,
            "meter_key": meter_key,
            "sweep_deg": sweep_deg,
            "dial_color": raw["dial_color"],
            "number_position": raw["number_position"],
            "font": raw["font"],
            "needle_shape": raw["needle_shape"],
            "needle_color": raw["needle_color"],
            "bezel_color": raw["bezel_color"],
            "danger_band": danger_band,
            "max_pointer": max_pointer,
            "acceptable_min": acceptable_min,
            "acceptable_max": acceptable_max,
        }

        key = appearance_key(device)
        if key in seen_appearances:
            other_id = seen_appearances[key]
            raise ValueError(f"{line_no}行目: 外観の組が重複しています ({other_id} と {device_id})")
        seen_appearances[key] = device_id

        devices.append(device)

    return devices


def check_catalog_history(previous: list[dict], current: list[dict]) -> None:
    """旧カタログに対する追加専用ルール（削除・改名・外観変更・旧最大番号以下への追加禁止）を検査する。"""
    prev_by_id = {d["device_id"]: d for d in previous}
    curr_by_id = {d["device_id"]: d for d in current}

    for prev_id, prev_dev in prev_by_id.items():
        if prev_id not in curr_by_id:
            raise ValueError(f"旧IDが削除されています: {prev_id}")
        curr_dev = curr_by_id[prev_id]
        if curr_dev["device_name"] != prev_dev["device_name"]:
            raise ValueError(f"旧ID {prev_id} の機器名が変更されています")
        if appearance_key(curr_dev) != appearance_key(prev_dev):
            raise ValueError(f"旧ID {prev_id} の外観が変更されています")

    if previous:
        max_prev_num = max(_parse_device_num(d["device_id"]) for d in previous)
        for curr_dev in current:
            cid = curr_dev["device_id"]
            if cid not in prev_by_id and _parse_device_num(cid) <= max_prev_num:
                raise ValueError(
                    f"旧最大番号 DMO-{max_prev_num:03d} 以下への新規ID追加は禁止です: {cid}"
                )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="デモ用機器カタログの検証")
    parser.add_argument("catalog", nargs="?", type=Path, default=DEFAULT_CATALOG_PATH)
    parser.add_argument("--previous", type=Path, default=None, help="比較対象の旧カタログCSV")
    args = parser.parse_args(argv)

    try:
        current = load_catalog(args.catalog)
        if args.previous is not None:
            previous = load_catalog(args.previous)
            check_catalog_history(previous, current)
    except (OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print(f"OK: {len(current)} devices")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
