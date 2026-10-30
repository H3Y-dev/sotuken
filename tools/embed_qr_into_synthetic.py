"""3D合成画像に機器QRコード板を合成し、評価および取り込み用のデータセットを生成するツール。

仕様:
1. QR板の作成:
   - 各画像の device_id, device_name から build_payload(device_id, device_name) のQRを生成
   - 誤り訂正M、余白4モジュール
   - 一辺200pxの白板、QRの下に小さく機器IDの文字列を描画（日本語フォント探索再利用）
2. 貼る位置:
   - 画像の右下の隅（右および下から24pxの余白）
   - メーター中心(640, 480)、半径約380px（影含め約450px）に重ならない
   - 画像枠外にはみ出さない
3. 条件に合わせた劣化の適用（QR板領域のみ）:
   - ブレ（水平モーションブラー）: condition.blur / target_blur_width または degradations のpx数で水平ブラー適用
   - 斜め（透視変換 cv2.warpPerspective）: camera_yaw, camera_pitch に応じた遠近投影変換を行い右下隅に収める
   - 画質（degradations）:
     - jpeg_compression: JPEG再圧縮（品質値を強度から算出）
     - sensor_noise: センサーノイズ（乱数シード再現）
     - small_in_frame: 遠景化に伴う板サイズの縮小（カメラ後退率に基づく）
     - color_cast: 色温度・色かぶり
   - 反射・汚れ・紛らわしい文字・背景: QR板には何も適用しない（未対応・対象外）
4. 出力フォルダ構造（--out 既定: C:\\卒研\\合成画像\\テスト用QR付き_20261030）:
   - <out>\\画像\\<条件>\\<画像名>.png: QR合成後の画像
   - <out>\\正解_QR付き.json: 元の groundtruth_synthetic.json 各要素に qr 辞書を追加
   - <out>\\取り込み用_サイドカーに機器あり\\: 平らなフォルダ（QR付きPNG + サイドカーJSON: local_id, captured_at, device_id, device_name）
   - <out>\\取り込み用_QRのみ\\: 平らなフォルダ（QR付きPNG + サイドカーJSON: local_id, captured_at のみ）
   - <out>\\QR読み取り率.md: cv2.QRCodeDetector による条件別および全体の読み取り率・不一致画像一覧
   - <out>\\README.md: 構成・使い方・劣化近似方針の説明
5. captured_at の決定論的規則:
   - 機器ごとに画像をファイル名昇順でソート
   - 開始基準時刻: 2026-10-01T09:00:00+09:00
   - 機器番号 × 3分 だけ開始時刻をオフセット
   - 各画像は1日ずつ進める（再現性100%）
"""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import json
import math
import os
from pathlib import Path
import re
import sys
from typing import Any, Dict, List, Optional, Sequence, Tuple

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont
import qrcode
import qrcode.constants

# プロジェクトルートの追加
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from manager.qr_label import build_payload, find_japanese_font, parse_payload
from manager.sidecar import SidecarMetadata

# 定数定義
DEFAULT_INPUT_DIR = r"C:\卒研\合成画像\テスト用_20261021"
DEFAULT_OUTPUT_DIR = r"C:\卒研\合成画像\テスト用QR付き_20261030"
DEFAULT_PLATE_SIZE = 200
DEFAULT_MARGIN = 24
METER_CENTER = (640, 480)
METER_RADIUS_WITH_SHADOW = 450.0

CONDITIONS_ORDER = ["正面", "斜め", "反射", "ブレ", "汚れ", "紛らわしい文字", "背景と画質"]


def load_image_unicode_safe(path: str | Path) -> np.ndarray:
    """Windows環境の日本語パスにも安全な画像読み込み。"""
    path_str = str(path)
    if not os.path.exists(path_str):
        raise FileNotFoundError(f"Image not found: {path_str}")
    raw_data = np.fromfile(path_str, dtype=np.uint8)
    if raw_data.size == 0:
        raise ValueError(f"Image file is empty: {path_str}")
    img = cv2.imdecode(raw_data, cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError(f"Failed to decode image: {path_str}")
    return img


def save_image_unicode_safe(path: str | Path, img: np.ndarray) -> None:
    """Windows環境の日本語パスにも安全な画像保存。"""
    path_obj = Path(path)
    path_obj.parent.mkdir(parents=True, exist_ok=True)
    ext = path_obj.suffix.lower() or ".png"
    success, encoded = cv2.imencode(ext, img)
    if not success or encoded is None:
        raise RuntimeError(f"Failed to encode image to {ext}: {path_obj}")
    encoded.tofile(str(path_obj))


def extract_device_number(device_id: str, default_idx: int = 1) -> int:
    """機器IDから数値を抽出する（例: SYN-001 -> 1）。見つからない場合は default_idx。"""
    match = re.search(r"\d+", device_id)
    if match:
        return int(match.group())
    return default_idx


def create_qr_plate(
    device_id: str,
    device_name: str,
    plate_size: int = DEFAULT_PLATE_SIZE,
    qr_display_size: int = 150,
    text_font_size: int = 14,
) -> Image.Image:
    """機器IDと機器名から白板QR画像を生成する（200px×200px、下部に機器ID文字）。"""
    payload = build_payload(device_id, device_name)

    qr = qrcode.QRCode(
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=5,
        border=4,
    )
    qr.add_data(payload)
    qr.make(fit=True)
    raw_qr_img = qr.make_image(fill_color="black", back_color="white").convert("RGB")

    # 白板基底
    plate = Image.new("RGB", (plate_size, plate_size), (255, 255, 255))

    # QRリサイズと配置（上部中央）
    resized_qr = raw_qr_img.resize((qr_display_size, qr_display_size), Image.Resampling.NEAREST)
    qr_x = (plate_size - qr_display_size) // 2
    qr_y = 10
    plate.paste(resized_qr, (qr_x, qr_y))

    # 機器ID描画（QRの下に小さく中央揃え）
    try:
        font = find_japanese_font(size=text_font_size)
    except Exception:
        font = ImageFont.load_default()

    draw = ImageDraw.Draw(plate)
    text = device_id
    bbox = font.getbbox(text)
    tw = bbox[2] - bbox[0]
    tx = max(4, (plate_size - tw) // 2)
    ty = qr_y + qr_display_size + 6
    draw.text((tx, ty), text, fill="black", font=font)

    return plate


def parse_blur_width(condition: dict, degradations: dict) -> int:
    """条件や劣化設定から水平ブラーのピクセル幅を抽出する。無効な場合は0。"""
    # 1. condition.target_blur_width
    tbw = condition.get("target_blur_width")
    if tbw is not None:
        try:
            val = int(tbw)
            if val > 0:
                return val
        except (ValueError, TypeError):
            pass

    # 2. condition.blur: "motion7", "motion15", "motion25"
    blur_str = str(condition.get("blur", ""))
    match = re.search(r"motion(\d+)", blur_str, re.IGNORECASE)
    if match:
        return int(match.group(1))

    # 3. degradations 内の blur
    if "blur" in degradations:
        d_blur = degradations["blur"]
        if isinstance(d_blur, dict):
            val = d_blur.get("target_blur_width") or d_blur.get("width") or d_blur.get("px")
            if val is not None:
                try:
                    return int(val)
                except (ValueError, TypeError):
                    pass

    return 0


def apply_qr_degradations(
    plate_bgr: np.ndarray,
    condition: dict,
    degradations: dict,
    seed: int = 1000,
) -> tuple[np.ndarray, list[str]]:
    """QR板に条件に応じた劣化を適用し、適用された劣化名称のリストを返す。"""
    out_bgr = plate_bgr.copy()
    applied: list[str] = []

    # 1. ブレ（水平モーションブラー）
    blur_px = parse_blur_width(condition, degradations)
    if blur_px > 1:
        kernel = np.ones((1, blur_px), dtype=np.float32) / float(blur_px)
        out_bgr = cv2.filter2D(out_bgr, -1, kernel)
        applied.append(f"motion_blur_{blur_px}px")

    # 2. JPEG圧縮
    if "jpeg_compression" in degradations:
        deg_info = degradations["jpeg_compression"]
        s = float(deg_info.get("strength", 0.5)) if isinstance(deg_info, dict) else 0.5
        quality = max(5, int(round(100.0 - s * 90.0)))
        _, enc = cv2.imencode(".jpg", out_bgr, [cv2.IMWRITE_JPEG_QUALITY, quality])
        if enc is not None:
            decoded = cv2.imdecode(enc, cv2.IMREAD_COLOR)
            if decoded is not None:
                out_bgr = decoded
                applied.append("jpeg_compression")

    # 3. センサーノイズ
    if "sensor_noise" in degradations:
        deg_info = degradations["sensor_noise"]
        s = float(deg_info.get("strength", 0.5)) if isinstance(deg_info, dict) else 0.5
        noise_seed = int(deg_info.get("seed", seed)) if isinstance(deg_info, dict) else seed
        rng = np.random.RandomState(noise_seed ^ 502)
        amp = 10.0 + 66.0 * s
        noise = rng.uniform(-amp / 2.0, amp / 2.0, out_bgr.shape)
        out_bgr = np.clip(out_bgr.astype(np.float32) + noise, 0, 255).astype(np.uint8)
        applied.append("sensor_noise")

    # 4. 遠景化（small_in_frame: カメラ後退による板の縮小）
    if "small_in_frame" in degradations:
        deg_info = degradations["small_in_frame"]
        s = float(deg_info.get("strength", 0.5)) if isinstance(deg_info, dict) else 0.5
        # meter3d.html のカメラ距離計算: 5.6 + s * 7.5
        scale = 5.6 / (5.6 + s * 7.5)
        new_w = max(24, int(round(out_bgr.shape[1] * scale)))
        new_h = max(24, int(round(out_bgr.shape[0] * scale)))
        out_bgr = cv2.resize(out_bgr, (new_w, new_h), interpolation=cv2.INTER_AREA)
        applied.append("small_in_frame")

    # 5. 色かぶり (color_cast)
    if "color_cast" in degradations:
        deg_info = degradations["color_cast"]
        s = float(deg_info.get("strength", 0.5)) if isinstance(deg_info, dict) else 0.5
        c_seed = int(deg_info.get("seed", seed)) if isinstance(deg_info, dict) else seed
        # meter3d.html のカラーキャスト近似
        overlay = out_bgr.astype(np.float32)
        if c_seed % 2 == 0:
            tint = np.array([145, 235, 110], dtype=np.float32)  # 緑
            alpha = 0.14 + 0.24 * s
        else:
            tint = np.array([65, 165, 255], dtype=np.float32)   # 橙
            alpha = 0.16 + 0.26 * s
        blended = overlay * (1.0 - alpha) + tint * alpha
        out_bgr = np.clip(blended, 0, 255).astype(np.uint8)
        applied.append("color_cast")

    return out_bgr, applied


def embed_plate_in_image(
    image_bgr: np.ndarray,
    plate_bgr: np.ndarray,
    yaw_deg: float = 0.0,
    pitch_deg: float = 0.0,
    margin: int = DEFAULT_MARGIN,
    focal_length: float = 1320.0,
) -> tuple[np.ndarray, list[int], list[str]]:
    """QR板を画像の右下に透視変換（または正対貼付）して合成する。

    Returns:
        (合成後画像, bbox [x, y, w, h], 追加劣化リスト)
    """
    img_h, img_w = image_bgr.shape[:2]
    plate_h, plate_w = plate_bgr.shape[:2]
    extra_degraded: list[str] = []

    has_tilt = (abs(yaw_deg) > 0.01) or (abs(pitch_deg) > 0.01)

    if not has_tilt:
        # 正対配置（右下から margin px の余白）
        x2 = img_w - margin
        x1 = max(0, x2 - plate_w)
        y2 = img_h - margin
        y1 = max(0, y2 - plate_h)
        actual_w = x2 - x1
        actual_h = y2 - y1

        out = image_bgr.copy()
        out[y1:y2, x1:x2] = plate_bgr[:actual_h, :actual_w]
        bbox = [x1, y1, actual_w, actual_h]
        return out, bbox, extra_degraded

    # 斜め配置: 3D透視投影による射影変換 (cv2.warpPerspective)
    yaw = math.radians(yaw_deg)
    pitch = math.radians(pitch_deg)

    src_pts = np.array([
        [0.0, 0.0],
        [float(plate_w), 0.0],
        [float(plate_w), float(plate_h)],
        [0.0, float(plate_h)],
    ], dtype=np.float32)

    corners = np.array([
        [-plate_w / 2.0, -plate_h / 2.0, 0.0],
        [ plate_w / 2.0, -plate_h / 2.0, 0.0],
        [ plate_w / 2.0,  plate_h / 2.0, 0.0],
        [-plate_w / 2.0,  plate_h / 2.0, 0.0],
    ], dtype=np.float32)

    Ry = np.array([
        [math.cos(yaw), 0.0, math.sin(yaw)],
        [0.0, 1.0, 0.0],
        [-math.sin(yaw), 0.0, math.cos(yaw)],
    ], dtype=np.float32)
    Rx = np.array([
        [1.0, 0.0, 0.0],
        [0.0, math.cos(pitch), -math.sin(pitch)],
        [0.0, math.sin(pitch), math.cos(pitch)],
    ], dtype=np.float32)

    R = Rx @ Ry
    rot = corners @ R.T

    f = float(focal_length)
    proj = []
    for pt in rot:
        z = pt[2]
        factor = f / (f + z)
        proj.append([pt[0] * factor, pt[1] * factor])
    proj_np = np.array(proj, dtype=np.float32)

    # 右下隅 (img_w - margin, img_h - margin) に収まるよう平行移動
    shift_x = float(img_w - margin) - float(proj_np[:, 0].max())
    shift_y = float(img_h - margin) - float(proj_np[:, 1].max())
    dst_pts = proj_np + np.array([shift_x, shift_y], dtype=np.float32)

    M = cv2.getPerspectiveTransform(src_pts, dst_pts)
    warped_plate = cv2.warpPerspective(
        plate_bgr,
        M,
        (img_w, img_h),
        flags=cv2.INTER_LINEAR,
        borderMode=cv2.BORDER_CONSTANT,
        borderValue=(255, 255, 255),
    )
    mask = np.ones((plate_h, plate_w), dtype=np.uint8) * 255
    warped_mask = cv2.warpPerspective(
        mask,
        M,
        (img_w, img_h),
        flags=cv2.INTER_LINEAR,
        borderMode=cv2.BORDER_CONSTANT,
        borderValue=0,
    )

    out = image_bgr.copy()
    mask_bool = warped_mask > 128
    out[mask_bool] = warped_plate[mask_bool]

    min_x = max(0, int(math.floor(dst_pts[:, 0].min())))
    min_y = max(0, int(math.floor(dst_pts[:, 1].min())))
    max_x = min(img_w, int(math.ceil(dst_pts[:, 0].max())))
    max_y = min(img_h, int(math.ceil(dst_pts[:, 1].max())))
    bbox = [min_x, min_y, max_x - min_x, max_y - min_y]

    extra_degraded.append(f"perspective_yaw{int(round(yaw_deg))}_pitch{int(round(pitch_deg))}")
    return out, bbox, extra_degraded


def calculate_captured_at(
    device_id: str,
    image_index: int,
    base_time: Optional[datetime] = None,
) -> str:
    """決定的 captured_at のタイムスタンプ（JST）を生成する。

    規則:
    - 機器ごとに画像をファイル名昇順でソート
    - 開始: 2026-10-01T09:00:00+09:00
    - 機器番号 × 3分 だけ開始をずらす
    - 画像ごとに1日進める
    """
    if base_time is None:
        jst = timezone(timedelta(hours=9))
        base_time = datetime(2026, 10, 1, 9, 0, 0, tzinfo=jst)

    dev_num = extract_device_number(device_id)
    dt = base_time + timedelta(minutes=dev_num * 3) + timedelta(days=image_index)
    return dt.isoformat()


def build_sidecar_with_device(
    local_id: str,
    captured_at: str,
    device_id: str,
    device_name: str,
) -> dict[str, Any]:
    """「取り込み用_サイドカーに機器あり」向けS1サイドカーJSON辞書。"""
    return {
        "local_id": local_id,
        "captured_at": captured_at,
        "device_id": device_id,
        "device_name": device_name,
    }


def build_sidecar_qr_only(
    local_id: str,
    captured_at: str,
) -> dict[str, Any]:
    """「取り込み用_QRのみ」向けS1サイドカーJSON辞書。"""
    return {
        "local_id": local_id,
        "captured_at": captured_at,
    }


def evaluate_qr_read_rates(
    items_to_eval: Sequence[Tuple[str, str, str, np.ndarray]],
) -> Tuple[Dict[str, Dict[str, Any]], List[Dict[str, str]]]:
    """全合成画像のQRコード読み取り率を集計する。

    Parameters:
        items_to_eval: (ファイル名, 条件, 想定device_id, BGR画像配列) のリスト

    Returns:
        (条件別集計辞書, 失敗画像一覧)
    """
    detector = cv2.QRCodeDetector()
    stats: dict[str, dict[str, int]] = {}
    failures: list[dict[str, str]] = []

    for name, condition, expected_id, img in items_to_eval:
        if condition not in stats:
            stats[condition] = {"total": 0, "success": 0}
        stats[condition]["total"] += 1

        try:
            decoded_info, _, _ = detector.detectAndDecode(img)
        except (cv2.error, Exception):
            decoded_info = ""
        parsed = parse_payload(decoded_info) if decoded_info else None

        if parsed and parsed.get("id") == expected_id:
            stats[condition]["success"] += 1
        else:
            reason = "unreadable" if not decoded_info else (
                f"id_mismatch (got {parsed.get('id') if parsed else 'invalid_payload'})"
            )
            failures.append({
                "file": name,
                "condition": condition,
                "expected_id": expected_id,
                "reason": reason,
            })

    # 全体集計を追加
    total_all = sum(s["total"] for s in stats.values())
    succ_all = sum(s["success"] for s in stats.values())
    stats["全体"] = {"total": total_all, "success": succ_all}

    # 読み取り率（%）を計算
    result: dict[str, dict[str, Any]] = {}
    ordered_keys = [c for c in CONDITIONS_ORDER if c in stats] + [k for k in stats if k not in CONDITIONS_ORDER and k != "全体"] + ["全体"]
    for k in ordered_keys:
        tot = stats[k]["total"]
        suc = stats[k]["success"]
        rate = (suc / tot * 100.0) if tot > 0 else 0.0
        result[k] = {
            "total": tot,
            "success": suc,
            "rate_pct": rate,
        }

    return result, failures


def generate_read_rate_markdown(
    stats: Dict[str, Dict[str, Any]],
    failures: List[Dict[str, str]],
) -> str:
    """QR読み取り率レポートのMarkdown文字列を生成する。"""
    lines = [
        "# 3D合成画像 QRコード読み取り率集計レポート",
        "",
        "## 概要",
        "OpenCV `cv2.QRCodeDetector` を用い、QR板を合成した全画像から機器QRのペイロードを読み取り、`device_id` が正解と一致した割合を集計しました。",
        "",
        "## 条件別読み取り率",
        "",
        "| 条件 | 総枚数 | 読み取り成功 | 読み取り率 (%) | 備考 |",
        "|---|---:|---:|---:|---|",
    ]

    for cond, row in stats.items():
        tot = row["total"]
        suc = row["success"]
        pct = row["rate_pct"]
        note = ""
        if cond == "正面":
            note = "劣化なし。基準読み取り性能"
        elif cond == "ブレ":
            note = "水平モーションブラー（7, 15, 25px）による検出難化"
        elif cond == "斜め":
            note = "視点傾き（yaw 15°〜60°, pitch 25°）の射影変形"
        elif cond in ("反射", "汚れ", "紛らわしい文字"):
            note = "QR板は影響外のため劣化なし"
        elif cond == "背景と画質":
            note = "JPEG圧縮・ノイズ・遠景化等による影響"
        elif cond == "全体":
            note = "**総合検出率**"

        lines.append(f"| {cond} | {tot} | {suc} | {pct:.1f}% | {note} |")

    lines.append("")
    lines.append(f"## 読み取り失敗画像一覧（全 {len(failures)} 件）")
    lines.append("")
    if not failures:
        lines.append("読み取りに失敗した画像はありません。")
    else:
        lines.append("| ファイル名 | 条件 | 想定機器ID | 失敗理由 |")
        lines.append("|---|---|---|---|")
        for f in failures:
            lines.append(f"| `{f['file']}` | {f['condition']} | {f['expected_id']} | {f['reason']} |")

    lines.append("")
    return "\n".join(lines)


def generate_readme_markdown(
    out_dir: str | Path,
    total_images: int,
) -> str:
    """データセットのREADME.mdを生成する。"""
    return f"""# 3D合成画像 QR機器ラベル付きテストデータセット（2026-10-30）

## 概要
本データセットは、3D合成メーター画像（`C:\\卒研\\合成画像\\テスト用_20261021`、全294枚）の右下に現場のQR機器ラベル板を合成し、PC取り込み処理（QRからの機器ID抽出およびDB投入試験）を検証するために作成されたテストデータセットです。

- **総画像数**: {total_images} 枚（1280×960 px、PNG形式）
- **出力ルート**: `{out_dir}`
- **QR板仕様**: 一辺200pxの白板、誤り訂正水準M、余白4モジュール、下部に機器ID文字を表記

## 貼る位置と設計
- **配置位置**: 画像の右下隅（右および下から余白24px）
- **メーター非重複性の保証**:
  - メーター中心は (640, 480)、メーター半径は約380px、影を含めても半径約450px
  - 貼付領域の最もメーターに近い左上隅座標は (1056, 736) 付近
  - 中心からの最短距離は約 488px（> 450px）であり、メーターや影には一切重複せず、画像枠外にもはみ出しません。

## 条件に応じた劣化近似方針と限界
実際の現場環境を模すため、各画像に付与されていた条件・劣化をQR板にのみ局所適用しています。

| 条件区分 | QR板への適用方法 | 近似方針と技術的限界 |
|---|---|---|
| **正面** | 劣化なし | クリーンな正対ラベル。100%読み取り可能な基準状態。 |
| **ブレ** | 水平モーションブラー | 画像の `target_blur_width`（7, 15, 25px）と同一幅の水平正規化カーネルでブラーを適用。手ブレによるQRパターンの横方向の滲みを忠実に再現。 |
| **斜め** | 透視投影変換 (`cv2.warpPerspective`) | カメラの `camera_yaw`（15°, 30°, 45°, 60°）および `camera_pitch`（25°）と同じ角度で空間回転させ、右下枠内に収まるよう射影。急角度（60°）ではQR検出器の復号限界を再現。 |
| **画質（背景と画質）** | 該当処理のみ適用 | - `jpeg_compression`: 指定強度に応じたJPEG再圧縮（ブロックノイズ・高周波消失）<br>- `sensor_noise`: 擬似乱数シードに基づくセンサーノイズ重畳<br>- `small_in_frame`: カメラ後退に伴う板サイズの縮小（遠景化）<br>- `color_cast`: 照明の色かぶりオーバーレイ |
| **反射・汚れ・文字・背景** | **未対応（何もしない）** | - 反射（グレア）: カバーガラス表面の光反射であり、外付けQR板表面の反射とは幾何条件が異なるため対象外。<br>- 汚れ・傷・水滴: メーター盤面・ガラスの経年劣化であり、新規貼付ラベルには適用不可。<br>- 紛らわしい文字: 文字盤内の誤読誘発文字のためラベルには影響なし。<br>- 雑多背景・メーター一部切れ・一部遮蔽: メーター本体の切り出し・遮蔽条件であり、右下隅のQR板の遮蔽幾何が未定義のため未対応。 |

## フォルダ構成
```text
<out>/
  ├── 画像/
  │    ├── 正面/              # QR合成画像（条件別）
  │    ├── 斜め/
  │    ├── 反射/
  │    ├── ブレ/
  │    ├── 汚れ/
  │    ├── 紛らわしい文字/
  │    └── 背景と画質/
  ├── 正解_QR付き.json        # 元の正解JSONに qr (bbox, degraded, payload) を追加
  ├── 取り込み用_サイドカーに機器あり/
  │    ├── *.png             # 平らな全画像コピー
  │    └── *.json            # S1サイドカー（local_id, captured_at, device_id, device_name）
  ├── 取り込み用_QRのみ/
  │    ├── *.png             # 平らな全画像コピー
  │    └── *.json            # S1サイドカー（local_id, captured_at のみ）
  ├── QR読み取り率.md         # 条件別検出率および不一致一覧レポート
  └── README.md              # 本ドキュメント
```

## 使い方
### 1. PC側QR自動読み取り試験
`取り込み用_QRのみ` フォルダをPC取り込みツールに投入し、画像からQRコードが自動検出されて機器IDが正しくDBに登録されるかテストします。

### 2. スマホ入力・サイドカー優先試験
`取り込み用_サイドカーに機器あり` フォルダを投入し、サイドカー記載の機器IDが優先してDBに登録されるかを検証します。
"""


def process_dataset(
    input_dir: Path,
    output_dir: Path,
    limit: Optional[int] = None,
    dry_run: bool = False,
) -> int:
    """データセット全体を処理してQR付き画像・正解JSON・取り込み用フォルダ・レポートを生成する。"""
    input_dir = Path(input_dir).resolve()
    output_dir = Path(output_dir).resolve()

    gt_path = input_dir / "groundtruth_synthetic.json"
    if not gt_path.is_file():
        raise FileNotFoundError(f"groundtruth_synthetic.json not found in {input_dir}")

    with open(gt_path, "r", encoding="utf-8") as f:
        groundtruth_entries: list[dict[str, Any]] = json.load(f)

    if limit is not None and limit > 0:
        groundtruth_entries = groundtruth_entries[:limit]

    print(f"Loaded {len(groundtruth_entries)} entries from {gt_path}")
    if dry_run:
        print("[DRY-RUN] No files will be written.")

    # 1. 機器IDごとに画像を名前昇順でグループ化して captured_at を割り当てる準備
    device_groups: dict[str, list[dict[str, Any]]] = {}
    for entry in groundtruth_entries:
        dev_id = entry.get("device_id", "SYN-001")
        device_groups.setdefault(dev_id, []).append(entry)

    # 機器内でのファイル名ソートと captured_at の算出
    entry_captured_at: dict[str, str] = {}
    for dev_id, entries in device_groups.items():
        # ファイル名（basename）昇順でソート
        entries.sort(key=lambda e: os.path.basename(e.get("image", "")))
        for idx, entry in enumerate(entries):
            img_rel_or_abs = entry.get("image", "")
            img_name = os.path.basename(img_rel_or_abs)
            c_at = calculate_captured_at(dev_id, idx)
            entry_captured_at[img_name] = c_at

    # 2. 出力フォルダ準備
    img_out_root = output_dir / "画像"
    with_device_dir = output_dir / "取り込み用_サイドカーに機器あり"
    qr_only_dir = output_dir / "取り込み用_QRのみ"

    if not dry_run:
        img_out_root.mkdir(parents=True, exist_ok=True)
        with_device_dir.mkdir(parents=True, exist_ok=True)
        qr_only_dir.mkdir(parents=True, exist_ok=True)

    new_groundtruth_entries: list[dict[str, Any]] = []
    items_to_eval: list[tuple[str, str, str, np.ndarray]] = []

    # 3. 各画像を順次処理
    processed_count = 0
    for entry in groundtruth_entries:
        orig_img_path_str = entry.get("image", "")
        # 相対パスまたは絶対パスに対応
        if os.path.isabs(orig_img_path_str):
            orig_img_path = Path(orig_img_path_str)
        else:
            orig_img_path = input_dir / orig_img_path_str

        if not orig_img_path.is_file():
            # 条件フォルダ配下から探索
            category = entry.get("category", "")
            alt_path = input_dir / category / orig_img_path.name
            if alt_path.is_file():
                orig_img_path = alt_path
            else:
                raise FileNotFoundError(f"Image not found: {orig_img_path}")

        img_bgr = load_image_unicode_safe(orig_img_path)
        img_name = orig_img_path.name
        img_stem = orig_img_path.stem
        category = entry.get("category", "")

        device_id = str(entry.get("device_id", "SYN-001"))
        device_name = str(entry.get("device_name", "合成メーター"))
        condition = entry.get("condition", {})
        degradations = entry.get("degradations", {})

        # A. QR板生成
        plate_pil = create_qr_plate(device_id, device_name)
        plate_bgr = cv2.cvtColor(np.array(plate_pil), cv2.COLOR_RGB2BGR)

        # B. 劣化適用
        seed = int(condition.get("seed", 1000 + processed_count))
        degraded_plate, applied_degs = apply_qr_degradations(
            plate_bgr, condition, degradations, seed=seed
        )

        # C. 画像への合成
        yaw = float(condition.get("camera_yaw", 0.0))
        pitch = float(condition.get("camera_pitch", 0.0))
        composite_bgr, bbox, extra_degs = embed_plate_in_image(
            img_bgr, degraded_plate, yaw_deg=yaw, pitch_deg=pitch
        )
        total_degraded = applied_degs + extra_degs

        # D. 保存
        dest_category_img_path = img_out_root / category / img_name
        dest_with_dev_img_path = with_device_dir / img_name
        dest_qr_only_img_path = qr_only_dir / img_name

        captured_at = entry_captured_at.get(img_name, calculate_captured_at(device_id, 0))

        if not dry_run:
            # 1. 画像保存
            save_image_unicode_safe(dest_category_img_path, composite_bgr)
            save_image_unicode_safe(dest_with_dev_img_path, composite_bgr)
            save_image_unicode_safe(dest_qr_only_img_path, composite_bgr)

            # 2. サイドカーJSON保存
            local_id = img_stem
            sidecar_with_dev = build_sidecar_with_device(
                local_id=local_id,
                captured_at=captured_at,
                device_id=device_id,
                device_name=device_name,
            )
            sidecar_qr_only = build_sidecar_qr_only(
                local_id=local_id,
                captured_at=captured_at,
            )

            sidecar_with_dev_path = with_device_dir / f"{img_stem}.json"
            sidecar_qr_only_path = qr_only_dir / f"{img_stem}.json"

            with open(sidecar_with_dev_path, "w", encoding="utf-8") as sf1:
                json.dump(sidecar_with_dev, sf1, indent=2, ensure_ascii=False)
            with open(sidecar_qr_only_path, "w", encoding="utf-8") as sf2:
                json.dump(sidecar_qr_only, sf2, indent=2, ensure_ascii=False)

        # E. 正解エントリの作成
        payload_str = build_payload(device_id, device_name)
        new_entry = dict(entry)
        new_entry["image"] = str(dest_category_img_path).replace("\\", "/")
        new_entry["qr"] = {
            "bbox": bbox,
            "degraded": total_degraded,
            "payload": payload_str,
        }
        new_groundtruth_entries.append(new_entry)

        # 評価用アイテム
        items_to_eval.append((img_name, category, device_id, composite_bgr))
        processed_count += 1

    # 4. 正解_QR付き.json の書き出し
    gt_out_path = output_dir / "正解_QR付き.json"
    if not dry_run:
        with open(gt_out_path, "w", encoding="utf-8") as gtf:
            json.dump(new_groundtruth_entries, gtf, indent=2, ensure_ascii=False)
        print(f"Wrote {len(new_groundtruth_entries)} entries to {gt_out_path}")

    # 5. QR読み取り率集計 & レポート出力
    print("Evaluating QR read rates with cv2.QRCodeDetector...")
    stats, failures = evaluate_qr_read_rates(items_to_eval)

    report_md = generate_read_rate_markdown(stats, failures)
    report_path = output_dir / "QR読み取り率.md"
    if not dry_run:
        with open(report_path, "w", encoding="utf-8") as rf:
            rf.write(report_md)
        print(f"Wrote read rate report to {report_path}")

    # 6. README.md の書き出し
    readme_md = generate_readme_markdown(output_dir, len(new_groundtruth_entries))
    readme_path = output_dir / "README.md"
    if not dry_run:
        with open(readme_path, "w", encoding="utf-8") as rmf:
            rmf.write(readme_md)
        print(f"Wrote README documentation to {readme_path}")

    print("\n--- QR READ RATE SUMMARY ---")
    for cond, row in stats.items():
        print(f"  {cond:10s}: {row['success']:3d} / {row['total']:3d} ({row['rate_pct']:.1f}%)")
    print(f"Total failures: {len(failures)}")

    return 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="3D合成画像にQR板を合成し、取り込み用フォルダと正解データを生成するツール"
    )
    parser.add_argument(
        "--in", "--input", dest="input_dir",
        default=DEFAULT_INPUT_DIR,
        help=f"入力合成画像ルートディレクトリ (既定: {DEFAULT_INPUT_DIR})",
    )
    parser.add_argument(
        "--out", "--output", dest="output_dir",
        default=DEFAULT_OUTPUT_DIR,
        help=f"出力ディレクトリ (既定: {DEFAULT_OUTPUT_DIR})",
    )
    parser.add_argument(
        "--limit", type=int, default=None,
        help="処理する画像枚数の上限（先頭N枚）",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="ファイル書き込みを行わずに処理内容を検証する",
    )
    args = parser.parse_args(argv)

    try:
        return process_dataset(
            input_dir=Path(args.input_dir),
            output_dir=Path(args.output_dir),
            limit=args.limit,
            dry_run=args.dry_run,
        )
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
