"""テスト画像および実写画像に機器ID（device_id）・表示名（device_name）を割り当て、
機器一覧CSV（eval/devices.csv）および各正解JSONを更新するCLIツール。

仕様（tasks/design/機器ID設計.md およびコーディネータ指示）:
1. 合成画像:
   - meter_id（10種類固定順）× dial_color（'white', 'cream', 'black'）= 30台。
   - 採番: SYN-001 〜 SYN-030。
   - 表示名: 「合成 <種類・範囲> <色>」（例: 「合成 圧力計0-150 白」）。
   - kind: synthetic, provisional: 0
   - note: "文字盤の色で分けた。針の形・書体・縁の色は同じ台の中でも混ざる（生成の仕組みの制約）"
2. 企業提供画像:
   - 気密試験 -> JSW-001, 表示名: 「圧力計（企業提供・気密試験）」
   - 耐圧試験 -> JSW-002, 表示名: 「圧力計（企業提供・耐圧試験）」
   - kind: corporate, provisional: 1
3. 一般画像:
   - ファイル名昇順で GEN-001 〜 GEN-005, 表示名: 「一般 メーター1」〜「一般 メーター5」
   - kind: general, provisional: 1
4. eval/devices.csv の生成（UTF-8 BOM）
5. groundtruth_synthetic.json および画像隣接サイドカーJSONへの書き込み
   （書き込み前に groundtruth_synthetic.before_ids.json としてバックアップ）
6. eval/groundtruth.json への書き込み（企業提供・一般の計9件をbasename照合で更新）
7. --dry-run オプションによる安全な事前確認
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import os
from pathlib import Path
import shutil
import sys
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# 合成メーターの固定順序
SYNTHETIC_METER_ORDER = [
    "pressure-150",
    "pressure-16",
    "pressure-1.6",
    "pressure-1.0",
    "pressure-250",
    "pressure-400",
    "pressure--0.1:0.5",
    "temperature-100",
    "temperature-60",
    "temperature--20:120",
]

# 合成メーターの表示名ラベル
SYNTHETIC_METER_LABELS = {
    "pressure-150": "圧力計0-150",
    "pressure-16": "圧力計0-16",
    "pressure-1.6": "圧力計0-1.6",
    "pressure-1.0": "圧力計0-1.0",
    "pressure-250": "圧力計0-250",
    "pressure-400": "圧力計0-400",
    "pressure--0.1:0.5": "圧力計-0.1〜0.5",
    "temperature-100": "温度計0-100",
    "temperature-60": "温度計0-60",
    "temperature--20:120": "温度計-20〜120",
}

# 文字盤色順序と表示ラベル
DIAL_COLOR_ORDER = ["white", "cream", "black"]
COLOR_LABELS = {
    "white": "白",
    "cream": "クリーム",
    "black": "黒",
}

SYNTHETIC_NOTE = "文字盤の色で分けた。針の形・書体・縁の色は同じ台の中でも混ざる（生成の仕組みの制約）"

# 合成メーターの既定仕様（フォールバック用）
SYNTHETIC_DEFAULTS = {
    "pressure-150": {"unit": "MPa", "min_value": 0.0, "max_value": 150.0},
    "pressure-16": {"unit": "bar", "min_value": 0.0, "max_value": 16.0},
    "pressure-1.6": {"unit": "MPa", "min_value": 0.0, "max_value": 1.6},
    "pressure-1.0": {"unit": "MPa", "min_value": 0.0, "max_value": 1.0},
    "pressure-250": {"unit": "kPa", "min_value": 0.0, "max_value": 250.0},
    "pressure-400": {"unit": "MPa", "min_value": 0.0, "max_value": 400.0},
    "pressure--0.1:0.5": {"unit": "MPa", "min_value": -0.1, "max_value": 0.5},
    "temperature-100": {"unit": "℃", "min_value": 0.0, "max_value": 100.0},
    "temperature-60": {"unit": "℃", "min_value": 0.0, "max_value": 60.0},
    "temperature--20:120": {"unit": "℃", "min_value": -20.0, "max_value": 120.0},
}


def build_synthetic_devices(
    gt_synthetic_path: Optional[Path] = None,
) -> Tuple[List[Dict[str, Any]], Dict[Tuple[str, str], Dict[str, Any]]]:
    """合成メーター30台のデバイス情報とマッピングを生成する。"""
    meter_specs = {k: dict(v) for k, v in SYNTHETIC_DEFAULTS.items()}

    # 実データが存在すれば正解から仕様（min, max, unit）を取得して更新
    if gt_synthetic_path and gt_synthetic_path.is_file():
        try:
            with open(gt_synthetic_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            for item in data:
                m_id = item.get("condition", {}).get("meter_id")
                if m_id in meter_specs:
                    if "min_value" in item and item["min_value"] is not None:
                        meter_specs[m_id]["min_value"] = float(item["min_value"])
                    if "max_value" in item and item["max_value"] is not None:
                        meter_specs[m_id]["max_value"] = float(item["max_value"])
                    # サイドカーからunitを拾えるか確認
                    img_path = item.get("image", "")
                    if img_path:
                        # 相対パスまたは絶対パスに対応
                        candidate_sidecar = gt_synthetic_path.parent / Path(img_path).name
                        if not candidate_sidecar.exists():
                            candidate_sidecar = Path(img_path).with_suffix(".json")
                        if candidate_sidecar.exists():
                            try:
                                with open(candidate_sidecar, "r", encoding="utf-8") as sc_f:
                                    sc_data = json.load(sc_f)
                                if sc_data.get("unit"):
                                    meter_specs[m_id]["unit"] = sc_data["unit"]
                            except Exception:
                                pass
        except Exception as e:
            logger.warning(f"合成正解データの仕様読み込みで例外が発生しました (フォールバック使用): {e}")

    devices: List[Dict[str, Any]] = []
    mapping: Dict[Tuple[str, str], Dict[str, Any]] = {}
    seq = 1

    for m_id in SYNTHETIC_METER_ORDER:
        spec = meter_specs.get(m_id, SYNTHETIC_DEFAULTS.get(m_id, {}))
        for color in DIAL_COLOR_ORDER:
            dev_id = f"SYN-{seq:03d}"
            seq += 1
            dev_name = f"合成 {SYNTHETIC_METER_LABELS.get(m_id, m_id)} {COLOR_LABELS.get(color, color)}"
            dev_info = {
                "device_id": dev_id,
                "device_name": dev_name,
                "kind": "synthetic",
                "unit": spec.get("unit", ""),
                "min_value": spec.get("min_value", 0.0),
                "max_value": spec.get("max_value", 0.0),
                "provisional": 0,
                "note": SYNTHETIC_NOTE,
            }
            devices.append(dev_info)
            mapping[(m_id, color)] = dev_info

    return devices, mapping


def build_corporate_devices(
    corporate_dir: Optional[Path] = None,
) -> Tuple[List[Dict[str, Any]], Dict[str, Dict[str, Any]]]:
    """企業提供メーター2台のデバイス情報とマッピングを生成する。"""
    jsw_001 = {
        "device_id": "JSW-001",
        "device_name": "圧力計（企業提供・気密試験）",
        "kind": "corporate",
        "unit": "MPa",
        "min_value": 0.0,
        "max_value": 150.0,
        "provisional": 1,
        "note": "仮ID",
    }
    jsw_002 = {
        "device_id": "JSW-002",
        "device_name": "圧力計（企業提供・耐圧試験）",
        "kind": "corporate",
        "unit": "MPa",
        "min_value": 0.0,
        "max_value": 400.0,
        "provisional": 1,
        "note": "仮ID",
    }
    devices = [jsw_001, jsw_002]

    # 画像ファイル名（basename）からデバイスへのマッピング
    mapping: Dict[str, Dict[str, Any]] = {}
    if corporate_dir and corporate_dir.is_dir():
        for p in sorted(corporate_dir.iterdir()):
            if p.suffix.lower() in [".jpg", ".jpeg", ".png"]:
                if "気密試験" in p.name:
                    mapping[p.name.lower()] = jsw_001
                elif "耐圧試験" in p.name:
                    mapping[p.name.lower()] = jsw_002

    return devices, mapping


def build_general_devices(
    general_dir: Optional[Path] = None,
    groundtruth_real_path: Optional[Path] = None,
) -> Tuple[List[Dict[str, Any]], Dict[str, Dict[str, Any]]]:
    """一般メーター5台のデバイス情報とマッピングを生成する。"""
    # 既定の一般メーター情報（ファイル名昇順）
    default_general_files = [
        "20260817_134647.jpg",
        "20260817_134656.jpg",
        "20260817_134745.jpg",
        "meter1.png",
        "meter2.jpg",
    ]

    files: List[str] = []
    if general_dir and general_dir.is_dir():
        found = [
            p.name
            for p in sorted(general_dir.iterdir(), key=lambda x: x.name)
            if p.suffix.lower() in [".jpg", ".jpeg", ".png"]
        ]
        if found:
            files = found

    if not files:
        files = default_general_files

    # groundtruth.jsonからmin, max, unitの参照を試みる
    real_gt_info: Dict[str, Dict[str, Any]] = {}
    if groundtruth_real_path and groundtruth_real_path.is_file():
        try:
            with open(groundtruth_real_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            for item in data:
                bname = Path(item.get("image", "")).name.lower()
                real_gt_info[bname] = item
        except Exception as e:
            logger.warning(f"実写groundtruth読み込み失敗 (フォールバック使用): {e}")

    # 一般メーターの既定仕様
    general_specs = {
        "20260817_134647.jpg": {"unit": "℃", "min_value": 0.0, "max_value": 100.0},
        "20260817_134656.jpg": {"unit": "℃", "min_value": 0.0, "max_value": 100.0},
        "20260817_134745.jpg": {"unit": "℃", "min_value": 0.0, "max_value": 100.0},
        "meter1.png": {"unit": "℃", "min_value": 0.0, "max_value": 150.0},
        "meter2.jpg": {"unit": "psi", "min_value": 0.0, "max_value": 100.0},
    }

    devices: List[Dict[str, Any]] = []
    mapping: Dict[str, Dict[str, Any]] = {}

    for idx, fname in enumerate(files):
        dev_id = f"GEN-{idx + 1:03d}"
        dev_name = f"一般 メーター{idx + 1}"
        spec = general_specs.get(fname, {"unit": "", "min_value": 0.0, "max_value": 0.0})

        # real_gt_infoにあれば反映
        gt_item = real_gt_info.get(fname.lower())
        if gt_item:
            if "min_value" in gt_item and gt_item["min_value"] is not None:
                spec["min_value"] = float(gt_item["min_value"])
            if "max_value" in gt_item and gt_item["max_value"] is not None:
                spec["max_value"] = float(gt_item["max_value"])

        dev_info = {
            "device_id": dev_id,
            "device_name": dev_name,
            "kind": "general",
            "unit": spec.get("unit", ""),
            "min_value": spec.get("min_value", 0.0),
            "max_value": spec.get("max_value", 0.0),
            "provisional": 1,
            "note": "仮ID",
        }
        devices.append(dev_info)
        mapping[fname.lower()] = dev_info

    return devices, mapping


def write_devices_csv(devices: List[Dict[str, Any]], csv_path: Path, dry_run: bool = False) -> None:
    """eval/devices.csv を UTF-8 BOM で書き出す。"""
    fieldnames = [
        "device_id",
        "device_name",
        "kind",
        "unit",
        "min_value",
        "max_value",
        "provisional",
        "note",
    ]
    if dry_run:
        logger.info(f"[DRY-RUN] devices.csv 出力先: {csv_path} (行数: {len(devices)})")
        return

    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with open(csv_path, mode="w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for dev in devices:
            writer.writerow(dev)
    logger.info(f"devices.csv を出力しました: {csv_path} (全 {len(devices)} 行)")


def assign_synthetic_data(
    synthetic_dir: Path,
    mapping: Dict[Tuple[str, str], Dict[str, Any]],
    dry_run: bool = False,
) -> Tuple[int, int]:
    """合成画像フォルダの groundtruth_synthetic.json およびサイドカーJSONを更新する。"""
    gt_file = synthetic_dir / "groundtruth_synthetic.json"
    if not gt_file.is_file():
        logger.warning(f"合成正解ファイルが存在しません: {gt_file}")
        return 0, 0

    with open(gt_file, "r", encoding="utf-8") as f:
        gt_data = json.load(f)

    if not isinstance(gt_data, list):
        raise ValueError(f"正解データのトップレベルがリストではありません: {gt_file}")

    # バックアップ作成
    backup_file = synthetic_dir / "groundtruth_synthetic.before_ids.json"
    if not dry_run:
        shutil.copy2(gt_file, backup_file)
        logger.info(f"バックアップを作成しました: {backup_file}")
    else:
        logger.info(f"[DRY-RUN] バックアップ予定: {backup_file}")

    gt_updated_count = 0
    sidecar_updated_count = 0

    for item in gt_data:
        m_id = item.get("condition", {}).get("meter_id")
        color = item.get("appearance", {}).get("dial_color")
        key = (m_id, color)
        dev = mapping.get(key)
        if dev:
            item["device_id"] = dev["device_id"]
            item["device_name"] = dev["device_name"]
            gt_updated_count += 1
        else:
            logger.warning(f"合成データに対応するデバイスが見つかりません: key={key}, image={item.get('image')}")

        # サイドカーJSONの更新
        img_rel = item.get("image", "")
        if img_rel:
            img_path = Path(img_rel)
            # パス解決（絶対パスまたはsynthetic_dir配下）
            if img_path.is_file():
                sidecar_path = img_path.with_suffix(".json")
            else:
                sidecar_path = synthetic_dir / img_path.parent.name / f"{img_path.stem}.json"
                if not sidecar_path.is_file():
                    sidecar_path = synthetic_dir / f"{img_path.stem}.json"

            if sidecar_path.is_file() and dev:
                if not dry_run:
                    try:
                        with open(sidecar_path, "r", encoding="utf-8") as sc_f:
                            sc_data = json.load(sc_f)
                        sc_data["device_id"] = dev["device_id"]
                        sc_data["device_name"] = dev["device_name"]
                        with open(sidecar_path, "w", encoding="utf-8") as sc_f:
                            json.dump(sc_data, sc_f, ensure_ascii=False, indent=2)
                        sidecar_updated_count += 1
                    except Exception as e:
                        logger.warning(f"サイドカーの更新に失敗しました ({sidecar_path}): {e}")
                else:
                    sidecar_updated_count += 1

    if not dry_run:
        with open(gt_file, "w", encoding="utf-8") as f:
            json.dump(gt_data, f, ensure_ascii=False, indent=2)
        logger.info(f"groundtruth_synthetic.json を更新しました (更新件数: {gt_updated_count})")
    else:
        logger.info(f"[DRY-RUN] groundtruth_synthetic.json 更新予定件数: {gt_updated_count}, サイドカー予定件数: {sidecar_updated_count}")

    return gt_updated_count, sidecar_updated_count


def assign_real_groundtruth(
    real_gt_path: Path,
    corporate_mapping: Dict[str, Dict[str, Any]],
    general_mapping: Dict[str, Dict[str, Any]],
    dry_run: bool = False,
) -> Tuple[int, List[str]]:
    """eval/groundtruth.json を更新する。"""
    if not real_gt_path.is_file():
        logger.warning(f"実写groundtruthが存在しません: {real_gt_path}")
        return 0, []

    with open(real_gt_path, "r", encoding="utf-8") as f:
        gt_data = json.load(f)

    updated_count = 0
    unmatched_images: List[str] = []

    for item in gt_data:
        img_str = item.get("image", "")
        bname = Path(img_str).name.lower()

        dev: Optional[Dict[str, Any]] = None
        # 1. 企業提供
        if "気密試験" in bname:
            dev = corporate_mapping.get(bname) or {
                "device_id": "JSW-001",
                "device_name": "圧力計（企業提供・気密試験）",
            }
        elif "耐圧試験" in bname:
            dev = corporate_mapping.get(bname) or {
                "device_id": "JSW-002",
                "device_name": "圧力計（企業提供・耐圧試験）",
            }
        # 2. 一般
        elif bname in general_mapping:
            dev = general_mapping[bname]

        if dev:
            item["device_id"] = dev["device_id"]
            item["device_name"] = dev["device_name"]
            updated_count += 1
        else:
            unmatched_images.append(img_str)
            logger.info(f"対象外（スキップ）: {img_str}")

    if not dry_run:
        with open(real_gt_path, "w", encoding="utf-8") as f:
            json.dump(gt_data, f, ensure_ascii=False, indent=2)
        logger.info(f"eval/groundtruth.json を更新しました (更新件数: {updated_count})")
    else:
        logger.info(f"[DRY-RUN] eval/groundtruth.json 更新予定件数: {updated_count}, 対象外: {len(unmatched_images)}")

    return updated_count, unmatched_images


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="テスト画像に機器ID・表示名を付与し、devices.csvを生成する。")
    parser.add_argument(
        "--synthetic-dir",
        type=Path,
        default=Path(r"C:\卒研\合成画像\テスト用_20261021"),
        help="合成画像フォルダへのパス",
    )
    parser.add_argument(
        "--corporate-dir",
        type=Path,
        default=Path(r"C:\卒研\サンプルメーター（本番用）\企業提供_日本製鋼所"),
        help="企業提供画像フォルダへのパス",
    )
    parser.add_argument(
        "--general-dir",
        type=Path,
        default=Path(r"C:\卒研\サンプルメーター（本番用）\一般"),
        help="一般画像フォルダへのパス",
    )
    parser.add_argument(
        "--devices-csv",
        type=Path,
        default=Path(r"eval/devices.csv"),
        help="出力する devices.csv のパス",
    )
    parser.add_argument(
        "--groundtruth-real",
        type=Path,
        default=Path(r"eval/groundtruth.json"),
        help="実写 groundtruth.json のパス",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="実際のファイル書き換えを行わず、ログ出力のみ行う",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="詳細ログを表示する",
    )

    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="[%(levelname)s] %(message)s",
    )

    logger.info("=== 機器ID割り当て処理を開始します ===")
    if args.dry_run:
        logger.info("モード: DRY-RUN（ファイルの書き換えは行いません）")
    else:
        logger.info("モード: 本番実行")

    # 1. 機器リストの構築
    synth_gt_path = args.synthetic_dir / "groundtruth_synthetic.json"
    synth_devices, synth_map = build_synthetic_devices(synth_gt_path)
    logger.info(f"合成メーター: {len(synth_devices)} 台 (予想: 30台)")

    corp_devices, corp_map = build_corporate_devices(args.corporate_dir)
    logger.info(f"企業提供メーター: {len(corp_devices)} 台 (JSW-001, JSW-002)")

    gen_devices, gen_map = build_general_devices(args.general_dir, args.groundtruth_real)
    logger.info(f"一般メーター: {len(gen_devices)} 台 (GEN-001〜GEN-{len(gen_devices):03d})")

    all_devices = synth_devices + corp_devices + gen_devices
    logger.info(f"合計機器台数: {len(all_devices)} 台 (合成={len(synth_devices)}, 企業={len(corp_devices)}, 一般={len(gen_devices)})")

    # 2. devices.csv の出力
    write_devices_csv(all_devices, args.devices_csv, dry_run=args.dry_run)

    # 3. 合成画像データの更新
    if args.synthetic_dir.is_dir():
        gt_up, sc_up = assign_synthetic_data(args.synthetic_dir, synth_map, dry_run=args.dry_run)
        logger.info(f"合成データ処理結果: groundtruth_synthetic.json={gt_up}件, サイドカーJSON={sc_up}件")
    else:
        logger.warning(f"合成画像フォルダが見つかりません: {args.synthetic_dir}")

    # 4. 実写 groundtruth.json の更新
    if args.groundtruth_real.is_file():
        real_up, unmatched = assign_real_groundtruth(
            args.groundtruth_real, corp_map, gen_map, dry_run=args.dry_run
        )
        logger.info(f"実写groundtruth処理結果: 更新={real_up}件, 対象外={len(unmatched)}件")
    else:
        logger.warning(f"実写groundtruthが見つかりません: {args.groundtruth_real}")

    logger.info("=== 機器ID割り当て処理が完了しました ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
