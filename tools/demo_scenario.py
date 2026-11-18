"""デモ用点検6件と例外シナリオの送信計画を組み立てるモジュール。

仕様: tasks/design/デモ用3Dメーターと機器カタログ.md
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
import hashlib
from pathlib import Path

DEFAULT_PHOTOS_DIR = Path(__file__).resolve().parent.parent / "demo" / "photos"
JST = timezone(timedelta(hours=9))
BROKEN_PNG_BYTES = b"DEMO-BROKEN-PNG-v1"

ROUTES: tuple[tuple[str, str, str, tuple[str, ...]], ...] = (
    ("DMO-ROUTE-A", "A", "動力設備巡回", tuple(f"DMO-{i:03d}" for i in range(1, 11))),
    ("DMO-ROUTE-B", "B", "冷却・熱交換設備巡回", tuple(f"DMO-{i:03d}" for i in range(11, 21))),
)

INSPECTION_DATES: tuple[date, ...] = (
    date(2026, 11, 16),
    date(2026, 11, 17),
    date(2026, 11, 18),
)


def _is_odd_device(device_id: str) -> bool:
    return int(device_id.split("-")[1]) % 2 == 1


def _route_schedule(
    day: date, route_suffix: str, device_ids: tuple[str, ...]
) -> tuple[list[tuple[str, int, bool, bool]], list[str], list[str]]:
    """日とルートに応じた (device_id, shot, resend, broken) 列と missing/extra を返す。"""
    if day == date(2026, 11, 16):
        items = [(did, 1, route_suffix == "A" and did == "DMO-001", False) for did in device_ids]
        return items, [], []
    if day == date(2026, 11, 17):
        return [(did, 2, False, False) for did in device_ids], [], []
    if day == date(2026, 11, 18) and route_suffix == "A":
        items = [(did, 3, False, False) for did in device_ids if did != "DMO-010"]
        items.append(("DMO-011", 4, False, False))
        items.append(("DMO-001", 4, False, False))
        return items, ["DMO-010"], ["DMO-011"]
    if day == date(2026, 11, 18) and route_suffix == "B":
        items = [(did, 3, False, did == "DMO-019") for did in device_ids]
        return items, [], []
    raise ValueError(f"未定義の点検日・ルートです: {day.isoformat()} {route_suffix}")


def build_inspections(
    catalog: list[dict],
    truth: dict,
    photos_dir: Path | None = None,
) -> list[dict]:
    """日付昇順・日内 A→B で6件の点検データ（manifest と uploads）を組み立てる。"""
    if truth.get("v") != 1 or not isinstance(truth.get("frames"), list):
        raise ValueError("groundtruth.json の形式が不正です")

    photos_root = Path(photos_dir) if photos_dir is not None else DEFAULT_PHOTOS_DIR
    devices_by_id = {d["device_id"]: d for d in catalog}
    frames_by_key = {(f["device_id"], f["shot"]): f for f in truth["frames"]}

    inspections: list[dict] = []
    local_id = 0

    for day in INSPECTION_DATES:
        for route_id, suffix, route_name, device_ids in ROUTES:
            start_hour = 8 if suffix == "A" else 14
            started_dt = datetime.combine(day, time(start_hour, 0), tzinfo=JST)
            completed_dt = started_dt + timedelta(minutes=20)
            inspection_id = f"DMO-{day.strftime('%Y%m%d')}-{suffix}"
            inspection_name = f"{day.isoformat()} {route_name}"

            items, missing, extra = _route_schedule(day, suffix, device_ids)
            uploads: list[dict] = []
            manifest_photos: list[dict] = []

            for seq, (device_id, shot, resend, broken) in enumerate(items, start=1):
                device = devices_by_id[device_id]
                frame = frames_by_key[(device_id, shot)]
                local_id += 1
                captured_dt = started_dt + timedelta(minutes=seq)
                captured_at = captured_dt.isoformat(timespec="seconds")
                file_name = f"{captured_dt.strftime('%Y%m%dT%H%M%S')}_{local_id}.png"

                if broken:
                    body = BROKEN_PNG_BYTES
                else:
                    body = (photos_root / frame["file"]).read_bytes()
                    actual_sha = hashlib.sha256(body).hexdigest()
                    if actual_sha != frame["sha256"]:
                        raise ValueError(
                            f"{device_id} shot {shot} のSHA-256が真値と一致しません"
                        )
                sha256 = hashlib.sha256(body).hexdigest()

                include_id_in_sidecar = broken or not _is_odd_device(device_id)
                sidecar: dict = {
                    "local_id": local_id,
                    "captured_at": captured_at,
                    "inspection_id": inspection_id,
                    "inspection_name": inspection_name,
                    "route_id": route_id,
                }
                if include_id_in_sidecar:
                    sidecar["device_id"] = device["device_id"]
                    sidecar["device_name"] = device["device_name"]

                upload = {
                    "file_name": file_name,
                    "body": body,
                    "sidecar": sidecar,
                    "sha256": sha256,
                }
                uploads.append(upload)
                if resend:
                    uploads.append(
                        {
                            "file_name": file_name,
                            "body": body,
                            "sidecar": dict(sidecar),
                            "sha256": sha256,
                        }
                    )

                manifest_photos.append(
                    {
                        "file_name": file_name,
                        "sha256": sha256,
                        "device_id": device["device_id"] if include_id_in_sidecar else None,
                        "device_id_source": None,
                        "captured_at": captured_at,
                    }
                )

            manifest = {
                "v": 1,
                "inspection_id": inspection_id,
                "inspection_name": inspection_name,
                "route_id": route_id,
                "operator": "デモ担当",
                "place": "設備棟",
                "started_at": started_dt.isoformat(timespec="seconds"),
                "completed_at": completed_dt.isoformat(timespec="seconds"),
                "missing": missing,
                "extra": extra,
                "photos": manifest_photos,
            }
            inspections.append({"manifest": manifest, "uploads": uploads})

    return inspections
