"""
アナログメーター目盛り数字 OCR 検出モジュール
EasyOCR を使用して目盛りの数字と座標を高精度に検出します

スタンドアロン実行:
    python OCR_Test.py               # ファイルダイアログで画像選択
    python OCR_Test.py meter.jpg     # パスを直接指定

別ファイルからのインポート:
    from OCR_Test import detect_meter_numbers
    detected, min_val, max_val = detect_meter_numbers("meter.jpg")
"""

import cv2
import numpy as np
import easyocr
import math
import sys
from pathlib import Path

# EasyOCR Reader のプロセス内キャッシュ（初期化コストが高いため）
_reader = None


def _get_reader(gpu=None):
    global _reader
    if _reader is None:
        if gpu is None:
            try:
                import torch
                gpu = torch.cuda.is_available()
            except ImportError:
                gpu = False
        label = "GPU" if gpu else "CPU"
        print(f"EasyOCR モデルを初期化中... ({label} モード、初回のみ時間がかかります)")
        _reader = easyocr.Reader(['en'], gpu=gpu)
    return _reader


def _make_variants(img):
    """認識率を上げるための複数前処理バリエーションを生成する"""
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if img.ndim == 3 else img.copy()

    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    _, otsu = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    adaptive = cv2.adaptiveThreshold(
        gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 11, 2
    )

    return [
        gray,                        # グレースケール原画
        clahe.apply(gray),           # CLAHE コントラスト強調
        otsu,                        # 大津二値化（黒文字）
        cv2.bitwise_not(otsu),       # 大津二値化（白文字対応）
        adaptive,                    # 適応的二値化
    ]


def _bbox_center(bbox):
    pts = np.array(bbox, dtype=np.float32)
    return int(pts[:, 0].mean()), int(pts[:, 1].mean())


def _dedup(items, dist=25):
    """同値・近接の検出結果を統合し、信頼度最大のものを残す"""
    items = sorted(items, key=lambda d: d['confidence'], reverse=True)
    used = [False] * len(items)
    out = []
    for i, a in enumerate(items):
        if used[i]:
            continue
        used[i] = True
        for j in range(i + 1, len(items)):
            if not used[j]:
                b = items[j]
                if (a['value'] == b['value'] and
                        math.hypot(a['x'] - b['x'], a['y'] - b['y']) < dist):
                    used[j] = True
        out.append(a)
    return out


def _order_points(pts):
    """4点を [TL, TR, BR, BL] の時計回りに並べ直す"""
    pts = np.array(pts, dtype=np.float32)
    rect = np.zeros((4, 2), dtype=np.float32)
    s = pts.sum(axis=1)
    rect[0] = pts[np.argmin(s)]    # TL: x+y が最小
    rect[2] = pts[np.argmax(s)]    # BR: x+y が最大
    diff = np.diff(pts, axis=1)
    rect[1] = pts[np.argmin(diff)] # TR: y-x が最小
    rect[3] = pts[np.argmax(diff)] # BL: y-x が最大
    return rect


def _four_point_transform(img, bbox, pad=4):
    """
    4頂点の透視変換で傾きを補正した矩形切り出し画像を返す。
    失敗した場合は None を返す。
    """
    pts = _order_points(bbox)
    tl, tr, br, bl = pts

    w = int(max(np.linalg.norm(br - bl), np.linalg.norm(tr - tl)))
    h = int(max(np.linalg.norm(tr - br), np.linalg.norm(tl - bl)))
    if w < 4 or h < 4:
        return None

    dst = np.array([[0, 0], [w - 1, 0], [w - 1, h - 1], [0, h - 1]], dtype=np.float32)
    M = cv2.getPerspectiveTransform(pts, dst)
    warped = cv2.warpPerspective(img, M, (w, h))

    # 周囲に余白を加えて OCR が認識しやすくする
    if pad > 0:
        warped = cv2.copyMakeBorder(warped, pad, pad, pad, pad, cv2.BORDER_REPLICATE)
    return warped


def _bbox_tilt_angle(bbox):
    """BBox の上辺（TL→TR）の傾き角を度で返す（水平 = 0°）"""
    tl = np.array(bbox[0], dtype=float)
    tr = np.array(bbox[1], dtype=float)
    return math.degrees(math.atan2(tr[1] - tl[1], tr[0] - tl[0]))


def detect_meter_numbers(image_source, gpu=None, conf_threshold=0.3, min_size=8,
                         tilt_threshold=10.0):
    """
    アナログメーター画像から目盛り数字をOCRで検出する。

    Parameters
    ----------
    image_source : str, Path, or np.ndarray
        画像ファイルパス、または OpenCV 形式の numpy 配列。
    gpu : bool
        True にするとGPUを使用（高速・高精度）。
    conf_threshold : float
        採用する最低信頼度（0〜1）。デフォルト 0.3。
    min_size : int
        無視する文字の最小ピクセルサイズ。デフォルト 8。
    tilt_threshold : float
        この角度（度）を超えた傾きの検出は透視変換でデスキュー後に再OCRする。
        デフォルト 10.0°。

    Returns
    -------
    detected : list of dict
        [{'value': float, 'x': int, 'y': int, 'bbox': list, 'confidence': float}]
        value  : 認識した数値
        x, y   : バウンディングボックスの中心座標（画像ピクセル）
        bbox   : [[x1,y1],[x2,y2],[x3,y3],[x4,y4]] の4頂点
        confidence : EasyOCR の信頼スコア（0〜1）
    min_value : float or None
        検出値の最小値（検出なしの場合 None）。
    max_value : float or None
        検出値の最大値（検出なしの場合 None）。
    """
    if isinstance(image_source, (str, Path)):
        img = cv2.imread(str(image_source))
        if img is None:
            raise FileNotFoundError(f"画像が見つかりません: {image_source}")
    else:
        img = np.asarray(image_source)

    reader = _get_reader(gpu)
    raw = []

    for variant in _make_variants(img):
        for bbox, text, conf in reader.readtext(
            variant,
            allowlist='0123456789.-',
            detail=1,
            paragraph=False,
            text_threshold=0.6,
            low_text=0.3,
            link_threshold=0.4,
            min_size=min_size,
            mag_ratio=1.5,
        ):
            # ── デスキュー処理 ──────────────────────────────────────────
            # 傾きが tilt_threshold を超えていたら透視変換で補正して再OCR
            tilt = abs(_bbox_tilt_angle(bbox))
            if tilt > tilt_threshold:
                crop = _four_point_transform(variant, bbox)
                if crop is not None:
                    deskewed = reader.readtext(
                        crop,
                        allowlist='0123456789.-',
                        detail=1,
                        paragraph=False,
                        text_threshold=0.5,
                        low_text=0.3,
                        min_size=5,
                    )
                    if deskewed:
                        best_d = max(deskewed, key=lambda x: x[2])
                        _, text_d, conf_d = best_d
                        # デスキュー後が有効な数値で信頼度が高ければ採用
                        try:
                            float(text_d)
                            if conf_d > conf:
                                text, conf = text_d, conf_d
                        except ValueError:
                            pass
            # ────────────────────────────────────────────────────────────

            if conf < conf_threshold:
                continue
            try:
                val = float(text)
            except ValueError:
                continue
            cx, cy = _bbox_center(bbox)
            raw.append({
                'value': val,
                'x': cx,
                'y': cy,
                'bbox': bbox,
                'confidence': conf,
            })

    detected = _dedup(raw)
    if not detected:
        return [], None, None

    vals = [d['value'] for d in detected]
    return detected, min(vals), max(vals)


def visualize_detections(image_source, detected):
    """検出結果をバウンディングボックス付きで描画した画像を返す"""
    if isinstance(image_source, (str, Path)):
        img = cv2.imread(str(image_source))
    else:
        img = np.asarray(image_source).copy()

    for d in detected:
        pts = np.array(d['bbox'], dtype=np.int32)
        cv2.polylines(img, [pts], isClosed=True, color=(0, 220, 0), thickness=2)
        label = f"{d['value']} ({d['confidence']:.2f})"
        cv2.putText(img, label, (d['x'], d['y'] - 6),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 60, 255), 2)
    return img


# ─────────────────────────── スタンドアロン実行 ───────────────────────────────
if __name__ == "__main__":
    import tkinter
    from tkinter import filedialog

    if len(sys.argv) > 1:
        path = sys.argv[1]
    else:
        root = tkinter.Tk()
        root.withdraw()
        path = filedialog.askopenfilename(
            title="メーター画像を選択",
            filetypes=[("画像ファイル", "*.png *.jpg *.jpeg *.bmp *.tif *.tiff")],
        )
        root.destroy()
        if not path:
            print("画像が選択されませんでした")
            sys.exit(0)

    print(f"\n画像: {path}")
    print("OCR 検出中...\n")

    detected, min_val, max_val = detect_meter_numbers(path)

    if detected:
        print(f"{'値':>10}  {'座標 (x,  y)':^16}  {'信頼度':>6}")
        print("─" * 42)
        for d in sorted(detected, key=lambda d: d['value']):
            print(f"{d['value']:>10.2f}  ({d['x']:>4}, {d['y']:>4})  {d['confidence']:>6.2f}")
        print(f"\n  最小値: {min_val}   最大値: {max_val}   検出数: {len(detected)}")
    else:
        print("数字を検出できませんでした。")

    result_img = visualize_detections(path, detected)

    # cv2.imshow は headless ビルドで動作しないため PIL で表示
    from PIL import Image
    pil_img = Image.fromarray(cv2.cvtColor(result_img, cv2.COLOR_BGR2RGB))
    pil_img.show()  # OS 標準の画像ビューアで開く
