"""デモ用受信口へ画像と完了manifestをHTTP送信するモジュール。

仕様: tasks/design/デモ用3Dメーターと機器カタログ.md
"""

from __future__ import annotations

import base64
import json
import urllib.request


def _post(url: str, body: bytes, headers: dict[str, str], timeout: float) -> dict:
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        if resp.status != 200:
            raise RuntimeError(f"予期しないHTTPステータスです: {resp.status}")
        data = json.loads(resp.read().decode("utf-8"))
    if not isinstance(data, dict):
        raise RuntimeError(f"応答JSONがオブジェクトではありません: {data!r}")
    return data


def upload_photo(base_url: str, token: str, photo: dict, timeout: float = 10.0) -> dict:
    """1枚の画像とサイドカーを POST /upload へ送信し、応答JSONを返す。"""
    file_name = photo["file_name"]
    body = photo["body"]
    sidecar_bytes = json.dumps(photo["sidecar"], ensure_ascii=False).encode("utf-8")
    sidecar_b64 = base64.urlsafe_b64encode(sidecar_bytes).decode("ascii").rstrip("=")
    headers = {
        "X-Sotuken-Token": token,
        "X-File-Name": file_name,
        "Content-Length": str(len(body)),
        "X-Image-Sha256": str(photo["sha256"]).lower(),
        "X-Sidecar-Json": sidecar_b64,
    }
    data = _post(f"{base_url.rstrip('/')}/upload", body, headers, timeout)
    if data.get("stored") != file_name:
        raise RuntimeError(f"画像送信の応答が不正です ({file_name}): {data!r}")
    return data


def send_manifest(base_url: str, token: str, manifest: dict, timeout: float = 10.0) -> dict:
    """1回分の完了manifestを POST /inspections/<id>/manifest へ送信し、応答JSONを返す。"""
    inspection_id = manifest["inspection_id"]
    body = json.dumps(manifest, ensure_ascii=False).encode("utf-8")
    headers = {
        "X-Sotuken-Token": token,
        "Content-Type": "application/json",
        "Content-Length": str(len(body)),
    }
    data = _post(
        f"{base_url.rstrip('/')}/inspections/{inspection_id}/manifest",
        body,
        headers,
        timeout,
    )
    expected_count = len(manifest.get("photos", []))
    if (
        data.get("ok") is not True
        or data.get("matched") != expected_count
        or data.get("missing_photos") != []
    ):
        raise RuntimeError(f"manifest送信の応答が不正です ({inspection_id}): {data!r}")
    return data
