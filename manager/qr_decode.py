"""画像から機器QRコードを読み取り、機器ID・表示名を判定するモジュール。

仕様: tasks/design/機器ID設計.md 6章, 9章(B3)
"""

from __future__ import annotations

from dataclasses import dataclass, field
import os
from pathlib import Path
from typing import Sequence, Union

import cv2
import numpy as np

from manager.qr_label import parse_payload


@dataclass
class QrResult:
    """QRコードの読み取り判定結果。

    Attributes
    ----------
    status : str
        判定ステータス（"found", "multiple", "not_device", "not_found"）。
    device_id : str | None
        機器ID。status=="found" のときのみ文字列が入る。
    device_name : str | None
        機器名。status=="found" のときのみ文字列が入る。
    payloads : list[str]
        読み取れた文字列の一覧。
    method : str | None
        読み取りに成功した方式（例: "wechat_full", "wechat_bottom_right_2x"）。
    """

    status: str
    device_id: str | None = None
    device_name: str | None = None
    payloads: list[str] = field(default_factory=list)
    method: str | None = None


def issue_for(result: QrResult | str) -> str | None:
    """取り込み側（B5）が使う device_id_issue の値を返す。

    対応関係:
    - found -> None
    - not_found -> "qr_not_found"
    - not_device -> "qr_not_device"
    - multiple -> "qr_multiple"
    - その他 -> "qr_not_found"
    """
    if isinstance(result, QrResult):
        status = result.status
    elif isinstance(result, str):
        status = result
    else:
        status = "not_found"

    mapping = {
        "found": None,
        "not_found": "qr_not_found",
        "not_device": "qr_not_device",
        "multiple": "qr_multiple",
    }
    return mapping.get(status, "qr_not_found")


# 検出器インスタンスのキャッシュ（初期化失敗・非対応環境では None）
_wechat_detector = None
_wechat_initialized = False

_aruco_detector = None
_aruco_initialized = False

_std_detector = None
_std_initialized = False


def _get_wechat_detector():
    global _wechat_detector, _wechat_initialized
    if not _wechat_initialized:
        _wechat_initialized = True
        if hasattr(cv2, "wechat_qrcode_WeChatQRCode"):
            try:
                _wechat_detector = cv2.wechat_qrcode_WeChatQRCode()
            except Exception:
                _wechat_detector = None
    return _wechat_detector


def _get_aruco_detector():
    global _aruco_detector, _aruco_initialized
    if not _aruco_initialized:
        _aruco_initialized = True
        if hasattr(cv2, "QRCodeDetectorAruco"):
            try:
                _aruco_detector = cv2.QRCodeDetectorAruco()
            except Exception:
                _aruco_detector = None
    return _aruco_detector


def _get_std_detector():
    global _std_detector, _std_initialized
    if not _std_initialized:
        _std_initialized = True
        if hasattr(cv2, "QRCodeDetector"):
            try:
                _std_detector = cv2.QRCodeDetector()
            except Exception:
                _std_detector = None
    return _std_detector


def _decode_with_wechat(img: np.ndarray) -> list[str]:
    detector = _get_wechat_detector()
    if detector is None:
        return []
    try:
        texts, _ = detector.detectAndDecode(img)
        return [t for t in texts if t]
    except Exception:
        return []


def _decode_with_aruco(img: np.ndarray) -> list[str]:
    detector = _get_aruco_detector()
    if detector is None:
        return []
    try:
        ret, decoded_info, _, _ = detector.detectAndDecodeMulti(img)
        if ret and decoded_info:
            return [t for t in decoded_info if t]
        single_text, _, _ = detector.detectAndDecode(img)
        if single_text:
            return [single_text]
        return []
    except (cv2.error, Exception):
        return []


def _decode_with_std(img: np.ndarray) -> list[str]:
    detector = _get_std_detector()
    if detector is None:
        return []
    try:
        ret, decoded_info, _, _ = detector.detectAndDecodeMulti(img)
        if ret and decoded_info:
            return [t for t in decoded_info if t]
        single_text, _, _ = detector.detectAndDecode(img)
        if single_text:
            return [single_text]
        return []
    except (cv2.error, Exception):
        return []


def _load_image(image_input: Union[str, Path, np.ndarray]) -> np.ndarray | None:
    if image_input is None:
        return None

    if isinstance(image_input, np.ndarray):
        if image_input.size == 0 or image_input.ndim < 2:
            return None
        if image_input.shape[0] == 0 or image_input.shape[1] == 0:
            return None
        return image_input

    try:
        path = Path(image_input)
        if not path.is_file():
            return None
        data = np.fromfile(str(path), dtype=np.uint8)
        if data.size == 0:
            return None
        img = cv2.imdecode(data, cv2.IMREAD_COLOR)
        if img is None or img.size == 0 or img.shape[0] == 0 or img.shape[1] == 0:
            return None
        return img
    except Exception:
        return None


def _crop_and_resize_2x(img: np.ndarray, corner: str) -> np.ndarray:
    """画像の指定隅（260×260px）を2倍に拡大した画像を返す。"""
    h, w = img.shape[:2]
    cw = min(w, 260)
    ch = min(h, 260)

    if corner == "bottom_right":
        crop = img[h - ch : h, w - cw : w]
    elif corner == "top_right":
        crop = img[0 : ch, w - cw : w]
    elif corner == "top_left":
        crop = img[0 : ch, 0 : cw]
    elif corner == "bottom_left":
        crop = img[h - ch : h, 0 : cw]
    else:
        raise ValueError(f"Unknown corner: {corner}")

    return cv2.resize(crop, (cw * 2, ch * 2), interpolation=cv2.INTER_LINEAR)


def read_device_qr(image_path_or_array: Union[str, Path, np.ndarray]) -> QrResult:
    """画像から機器QRコードを読み取り、判定結果を返す。

    Parameters
    ----------
    image_path_or_array : str | Path | np.ndarray
        画像ファイルパス（日本語パス対応）または画像配列（BGR / グレースケール）。

    Returns
    -------
    QrResult
        判定結果（status, device_id, device_name, payloads, method）。
        例外は外へ出さず、読めない・壊れた画像・不正入力は status="not_found" を返す。
    """
    try:
        img = _load_image(image_path_or_array)
        if img is None:
            return QrResult(
                status="not_found",
                device_id=None,
                device_name=None,
                payloads=[],
                method=None,
            )

        all_non_device_payloads: list[str] = []
        first_non_device_method: str | None = None

        # 読む順序:
        # (1) WeChat・全体
        # (2) Aruco・全体
        # (3) 標準・全体
        # (4) WeChat・右下2倍
        # (5) Aruco・右下2倍
        # (6) 標準・右下2倍
        # (7) 四隅（右上・左上・左下）の260×260pxを2倍に拡大して、WeChat → Aruco → 標準
        stages = [
            ("wechat_full", lambda: _decode_with_wechat(img)),
            ("aruco_full", lambda: _decode_with_aruco(img)),
            ("std_full", lambda: _decode_with_std(img)),
            (
                "wechat_bottom_right_2x",
                lambda: _decode_with_wechat(_crop_and_resize_2x(img, "bottom_right")),
            ),
            (
                "aruco_bottom_right_2x",
                lambda: _decode_with_aruco(_crop_and_resize_2x(img, "bottom_right")),
            ),
            (
                "std_bottom_right_2x",
                lambda: _decode_with_std(_crop_and_resize_2x(img, "bottom_right")),
            ),
        ]

        # (7) 四隅（右上・左上・左下）の260×260pxを2倍拡大: WeChat -> Aruco -> 標準
        for det_name, det_fn in [
            ("wechat", _decode_with_wechat),
            ("aruco", _decode_with_aruco),
            ("std", _decode_with_std),
        ]:
            for corner in ["top_right", "top_left", "bottom_left"]:
                method_name = f"{det_name}_{corner}_2x"
                stages.append(
                    (
                        method_name,
                        lambda fn=det_fn, c=corner: fn(_crop_and_resize_2x(img, c)),
                    )
                )

        for method_name, decode_fn in stages:
            payloads = decode_fn()
            if not payloads:
                continue

            # 機器QRの判定
            device_infos: list[dict] = []
            for text in payloads:
                parsed = parse_payload(text)
                if parsed is not None and "id" in parsed:
                    device_infos.append(parsed)

            if device_infos:
                # 異なるidの数を集計
                unique_ids = list(dict.fromkeys(info["id"] for info in device_infos))
                if len(unique_ids) >= 2:
                    return QrResult(
                        status="multiple",
                        device_id=None,
                        device_name=None,
                        payloads=payloads,
                        method=method_name,
                    )
                else:
                    # 1つ（同一idの重複は1つとして扱う）
                    matched_info = device_infos[0]
                    return QrResult(
                        status="found",
                        device_id=matched_info["id"],
                        device_name=matched_info.get("name"),
                        payloads=payloads,
                        method=method_name,
                    )
            else:
                # 機器QRではないQRが読めた場合
                for text in payloads:
                    if text not in all_non_device_payloads:
                        all_non_device_payloads.append(text)
                if first_non_device_method is None:
                    first_non_device_method = method_name

        # すべての方式で機器QRが読めなかった場合
        if all_non_device_payloads:
            return QrResult(
                status="not_device",
                device_id=None,
                device_name=None,
                payloads=all_non_device_payloads,
                method=first_non_device_method,
            )

        return QrResult(
            status="not_found",
            device_id=None,
            device_name=None,
            payloads=[],
            method=None,
        )

    except Exception:
        return QrResult(
            status="not_found",
            device_id=None,
            device_name=None,
            payloads=[],
            method=None,
        )
