"""QR機器ラベルのペイロード生成・検証およびラベルシートPDFの作成モジュール。

仕様: tasks/design/QR機器ラベル仕様.md
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Sequence
import unicodedata

from PIL import Image, ImageDraw, ImageFont
import qrcode
import qrcode.constants

# 定数（300 DPI, A4縦）
PAGE_WIDTH = 2480
PAGE_HEIGHT = 3508
COLS = 2
ROWS = 5
LABELS_PER_PAGE = COLS * ROWS

# マージンとセルサイズ
MARGIN_X = 140
MARGIN_Y = 164
CELL_WIDTH = (PAGE_WIDTH - 2 * MARGIN_X) // COLS   # 1100 px
CELL_HEIGHT = (PAGE_HEIGHT - 2 * MARGIN_Y) // ROWS  # 636 px

# QRサイズ（約25mm角 @ 300DPI）
QR_PIXEL_SIZE = 295


def build_payload(
    name: str,
    unit: str | None = None,
    min: float | int | None = None,
    max: float | int | None = None,
) -> str:
    """機器ラベル用のQRペイロードJSON文字列を生成する。

    Parameters
    ----------
    name : str
        機器名（1〜64文字、前後の空白は除外される）。
    unit : str | None, optional
        単位（例: "MPa"）。
    min : float | int | None, optional
        目盛り最小値（数値）。
    max : float | int | None, optional
        目盛り最大値（数値）。

    Returns
    -------
    str
        JSON文字列（キー順: v, name, unit, min, max。区切り: (",", ":")）。

    Raises
    ------
    ValueError
        nameが文字列でない、空文字、65文字以上、または制御文字・改行を含む場合。
    """
    if not isinstance(name, str):
        raise ValueError("機器名は文字列である必要があります")

    # 制御文字・改行の検査（strip 前に判定し、改行等の混入を防ぐ）
    if any(unicodedata.category(c).startswith("C") for c in name):
        raise ValueError("機器名に制御文字や改行を含めることはできません")

    stripped_name = name.strip()
    if not stripped_name:
        raise ValueError("機器名が空です")

    if len(stripped_name) >= 65:
        raise ValueError(f"機器名が長すぎます（{len(stripped_name)}文字。上限64文字）")

    payload: dict = {"v": 1, "name": stripped_name}

    if unit is not None:
        if not isinstance(unit, str):
            raise ValueError("unitは文字列である必要があります")
        payload["unit"] = unit

    if min is not None:
        if not isinstance(min, (int, float)) or isinstance(min, bool):
            raise ValueError("minは数値である必要があります")
        payload["min"] = min

    if max is not None:
        if not isinstance(max, (int, float)) or isinstance(max, bool):
            raise ValueError("maxは数値である必要があります")
        payload["max"] = max

    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def parse_payload(text: str) -> dict | None:
    """QRコードから読み取った文字列を機器ラベル仕様に従って検証・パースする。

    Parameters
    ----------
    text : str
        QRコードの内容。

    Returns
    -------
    dict | None
        検証に成功した場合は {"name": ..., "unit": ..., "min": ..., "max": ...}
        （存在しないキーは含まない）。機器QRでない場合は None。例外は発生させない。
    """
    if not isinstance(text, str):
        return None

    try:
        data = json.loads(text)
    except Exception:
        return None

    if not isinstance(data, dict):
        return None

    # v の検証（必須、1）
    v = data.get("v")
    if v != 1 or isinstance(v, bool):
        return None

    # name の検証（必須、文字列、前後の空白を除き1〜64文字、制御文字不可）
    name = data.get("name")
    if not isinstance(name, str):
        return None

    # 制御文字・改行の検査
    if any(unicodedata.category(c).startswith("C") for c in name):
        return None

    stripped_name = name.strip()
    if not stripped_name or len(stripped_name) >= 65:
        return None

    result: dict = {"name": stripped_name}

    # unit の検証（任意、文字列）
    if "unit" in data and isinstance(data["unit"], str):
        result["unit"] = data["unit"]

    # min, max の検証（任意、数値）
    if "min" in data and isinstance(data["min"], (int, float)) and not isinstance(data["min"], bool):
        result["min"] = data["min"]

    if "max" in data and isinstance(data["max"], (int, float)) and not isinstance(data["max"], bool):
        result["max"] = data["max"]

    return result


def find_japanese_font(size: int = 40) -> ImageFont.FreeTypeFont:
    """Windows環境の日本語フォントを探して読み込む。

    探索順: meiryo.ttc -> YuGothM.ttc -> msgothic.ttc
    """
    candidate_paths = [
        r"C:\Windows\Fonts\meiryo.ttc",
        r"C:\Windows\Fonts\YuGothM.ttc",
        r"C:\Windows\Fonts\msgothic.ttc",
    ]
    for font_path in candidate_paths:
        if os.path.exists(font_path):
            try:
                return ImageFont.truetype(font_path, size)
            except Exception:
                continue

    raise FileNotFoundError(
        "日本語フォントが見つかりません。C:\\Windows\\Fonts\\ に meiryo.ttc, YuGothM.ttc, msgothic.ttc のいずれかが必要です。"
    )


def create_label_image(
    name: str,
    font: ImageFont.FreeTypeFont | None = None,
    width: int = CELL_WIDTH,
    height: int = CELL_HEIGHT,
) -> Image.Image:
    """単一ラベルの画像を生成する（QRコード + 日本語機器名）。

    Parameters
    ----------
    name : str
        機器名。
    font : ImageFont.FreeTypeFont | None, optional
        描画に使用するフォント。Noneの場合は自動取得。
    width : int
        ラベル幅（px）。
    height : int
        ラベル高（px）。

    Returns
    -------
    Image.Image
        ラベル画像（RGB）。
    """
    if font is None:
        font = find_japanese_font(size=40)

    # 白背景のラベル基底
    img = Image.new("RGB", (width, height), (255, 255, 255))
    draw = ImageDraw.Draw(img)

    # 1. QRコードの生成
    payload = build_payload(name)
    qr = qrcode.QRCode(
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=10,
        border=4,
    )
    qr.add_data(payload)
    qr.make(fit=True)
    qr_img = qr.make_image(fill_color="black", back_color="white").convert("RGB")
    qr_img = qr_img.resize((QR_PIXEL_SIZE, QR_PIXEL_SIZE), Image.Resampling.NEAREST)

    # QR貼り付け位置（上部中央）
    qr_x = (width - QR_PIXEL_SIZE) // 2
    qr_y = 50
    img.paste(qr_img, (qr_x, qr_y))

    # 2. 機器名の描画（QRの下、中央揃え、折り返し対応）
    max_text_width = width - 80
    lines: list[str] = []
    current_line = ""

    display_name = name.strip()
    for ch in display_name:
        test_line = current_line + ch
        bbox = font.getbbox(test_line)
        line_w = bbox[2] - bbox[0]
        if line_w > max_text_width and current_line:
            lines.append(current_line)
            current_line = ch
        else:
            current_line = test_line
    if current_line:
        lines.append(current_line)

    text_top_y = qr_y + QR_PIXEL_SIZE + 30
    line_height = int(getattr(font, "size", 40) * 1.35)

    for idx, line in enumerate(lines):
        line_bbox = font.getbbox(line)
        line_w = line_bbox[2] - line_bbox[0]
        tx = (width - line_w) // 2
        ty = text_top_y + idx * line_height
        draw.text((tx, ty), line, fill="black", font=font)

    return img


def make_label_sheet(names: Sequence[str], out_path: str | Path) -> None:
    """A4縦・2列×5行のラベルシートPDFを生成して保存する。

    Parameters
    ----------
    names : Sequence[str]
        機器名の一覧。
    out_path : str | Path
        出力PDFのファイルパス。
    """
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    font = find_japanese_font(size=40)

    # 10台ごとにページ分割
    chunks = [list(names[i : i + LABELS_PER_PAGE]) for i in range(0, len(names), LABELS_PER_PAGE)]
    if not chunks:
        chunks = [[]]

    pages: list[Image.Image] = []

    for chunk in chunks:
        page_img = Image.new("RGB", (PAGE_WIDTH, PAGE_HEIGHT), (255, 255, 255))
        draw = ImageDraw.Draw(page_img)

        # 2列×5行のグリッドを描画
        for row in range(ROWS):
            for col in range(COLS):
                cell_x = MARGIN_X + col * CELL_WIDTH
                cell_y = MARGIN_Y + row * CELL_HEIGHT

                # セルの薄い外枠線（カット補助線）
                draw.rectangle(
                    [cell_x, cell_y, cell_x + CELL_WIDTH, cell_y + CELL_HEIGHT],
                    outline="#D8D8D8",
                    width=1,
                )

                idx = row * COLS + col
                if idx < len(chunk):
                    device_name = chunk[idx]
                    lbl_img = create_label_image(
                        device_name,
                        font=font,
                        width=CELL_WIDTH,
                        height=CELL_HEIGHT,
                    )
                    page_img.paste(lbl_img, (cell_x, cell_y))

        pages.append(page_img)

    # Pillow で PDF として保存
    pages[0].save(
        out_path,
        "PDF",
        resolution=300,
        save_all=True,
        append_images=pages[1:],
    )
