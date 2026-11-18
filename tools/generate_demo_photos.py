"""デモ用3Dメーター画像80枚と真値JSONを生成するモジュール。

仕様: tasks/design/デモ用3Dメーターと機器カタログ.md
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys

from PIL import Image

from manager.qr_decode import read_device_qr
from manager.qr_label import parse_payload
from tools.demo_catalog import APPEARANCE_KEYS, DEFAULT_CATALOG_PATH, load_catalog
from tools.embed_qr_into_synthetic import create_qr_plate

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PHOTOS_DIR = REPO_ROOT / "demo" / "photos"
METER3D_DIR = Path(__file__).resolve().parent / "meter3d"

RENDERER_HASHES: dict[str, str] = {
    "meter3d.html": "c3b6f7c5551be1c36dddd84f2483fb1c96a6239cd0c33946fcc96274484da731",
    "batch/generate.cjs": "f90ccfb9105f7054da3f1fae6e929dfdd3cb5a1477b444e41dba25b2183d7ad4",
    "batch/final_set_plan.cjs": "f5db7a3f45475ae69661d8673e6f5f426f54d0f9df3cc4cbd56a7f1fa6ea8d69",
}

RENDERER_APPEARANCE_KEYS: tuple[str, ...] = (
    "sweep_deg",
    "dial_color",
    "number_position",
    "font",
    "needle_shape",
    "needle_color",
    "bezel_color",
    "danger_band",
    "max_pointer",
)

SHOT_SPECS: dict[int, dict[str, int | float | str]] = {
    1: {
        "value_percent": 7,
        "yaw_deg": 0,
        "pitch_deg": 0,
        "lighting": "normal",
        "glass_scratches": 0,
        "sensor_noise": 0,
    },
    2: {
        "value_percent": 48,
        "yaw_deg": 30,
        "pitch_deg": 0,
        "lighting": "glare",
        "glass_scratches": 0.2,
        "sensor_noise": 0.08,
    },
    3: {
        "value_percent": 93,
        "yaw_deg": 0,
        "pitch_deg": 25,
        "lighting": "normal",
        "glass_scratches": 0.35,
        "sensor_noise": 0.15,
    },
    4: {
        "value_percent": 27,
        "yaw_deg": 45,
        "pitch_deg": 0,
        "lighting": "normal",
        "glass_scratches": 0.1,
        "sensor_noise": 0.04,
    },
}

RENDERER_TIMEOUT_SECONDS = 90
_DEVICE_NUM_RE = re.compile(r"^DMO-(\d{3})$")

BASE_WIDTH = 1280
BASE_HEIGHT = 960
SIDEBAR_WIDTH = 256
SIDEBAR_BG_COLOR = (0xE5, 0xE7, 0xEB)
QR_LABEL_POS = (1296, 64)
QR_PLATE_SIZE = 224
QR_MAX_DISPLAY_SIZE = 200
QR_BBOX = [1296, 64, 224, 224]


def is_odd_device_id(device_id: str) -> bool:
    """機器IDの末尾番号が奇数であれば True、偶数であれば False を返す。"""
    m = _DEVICE_NUM_RE.fullmatch(device_id)
    if not m:
        raise ValueError(f"device_id の形式が不正です: {device_id!r}")
    return int(m.group(1)) % 2 == 1


def verify_qr_frame(png_path: Path, device: dict) -> None:
    """QR付き画像からQRを読み戻し、カタログの機器情報と照合する。"""
    qr_res = read_device_qr(png_path)
    if qr_res.status != "found" or qr_res.device_id != device["device_id"]:
        raise ValueError(
            f"{device['device_id']}: QR読み取りに失敗しました "
            f"(status={qr_res.status!r}, device_id={qr_res.device_id!r})"
        )

    matched_parsed: dict | None = None
    for text in qr_res.payloads:
        try:
            raw_obj = json.loads(text)
        except Exception:
            continue
        if isinstance(raw_obj, dict) and (
            "acceptable_min" in raw_obj or "acceptable_max" in raw_obj
        ):
            raise ValueError(
                f"{device['device_id']}: QRペイロードに許容範囲キーが含まれています"
            )
        parsed = parse_payload(text)
        if parsed is not None and parsed.get("id") == device["device_id"]:
            matched_parsed = parsed
            break

    if matched_parsed is None:
        raise ValueError(f"{device['device_id']}: parse_payload で対象機器を復元できません")

    if matched_parsed.get("name") != device["device_name"]:
        raise ValueError(
            f"{device['device_id']}: QRの機器名が不一致です "
            f"(期待 {device['device_name']!r}, 実際 {matched_parsed.get('name')!r})"
        )
    if matched_parsed.get("unit") != device["unit"]:
        raise ValueError(
            f"{device['device_id']}: QRの単位が不一致です "
            f"(期待 {device['unit']!r}, 実際 {matched_parsed.get('unit')!r})"
        )
    for key_qr, key_cat in (("min", "min_value"), ("max", "max_value")):
        val = matched_parsed.get(key_qr)
        expected = device[key_cat]
        if not isinstance(val, (int, float)) or abs(float(val) - float(expected)) > 1e-8:
            raise ValueError(
                f"{device['device_id']}: QRの {key_qr} が不一致です "
                f"(期待 {expected!r}, 実際 {val!r})"
            )


def compose_qr_frame(raw_png: Path, dest_png: Path, device: dict) -> list[int]:
    """元PNGの右に256pxの帯を足し、QRラベルを合成して読み戻し照合する。"""
    with Image.open(raw_png) as img:
        base = img.convert("RGB")
        if base.size != (BASE_WIDTH, BASE_HEIGHT):
            raise ValueError(
                f"{device['device_id']}: 元画像サイズが想定外です "
                f"(期待 {(BASE_WIDTH, BASE_HEIGHT)}, 実際 {base.size})"
            )
        canvas = Image.new("RGB", (BASE_WIDTH + SIDEBAR_WIDTH, BASE_HEIGHT), SIDEBAR_BG_COLOR)
        canvas.paste(base, (0, 0))

    plate = create_qr_plate(
        device["device_id"],
        device["device_name"],
        plate_size=QR_PLATE_SIZE,
        qr_display_size=QR_MAX_DISPLAY_SIZE,
        unit=device["unit"],
        min_value=device["min_value"],
        max_value=device["max_value"],
    )
    canvas.paste(plate, QR_LABEL_POS)
    dest_png.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(dest_png, format="PNG")
    verify_qr_frame(dest_png, device)
    return list(QR_BBOX)


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def verify_renderer_hashes(meter3d_dir: Path = METER3D_DIR) -> None:
    """取り込み済み3Dレンダラー3ファイルのSHA-256を検証する（WindowsのCRLF変換を許容）。"""
    for rel, expected in RENDERER_HASHES.items():
        target = meter3d_dir / rel
        if not target.is_file():
            raise FileNotFoundError(f"レンダラーファイルが見つかりません: {target}")
        raw = target.read_bytes()
        actual = hashlib.sha256(raw).hexdigest()
        normalized = hashlib.sha256(raw.replace(b"\r\n", b"\n")).hexdigest()
        if expected not in (actual, normalized):
            raise ValueError(
                f"レンダラーのSHA-256が一致しません ({rel}): "
                f"期待 {expected}, 実際 {actual}"
            )


def copy_renderer(meter3d_dir: Path, renderer_dir: Path) -> Path:
    """レンダラー3ファイルを相対配置のまま作業用ディレクトリへコピーする。"""
    verify_renderer_hashes(meter3d_dir)
    for rel in RENDERER_HASHES:
        src = meter3d_dir / rel
        dst = renderer_dir / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
    return renderer_dir / "batch" / "generate.cjs"


def compute_seed(device_id: str, shot: int) -> int:
    """機器IDとshot番号から決定的なシード値を計算する。"""
    m = _DEVICE_NUM_RE.fullmatch(device_id)
    if not m:
        raise ValueError(f"device_id の形式が不正です: {device_id!r}")
    if shot not in SHOT_SPECS:
        raise ValueError(f"shot 番号が不正です: {shot}")
    return 1000 + int(m.group(1)) * 10 + shot


def build_renderer_args(device: dict, shot: int, raw_dir: Path) -> list[str]:
    """カタログ1行とshot番号から generate.cjs 用の引数リストを組み立てる。"""
    if shot not in SHOT_SPECS:
        raise ValueError(f"shot 番号が不正です: {shot}")
    spec = SHOT_SPECS[shot]
    seed = compute_seed(device["device_id"], shot)
    return [
        "--meters",
        str(device["meter_key"]),
        "--values",
        str(spec["value_percent"]),
        "--cameras",
        f"{spec['yaw_deg']}:{spec['pitch_deg']}",
        "--lightings",
        str(spec["lighting"]),
        "--distance",
        "5.6",
        "--seed",
        str(seed),
        "--sweep-deg",
        str(device["sweep_deg"]),
        "--dial-color",
        str(device["dial_color"]),
        "--number-position",
        str(device["number_position"]),
        "--font",
        str(device["font"]),
        "--needle-shape",
        str(device["needle_shape"]),
        "--needle-color",
        str(device["needle_color"]),
        "--bezel-color",
        str(device["bezel_color"]),
        "--danger-band",
        "true" if device["danger_band"] else "false",
        "--max-pointer",
        "true" if device["max_pointer"] else "false",
        "--glass-scratches",
        str(spec["glass_scratches"]),
        "--sensor-noise",
        str(spec["sensor_noise"]),
        "--out",
        str(Path(raw_dir).resolve()),
    ]


def verify_raw_output(device: dict, shot: int, raw_dir: Path) -> tuple[Path, dict]:
    """生成器の manifest.json と個別JSONを読み、台帳およびshot条件と照合する。"""
    if shot not in SHOT_SPECS:
        raise ValueError(f"shot 番号が不正です: {shot}")
    raw_root = Path(raw_dir).resolve()
    manifest_path = raw_root / "manifest.json"
    if not manifest_path.is_file():
        raise ValueError(f"manifest.json が見つかりません: {manifest_path}")

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    frames = manifest.get("frames")
    if not isinstance(frames, list) or len(frames) != 1:
        raise ValueError(
            f"manifest.json の frames 件数が1ではありません: "
            f"{len(frames) if isinstance(frames, list) else type(frames).__name__}"
        )
    frame = frames[0]

    file_rel = frame.get("file")
    json_rel = frame.get("json")
    if not isinstance(file_rel, str) or not isinstance(json_rel, str):
        raise ValueError("manifest.json の file または json が文字列ではありません")

    png_path = (raw_root / file_rel).resolve()
    json_path = (raw_root / json_rel).resolve()
    if not png_path.is_relative_to(raw_root) or not png_path.is_file():
        raise ValueError(f"PNGファイルが raw_dir 内に存在しません: {file_rel}")
    if not json_path.is_relative_to(raw_root) or not json_path.is_file():
        raise ValueError(f"個別JSONが raw_dir 内に存在しません: {json_rel}")

    frame_json = json.loads(json_path.read_text(encoding="utf-8"))
    actual_unit = frame_json.get("unit")
    if actual_unit != device["unit"]:
        raise ValueError(
            f"{device['device_id']} shot {shot}: unit が不一致です "
            f"(期待 {device['unit']!r}, 実際 {actual_unit!r})"
        )

    for bound_key in ("min_value", "max_value"):
        actual_bound = frame.get(bound_key)
        expected_bound = device[bound_key]
        if not isinstance(actual_bound, (int, float)) or abs(actual_bound - expected_bound) > 1e-8:
            raise ValueError(
                f"{device['device_id']} shot {shot}: {bound_key} が不一致です "
                f"(期待 {expected_bound}, 実際 {actual_bound})"
            )

    pct = float(SHOT_SPECS[shot]["value_percent"])
    expected_true = device["min_value"] + (device["max_value"] - device["min_value"]) * pct / 100.0
    actual_true = frame.get("true_value")
    if not isinstance(actual_true, (int, float)) or abs(actual_true - expected_true) > 1e-8:
        raise ValueError(
            f"{device['device_id']} shot {shot}: true_value が不一致です "
            f"(期待 {expected_true}, 実際 {actual_true})"
        )

    actual_app = frame.get("appearance")
    if not isinstance(actual_app, dict):
        raise ValueError(f"{device['device_id']} shot {shot}: appearance が辞書ではありません")
    for key in RENDERER_APPEARANCE_KEYS:
        expected_val = device[key]
        actual_val = actual_app.get(key)
        if type(actual_val) is not type(expected_val) or actual_val != expected_val:
            raise ValueError(
                f"{device['device_id']} shot {shot}: 外観 {key} が不一致です "
                f"(期待 {expected_val!r}, 実際 {actual_val!r})"
            )

    return png_path, frame


def render_frame(
    device: dict,
    shot: int,
    raw_dir: Path,
    *,
    renderer_script: Path | None = None,
) -> tuple[Path, dict]:
    """1条件分の3Dメーター画像をレンダリングし、出力を照合して返す。"""
    script = renderer_script if renderer_script is not None else METER3D_DIR / "batch" / "generate.cjs"
    raw_dir = Path(raw_dir)
    raw_dir.mkdir(parents=True, exist_ok=True)
    cmd = ["node", str(script), *build_renderer_args(device, shot, raw_dir)]
    proc = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=RENDERER_TIMEOUT_SECONDS,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"{device['device_id']} shot {shot} のレンダリングに失敗しました "
            f"(returncode={proc.returncode}): {proc.stderr or proc.stdout}"
        )
    return verify_raw_output(device, shot, raw_dir)


def build_groundtruth_entry(
    device: dict,
    shot: int,
    rel_file: str,
    png_sha256: str,
    raw_frame: dict,
    *,
    qr_bbox: list[int] | None = None,
) -> dict:
    """groundtruth.json の1フレーム分エントリを組み立てる。"""
    spec = SHOT_SPECS[shot]
    return {
        "file": rel_file,
        "sha256": png_sha256,
        "device_id": device["device_id"],
        "device_name": device["device_name"],
        "appearance": {k: device[k] for k in APPEARANCE_KEYS},
        "shot": shot,
        "seed": compute_seed(device["device_id"], shot),
        "true_value": raw_frame["true_value"],
        "unit": device["unit"],
        "min_value": device["min_value"],
        "max_value": device["max_value"],
        "value_percent": spec["value_percent"],
        "yaw_deg": spec["yaw_deg"],
        "pitch_deg": spec["pitch_deg"],
        "lighting": spec["lighting"],
        "glass_scratches": spec["glass_scratches"],
        "sensor_noise": spec["sensor_noise"],
        "qr_bbox": qr_bbox,
    }


def verify_groundtruth(catalog: list[dict], truth: dict, photos_dir: Path) -> None:
    """groundtruth.json の全フレームをカタログおよび実ファイルと照合する。"""
    if truth.get("v") != 1:
        raise ValueError(f"groundtruth.json のバージョンが不正です: {truth.get('v')!r}")
    frames = truth.get("frames")
    expected_count = len(catalog) * len(SHOT_SPECS)
    if not isinstance(frames, list) or len(frames) != expected_count:
        raise ValueError(
            f"groundtruth.json のフレーム数が不正です "
            f"(期待 {expected_count}, 実際 {len(frames) if isinstance(frames, list) else 'non-list'})"
        )

    photos_root = Path(photos_dir).resolve()
    seen_sha: set[str] = set()
    idx = 0
    for device in catalog:
        expected_app = {k: device[k] for k in APPEARANCE_KEYS}
        for shot in sorted(SHOT_SPECS):
            entry = frames[idx]
            idx += 1
            if entry.get("device_id") != device["device_id"] or entry.get("shot") != shot:
                raise ValueError(
                    f"frames[{idx - 1}] の順序/IDが不正です "
                    f"(期待 {(device['device_id'], shot)}, 実際 {(entry.get('device_id'), entry.get('shot'))})"
                )
            if entry.get("device_name") != device["device_name"]:
                raise ValueError(f"{device['device_id']} shot {shot}: device_name が不一致です")
            if entry.get("appearance") != expected_app:
                raise ValueError(f"{device['device_id']} shot {shot}: appearance が不一致です")
            if entry.get("unit") != device["unit"]:
                raise ValueError(f"{device['device_id']} shot {shot}: unit が不一致です")
            if entry.get("min_value") != device["min_value"] or entry.get("max_value") != device["max_value"]:
                raise ValueError(f"{device['device_id']} shot {shot}: min/max_value が不一致です")

            pct = SHOT_SPECS[shot]["value_percent"]
            expected_true = device["min_value"] + (device["max_value"] - device["min_value"]) * float(pct) / 100.0
            if abs(entry.get("true_value", float("nan")) - expected_true) > 1e-8:
                raise ValueError(f"{device['device_id']} shot {shot}: true_value が不一致です")

            rel_file = entry.get("file")
            if not isinstance(rel_file, str):
                raise ValueError(f"{device['device_id']} shot {shot}: file が文字列ではありません")
            png_path = (photos_root / rel_file).resolve()
            if not png_path.is_relative_to(photos_root) or not png_path.is_file():
                raise ValueError(f"{device['device_id']} shot {shot}: 画像が見つかりません: {rel_file}")

            sha = entry.get("sha256")
            actual_sha = _sha256_file(png_path)
            if sha != actual_sha:
                raise ValueError(
                    f"{device['device_id']} shot {shot}: SHA-256 が不一致です "
                    f"(記録 {sha}, 実際 {actual_sha})"
                )
            if sha in seen_sha:
                raise ValueError(f"公開用画像のSHA-256が重複しています: {sha}")
            seen_sha.add(sha)

            expected_bbox = list(QR_BBOX) if is_odd_device_id(device["device_id"]) else None
            if entry.get("qr_bbox") != expected_bbox:
                raise ValueError(
                    f"{device['device_id']} shot {shot}: qr_bbox が不一致です "
                    f"(期待 {expected_bbox}, 実際 {entry.get('qr_bbox')})"
                )


def generate_demo_photos(
    catalog_path: Path = DEFAULT_CATALOG_PATH,
    photos_dir: Path = DEFAULT_PHOTOS_DIR,
    meter3d_dir: Path = METER3D_DIR,
) -> dict:
    """カタログ全機器の4ショット画像を生成し、groundtruth.json を書き出す。"""
    photos_dir = Path(photos_dir)
    if photos_dir.exists():
        raise FileExistsError(f"出力先ディレクトリが既に存在します: {photos_dir}")

    catalog = load_catalog(catalog_path)
    verify_renderer_hashes(meter3d_dir)

    photos_dir.mkdir(parents=True, exist_ok=False)
    renderer_script = copy_renderer(meter3d_dir, photos_dir / "renderer")
    frames_dir = photos_dir / "frames"
    frames_dir.mkdir(parents=True, exist_ok=True)

    entries: list[dict] = []
    for device in catalog:
        for shot in sorted(SHOT_SPECS):
            raw_dir = photos_dir / "raw" / device["device_id"] / str(shot)
            raw_png, raw_frame = render_frame(
                device, shot, raw_dir, renderer_script=renderer_script
            )
            rel_file = f"frames/{device['device_id']}-{shot}.png"
            dest_png = photos_dir / rel_file
            if is_odd_device_id(device["device_id"]):
                qr_bbox = compose_qr_frame(raw_png, dest_png, device)
            else:
                shutil.copyfile(raw_png, dest_png)
                qr_bbox = None
            entries.append(
                build_groundtruth_entry(
                    device=device,
                    shot=shot,
                    rel_file=rel_file,
                    png_sha256=_sha256_file(dest_png),
                    raw_frame=raw_frame,
                    qr_bbox=qr_bbox,
                )
            )

    truth = {"v": 1, "frames": entries}
    verify_groundtruth(catalog, truth, photos_dir)
    (photos_dir / "groundtruth.json").write_text(
        json.dumps(truth, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return truth


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="デモ用3Dメーター画像80枚と真値JSONを生成")
    parser.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG_PATH)
    parser.add_argument("--out", type=Path, default=DEFAULT_PHOTOS_DIR)
    args = parser.parse_args(argv)

    try:
        truth = generate_demo_photos(catalog_path=args.catalog, photos_dir=args.out)
    except (FileExistsError, FileNotFoundError, OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print(f"OK: generated {len(truth['frames'])} frames in {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
