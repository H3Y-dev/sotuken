"""Device registry shared by automatic registration and explicit CSV imports."""

import csv
import math
from dataclasses import dataclass, field
from datetime import datetime, timezone

from manager.qr_label import validate_device_id as _validate_device_id


_FIELDS = ("device_name", "unit", "min_value", "max_value", "kind", "provisional", "note")


@dataclass
class DeviceResult:
    created: bool = False
    updated_fields: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    skipped: bool = False


def validate_device_id(device_id) -> bool:
    try:
        _validate_device_id(device_id)
    except ValueError:
        return False
    return True


def _now():
    return datetime.now(timezone.utc).isoformat()


def _select_device(conn, device_id):
    cursor = conn.execute("SELECT * FROM devices WHERE device_id = ?", (device_id,))
    row = cursor.fetchone()
    return dict(zip((col[0] for col in cursor.description), row)) if row else None


def get_device(storage, device_id) -> dict | None:
    with storage.connection() as conn:
        return _select_device(conn, device_id)


def list_devices(storage) -> list[dict]:
    with storage.connection() as conn:
        cursor = conn.execute("SELECT * FROM devices ORDER BY device_id")
        columns = [col[0] for col in cursor.description]
        return [dict(zip(columns, row)) for row in cursor.fetchall()]


def _update(conn, device_id, values):
    if values:
        fields = list(values)
        conn.execute(
            "UPDATE devices SET " + ", ".join(f"{name} = ?" for name in fields)
            + ", updated_at = ? WHERE device_id = ?",
            [values[name] for name in fields] + [_now(), device_id],
        )


def register_device(storage, device_id, device_name=None, unit=None,
                    min_value=None, max_value=None, kind=None,
                    provisional=False, note=None, source="auto") -> DeviceResult:
    """Fill missing registry fields; source does not change the merge rules."""
    _validate_device_id(device_id)
    if device_name is not None:
        if not isinstance(device_name, str):
            raise ValueError("device_name must be a string")
        device_name = device_name.strip()
        if not device_name or device_name == "unknown":
            return DeviceResult(skipped=True)
    values = dict(zip(_FIELDS, (device_name, unit, min_value, max_value,
                                kind, provisional, note)))
    result = DeviceResult()
    with storage.connection() as conn:
        # Serialize the read-then-write rule across separate automatic imports.
        conn.execute("BEGIN IMMEDIATE")
        if conn.execute(
            "SELECT 1 FROM devices WHERE device_id = ? COLLATE NOCASE AND device_id != ?",
            (device_id, device_id),
        ).fetchone():
            result.warnings.append("id_case_conflict")
        old = _select_device(conn, device_id)
        if old is None:
            now = _now()
            values["device_name"] = device_name if device_name is not None else device_id
            values["provisional"] = values["provisional"] or 0
            conn.execute(
                "INSERT INTO devices (device_id, " + ", ".join(_FIELDS)
                + ", created_at, updated_at) VALUES (" + ", ".join("?" for _ in range(10)) + ")",
                [device_id] + [values[name] for name in _FIELDS] + [now, now],
            )
            result.created = True
            return result

        changed = {}
        for name in _FIELDS:
            incoming = values[name]
            if incoming is None or incoming == "":
                continue
            if old[name] is None or old[name] == "":
                changed[name] = incoming
            elif old[name] != incoming:
                warning = {"device_name": "name_conflict", "unit": "unit_conflict",
                           "min_value": "range_conflict", "max_value": "range_conflict"}.get(name)
                if warning and warning not in result.warnings:
                    result.warnings.append(warning)
        _update(conn, device_id, changed)
        result.updated_fields = list(changed)
    return result


def rename_device(storage, device_id, new_name):
    _validate_device_id(device_id)
    if not isinstance(new_name, str) or not new_name.strip() or new_name.strip() == "unknown":
        raise ValueError("A device name is required")
    with storage.connection() as conn:
        if _select_device(conn, device_id) is None:
            raise ValueError(f"Device not found: {device_id}")
        _update(conn, device_id, {"device_name": new_name.strip()})


def _csv_values(row):
    values = {name: row.get(name) or None for name in _FIELDS}
    for name in ("min_value", "max_value"):
        if values[name] is not None:
            values[name] = float(values[name])
            if not math.isfinite(values[name]):
                raise ValueError(f"Invalid {name}")
    provisional = values["provisional"]
    if provisional not in (None, "0", "1"):
        raise ValueError("provisional must be 0 or 1")
    values["provisional"] = int(provisional) if provisional is not None else None
    return values


def import_devices_csv(storage, csv_path, overwrite=False) -> dict:
    result = {"created": 0, "updated": 0, "skipped": 0,
              "differences": [], "errors": [], "warnings": []}
    seen = set()
    with open(csv_path, encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        for line, row in enumerate(reader, start=2):
            device_id = row.get("device_id")
            try:
                _validate_device_id(device_id)
                if device_id in seen:
                    raise ValueError("Duplicate device_id")
                seen.add(device_id)
                values = _csv_values(row)
            except (ValueError, TypeError) as exc:
                result["errors"].append({"line": line, "device_id": device_id, "error": str(exc)})
                result["skipped"] += 1
                continue

            # Missing CSV names must not become an implicit ID-only registration.
            if values["device_name"] is None:
                values["device_name"] = ""
            if not overwrite:
                registered = register_device(storage, device_id, **values, source="csv")
            else:
                with storage.connection() as conn:
                    old = _select_device(conn, device_id)
                    if old is None or not values["device_name"].strip() or values["device_name"].strip() == "unknown":
                        registered = None
                    else:
                        values["device_name"] = values["device_name"].strip()
                        values["provisional"] = values["provisional"] or 0
                        changed = {name: values[name] for name in _FIELDS if old[name] != values[name]}
                        _update(conn, device_id, changed)
                        result["differences"].extend(
                            {"device_id": device_id, "field": name,
                             "old_value": old[name], "new_value": value}
                            for name, value in changed.items()
                        )
                        registered = DeviceResult(updated_fields=list(changed))
                if registered is None:
                    registered = register_device(storage, device_id, **values, source="csv")
            if registered.warnings:
                result["warnings"].append({"line": line, "device_id": device_id,
                                           "warnings": registered.warnings})
            if registered.created:
                result["created"] += 1
            elif registered.updated_fields:
                result["updated"] += 1
            else:
                result["skipped"] += 1
    return result
