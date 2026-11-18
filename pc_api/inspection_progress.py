"""Inspection progress builder and summary helpers for PC API."""
from datetime import datetime, timezone
import math

from manager.export import _reading_time
from manager.ingest import UNKNOWN_DEVICE
from manager.routes import arrived_manifest_devices, get_manifest, get_route, route_progress
from pc_api.server import APIError

_MAX_MANIFEST_PHOTOS = 10000
_MAX_PROGRESS_DEVICES = 1000
_SOURCE_MAP = {
    'qr': 'phone_qr',
    'sidecar_qr': 'phone_qr',
    'manual': 'manual',
    'sidecar_manual': 'manual',
    'pc_qr': 'pc_qr',
}


def _field(row, key):
    return row.get(key) if isinstance(row, dict) else getattr(row, key, None)


def _clean_text(value):
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


def _clean_device_id(value):
    text = _clean_text(value)
    if text is None or text.lower() == UNKNOWN_DEVICE:
        return None
    return text


def _clean_device_name(value):
    text = _clean_text(value)
    if text is None or text == UNKNOWN_DEVICE:
        return None
    return text


def _format_iso_offset(text):
    clean = _clean_text(text)
    if clean is None:
        return None
    dt = datetime.fromisoformat(clean)
    if dt.tzinfo is None:
        return dt.astimezone().isoformat()
    return clean


def _parse_iso_for_sort(text):
    clean = _clean_text(text)
    if clean is None:
        return None
    try:
        dt = datetime.fromisoformat(clean)
    except ValueError:
        return None
    if dt.tzinfo is not None:
        return dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def _valid_scale(min_val, max_val):
    if min_val is None or max_val is None:
        return None
    lo, hi = float(min_val), float(max_val)
    if math.isfinite(lo) and math.isfinite(hi) and lo < hi:
        return [lo, hi]
    return None


def _valid_tolerance(min_val, max_val):
    if min_val is None or max_val is None:
        return None
    lo, hi = float(min_val), float(max_val)
    if math.isfinite(lo) and math.isfinite(hi) and lo <= hi:
        return [lo, hi]
    return None


def _normalize_value_status(row):
    raw_status = _field(row, 'status')
    raw_value = _field(row, 'value')
    if raw_status == 'failed':
        return None, 'failed'
    is_finite = (
        raw_value is not None
        and isinstance(raw_value, (int, float))
        and not isinstance(raw_value, bool)
        and math.isfinite(raw_value)
    )
    if raw_status in ('ok', 'low_confidence') and is_finite:
        return float(raw_value), raw_status
    return None, 'failed'


def _build_status(manifest, hashes):
    if manifest is None:
        return {'state': '受信中', 'matched': 0, 'missing_photos': []}
    photos = manifest['photos']
    missing = [
        p['file_name']
        for p in photos
        if p.get('sha256') is None or p['sha256'].lower() not in hashes
    ]
    return {
        'state': '不足あり' if missing else '完了',
        'matched': len(photos) - len(missing),
        'missing_photos': missing,
    }


def _select_route_id(manifest, readings):
    if manifest is not None:
        route_id = _clean_text(manifest.get('route_id'))
        if route_id is not None:
            return route_id
    for row in sorted(readings, key=lambda r: _field(r, 'id') or 0, reverse=True):
        route_id = _clean_text(_field(row, 'route_id'))
        if route_id is not None:
            return route_id
    return None


def _build_meta(inspection_id, manifest, readings, route_id, route):
    route_name = route['name'] if route is not None else None
    if manifest is not None:
        name = _clean_text(manifest.get('inspection_name')) or inspection_id
        return {
            'id': inspection_id,
            'name': name,
            'route_id': route_id,
            'route_name': route_name,
            'operator': _clean_text(manifest.get('operator')),
            'place': _clean_text(manifest.get('place')),
            'started_at': _format_iso_offset(manifest.get('started_at')),
            'completed_at': _format_iso_offset(manifest.get('completed_at')),
        }

    ordered = sorted(readings, key=lambda r: _field(r, 'id') or 0, reverse=True)
    name = inspection_id
    if ordered:
        name = _clean_text(_field(ordered[0], 'inspection_name')) or inspection_id

    oldest_dt = None
    oldest_iso = None
    for row in ordered:
        for col in ('captured_at', 'received_at', 'timestamp'):
            raw = _clean_text(_field(row, col))
            if raw is None:
                continue
            dt = _parse_iso_for_sort(raw)
            if dt is not None:
                if oldest_dt is None or dt < oldest_dt:
                    oldest_dt = dt
                    oldest_iso = _format_iso_offset(raw)
                break

    return {
        'id': inspection_id,
        'name': name,
        'route_id': route_id,
        'route_name': route_name,
        'operator': None,
        'place': None,
        'started_at': oldest_iso,
        'completed_at': None,
    }


def _load_devices_map(storage, device_ids):
    if not device_ids:
        return {}
    placeholders = ', '.join('?' for _ in device_ids)
    with storage.connection() as conn:
        rows = conn.execute(
            f'SELECT device_id, device_name, unit, min_value, max_value, tolerance_min, tolerance_max '
            f'FROM devices WHERE device_id IN ({placeholders})',
            tuple(device_ids),
        ).fetchall()
    return {
        r[0]: {
            'device_name': _clean_text(r[1]),
            'unit': _clean_text(r[2]),
            'scale': _valid_scale(r[3], r[4]),
            'tolerance': _valid_tolerance(r[5], r[6]),
        }
        for r in rows
    }


def build_inspection_progress(storage, incoming_dir, inspection_id, readings, hashes):
    """Build InspectionProgress DTO from DB readings, manifest, route, and devices."""
    manifest = get_manifest(storage, inspection_id)
    if manifest is not None:
        if not isinstance(manifest, dict) or not isinstance(manifest.get('photos'), list):
            raise ValueError('invalid manifest')
        if len(manifest['photos']) > _MAX_MANIFEST_PHOTOS:
            raise APIError(422, 'validation_failed')

    route_id = _select_route_id(manifest, readings)
    route = get_route(storage, route_id) if route_id is not None else None
    meta = _build_meta(inspection_id, manifest, readings, route_id, route)
    status = _build_status(manifest, hashes)

    if route is not None:
        arrived = arrived_manifest_devices(storage, manifest, readings, incoming_dir, hashes=hashes)
        route_progress(route, [*readings, *arrived], manifest)

    # Unify photos by hash / file_name / row_id.
    photos_by_id = {}
    manifest_by_hash = {}
    for p in (manifest['photos'] if manifest is not None else []):
        sha = _clean_text(p.get('sha256'))
        sha_lower = sha.lower() if sha else None
        photo_id = f'hash:{sha_lower}' if sha_lower else f"file:{p['file_name']}"
        if sha_lower and sha_lower not in manifest_by_hash:
            manifest_by_hash[sha_lower] = p
        if photo_id in photos_by_id:
            continue
        arrived_flag = bool(sha_lower and sha_lower in hashes)
        photos_by_id[photo_id] = {
            'photo_id': photo_id,
            'sha256': sha_lower,
            'manifest_photo': p,
            'readings': [],
            'stage': 2 if arrived_flag else 1,
        }

    for row in readings:
        sha = _clean_text(_field(row, 'image_sha256'))
        sha_lower = sha.lower() if sha else None
        photo_id = f'hash:{sha_lower}' if sha_lower else f"row:{_field(row, 'id')}"
        entry = photos_by_id.get(photo_id)
        if entry is None:
            entry = {
                'photo_id': photo_id,
                'sha256': sha_lower,
                'manifest_photo': manifest_by_hash.get(sha_lower) if sha_lower else None,
                'readings': [],
                'stage': 4,
            }
            photos_by_id[photo_id] = entry
        else:
            entry['stage'] = 4
        entry['readings'].append(row)

    # Group photos into device buckets.
    groups = {}
    for photo in photos_by_id.values():
        p_readings = photo['readings']
        m_photo = photo['manifest_photo']
        db_dev_id = None
        db_dev_name = None
        if p_readings:
            latest_p_row = max(p_readings, key=lambda r: (_reading_time(r), _field(r, 'id') or 0))
            db_dev_id = _clean_device_id(_field(latest_p_row, 'device_id'))
            db_dev_name = _clean_device_name(_field(latest_p_row, 'device_name'))
            if db_dev_id is None:
                for r in sorted(p_readings, key=lambda x: (_reading_time(x), _field(x, 'id') or 0), reverse=True):
                    cand = _clean_device_id(_field(r, 'device_id'))
                    if cand is not None:
                        db_dev_id = cand
                        break
        m_dev_id = _clean_device_id(m_photo.get('device_id')) if m_photo else None
        dev_id = db_dev_id if db_dev_id is not None else m_dev_id

        if dev_id is not None:
            key = f'device:{dev_id}'
        elif db_dev_name is not None:
            key = f'name:{db_dev_name}'
        else:
            key = f"photo:{photo['photo_id']}"

        grp = groups.setdefault(key, {
            'key': key,
            'device_id': dev_id,
            'photos': [],
            'readings': [],
            'manifest_photos': [],
        })
        grp['photos'].append(photo)
        grp['readings'].extend(p_readings)
        if m_photo is not None:
            grp['manifest_photos'].append(m_photo)

    # Planned devices from route and extra declarations from manifest.
    planned_keys = []
    planned_route_names = {}
    if route is not None:
        for idx, d in enumerate(route['devices'], start=1):
            key = f"device:{d['id']}"
            planned_keys.append((idx, key, d['id']))
            planned_route_names[key] = _clean_text(d.get('name'))
            groups.setdefault(key, {
                'key': key,
                'device_id': d['id'],
                'photos': [],
                'readings': [],
                'manifest_photos': [],
            })

    if manifest is not None:
        for extra_id in dict.fromkeys(manifest.get('extra', [])):
            clean_id = _clean_device_id(extra_id)
            if clean_id is None:
                continue
            key = f'device:{clean_id}'
            groups.setdefault(key, {
                'key': key,
                'device_id': clean_id,
                'photos': [],
                'readings': [],
                'manifest_photos': [],
                'extra_only': True,
            })

    if len(groups) > _MAX_PROGRESS_DEVICES:
        raise APIError(422, 'validation_failed')

    device_ids = [g['device_id'] for g in groups.values() if g['device_id'] is not None]
    devices_db = _load_devices_map(storage, list(dict.fromkeys(device_ids)))

    def _build_meter(grp, seq, off_route):
        dev_id = grp['device_id']
        db_info = devices_db.get(dev_id) if dev_id is not None else None
        grp_readings = grp['readings']
        grp_m_photos = grp['manifest_photos']

        latest_row = None
        if grp_readings:
            latest_row = max(grp_readings, key=lambda r: (_reading_time(r), _field(r, 'id') or 0))

        # Display name priority: devices DB -> route -> latest DB reading -> device_id -> '名前なし'
        latest_row_name = _clean_device_name(_field(latest_row, 'device_name')) if latest_row is not None else None
        name = (
            (db_info['device_name'] if db_info else None)
            or planned_route_names.get(grp['key'])
            or latest_row_name
            or dev_id
            or '名前なし'
        )

        if grp['photos']:
            stage = max(p['stage'] for p in grp['photos'])
        elif grp.get('extra_only'):
            stage = 1
        else:
            stage = 0

        if latest_row is not None:
            value, read_status = _normalize_value_status(latest_row)
            cap = _clean_text(_field(latest_row, 'captured_at'))
            if cap is not None:
                captured_at = _format_iso_offset(cap)
            else:
                sha = _clean_text(_field(latest_row, 'image_sha256'))
                m_match = manifest_by_hash.get(sha.lower()) if sha else None
                m_cap = _clean_text(m_match.get('captured_at')) if m_match else None
                captured_at = _format_iso_offset(m_cap) if m_cap else None
        else:
            value, read_status = None, None
            best_dt = None
            captured_at = None
            for mp in grp_m_photos:
                m_cap = _clean_text(mp.get('captured_at'))
                if m_cap is None:
                    continue
                dt = _parse_iso_for_sort(m_cap)
                if dt is not None and (best_dt is None or dt > best_dt):
                    best_dt = dt
                    captured_at = _format_iso_offset(m_cap)

        sources_raw = []
        for mp in grp_m_photos:
            mapped = _SOURCE_MAP.get(_clean_text(mp.get('device_id_source')))
            if mapped:
                sources_raw.append(mapped)
        for r in grp_readings:
            mapped = _SOURCE_MAP.get(_clean_text(_field(r, 'device_id_source')))
            if mapped:
                sources_raw.append(mapped)
        sources = list(dict.fromkeys(sources_raw))

        return {
            'key': grp['key'],
            'seq': seq,
            'off_route': off_route,
            'device_id': dev_id,
            'name': name,
            'unit': db_info['unit'] if db_info else None,
            'scale': db_info['scale'] if db_info else None,
            'tolerance': db_info['tolerance'] if db_info else None,
            'stage': stage,
            'value': value,
            'read_status': read_status,
            'sources': sources,
            'photos': len(grp['photos']),
            'captured_at': captured_at,
        }

    devices_out = []
    planned_set = {k for _, k, _ in planned_keys}
    for seq, key, _ in planned_keys:
        devices_out.append(_build_meter(groups[key], seq=seq, off_route=False))

    other_keys = sorted(k for k in groups if k not in planned_set)
    is_off_route = route is not None
    for key in other_keys:
        devices_out.append(_build_meter(groups[key], seq=None, off_route=is_off_route))

    return {
        **meta,
        'status': status,
        'devices': devices_out,
    }


def _judge_meter(meter):
    stage = meter['stage']
    val = meter['value']
    status = meter['read_status']
    dev_id = meter['device_id'] or ''
    scale = meter['scale']
    tol = meter['tolerance']

    if stage == 0:
        return 'missing', False
    is_finite = val is not None and math.isfinite(val)
    if status == 'failed' or (stage >= 3 and not is_finite):
        return 'fail', False
    if stage < 4 or not is_finite:
        return 'wait', False

    has_warn = (
        not dev_id
        or status == 'low_confidence'
        or (scale is not None and (val < scale[0] or val > scale[1]))
    )
    out_of_tol = bool(dev_id and tol is not None and (val < tol[0] or val > tol[1]))
    return ('warn' if has_warn else 'ok'), out_of_tol


def summarize_progress(progress):
    """Compute InspectionSummary matching frontend judge.ts::summarize."""
    devices = progress['devices']
    route_total = 0
    route_captured = 0
    route_recorded = 0
    captured = 0
    recorded = 0
    missing = 0
    off_route = 0
    off_route_recorded = 0
    warn = 0
    fail = 0
    wait = 0
    out_of_tolerance = 0
    all_ok_devices = True

    for d in devices:
        kind, out_of_tol = _judge_meter(d)
        stage = d['stage']
        val = d['value']
        is_rec = stage >= 4 and val is not None and math.isfinite(val) and kind != 'fail'

        if d['seq'] is not None:
            route_total += 1
            if stage > 0:
                route_captured += 1
            if is_rec:
                route_recorded += 1
        if d['off_route']:
            off_route += 1
            if is_rec:
                off_route_recorded += 1
        if stage >= 1:
            captured += 1
        if is_rec:
            recorded += 1

        if kind == 'missing':
            missing += 1
        elif kind == 'warn':
            warn += 1
        elif kind == 'fail':
            fail += 1
        elif kind == 'wait':
            wait += 1

        if out_of_tol:
            out_of_tolerance += 1
        if kind != 'ok' or out_of_tol:
            all_ok_devices = False

    needs_action = (
        (missing + off_route + warn + fail > 0)
        or (progress['status']['state'] == '不足あり')
        or (out_of_tolerance > 0)
    )
    all_ok = (
        progress['status']['state'] == '完了'
        and len(devices) > 0
        and not needs_action
        and all_ok_devices
    )
    return {
        'route_total': route_total,
        'route_captured': route_captured,
        'route_recorded': route_recorded,
        'captured': captured,
        'recorded': recorded,
        'missing': missing,
        'off_route': off_route,
        'off_route_recorded': off_route_recorded,
        'warn': warn,
        'fail': fail,
        'wait': wait,
        'out_of_tolerance': out_of_tolerance,
        'all_ok': all_ok,
        'needs_action': needs_action,
    }


def parse_iso_for_sort(text):
    """Parse ISO 8601 string into UTC naive datetime for sorting."""
    return _parse_iso_for_sort(text)


def build_inspection_preview(devices, has_route):
    """Select preview meters in progress order (6 route + 2 off-route, or 6 total)."""
    if has_route:
        on_route = [d for d in devices if not d['off_route']][:6]
        off_route = [d for d in devices if d['off_route']][:2]
        return on_route + off_route
    return list(devices[:6])


def build_inspection_list_item(progress, reading_count):
    """Build InspectionListItem DTO from full InspectionProgress and DB reading count."""
    return {
        'id': progress['id'],
        'name': progress['name'],
        'route_id': progress['route_id'],
        'route_name': progress['route_name'],
        'operator': progress['operator'],
        'place': progress['place'],
        'started_at': progress['started_at'],
        'completed_at': progress['completed_at'],
        'count': reading_count,
        'status': {
            'state': progress['status']['state'],
            'matched': progress['status']['matched'],
        },
        'missing_photo_count': len(progress['status']['missing_photos']),
        'preview': build_inspection_preview(
            progress['devices'], progress['route_name'] is not None
        ),
        'summary': summarize_progress(progress),
    }

