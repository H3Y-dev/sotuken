"""Read-only inspection status routes for PC API."""
from contextlib import closing, contextmanager
import re
from types import SimpleNamespace
from urllib.parse import parse_qs, unquote

from manager.routes import get_manifest, inspection_status, received_hashes, validate_id
from pc_api.inspection_pages import get_page_cache, parse_inspections_query
from pc_api.inspection_progress import (
    build_inspection_list_item,
    build_inspection_progress,
    parse_iso_for_sort,
)
from pc_api.server import APIError

_MAX_INSPECTIONS = 10000
_MAX_MANIFEST_PHOTOS = 10000
_MAX_PROGRESS_READINGS = 10000
_STATUS_PATH_RE = re.compile(r'/api/v1/inspections/([^/]+)/status')
_PROGRESS_PATH_RE = re.compile(r'/api/v1/inspections/([^/]+)/progress')
_PROGRESS_READING_COLUMNS = (
    'id', 'device_id', 'device_name', 'device_id_source', 'value', 'status',
    'stage', 'image_sha256', 'captured_at', 'received_at', 'timestamp',
    'inspection_name', 'route_id', 'image_path', 'overlay_path',
)


class _ReadOnlyStorageAdapter:
    """Adapter exposing a single read-only transaction connection without commit/close."""

    def __init__(self, conn):
        self._conn = conn

    @contextmanager
    def connection(self):
        yield self._conn

    def get_processed_hashes(self):
        rows = self._conn.execute(
            'SELECT image_sha256 FROM meter_readings WHERE image_sha256 IS NOT NULL'
        ).fetchall()
        return {row[0] for row in rows}


@contextmanager
def _open_read_adapter(storage):
    with closing(storage._get_connection()) as conn:
        conn.execute('BEGIN')
        try:
            yield _ReadOnlyStorageAdapter(conn)
        finally:
            if conn.in_transaction:
                conn.rollback()


def validate_inspection_id(value):
    """Validate a single-decoded inspection path ID."""
    if value in ('.', '..'):
        raise APIError(400, 'invalid_request')
    try:
        return validate_id(value)
    except ValueError:
        raise APIError(400, 'invalid_request') from None


def _ensure_inspection_exists(storage, inspection_id):
    with storage.connection() as conn:
        in_inspections = conn.execute(
            'SELECT 1 FROM inspections WHERE inspection_id = ? LIMIT 1',
            (inspection_id,),
        ).fetchone() is not None
        in_readings = conn.execute(
            'SELECT 1 FROM meter_readings WHERE inspection_id = ? LIMIT 1',
            (inspection_id,),
        ).fetchone() is not None
    if not in_inspections and not in_readings:
        raise APIError(404, 'not_found')


def get_inspection_status(storage, incoming_dir, inspection_id):
    """Verify inspection existence and return its manifest/incoming receive status."""
    _ensure_inspection_exists(storage, inspection_id)

    hashes = received_hashes(storage, incoming_dir)
    try:
        manifest = get_manifest(storage, inspection_id)
    except (ValueError, TypeError):
        raise APIError(503, 'data_invalid') from None
    if manifest is not None:
        if not isinstance(manifest, dict) or not isinstance(manifest.get('photos'), list):
            raise APIError(503, 'data_invalid')
        if len(manifest['photos']) > _MAX_MANIFEST_PHOTOS:
            raise APIError(422, 'validation_failed')

    try:
        return inspection_status(storage, inspection_id, incoming_dir, hashes=hashes)
    except (ValueError, TypeError, KeyError, AttributeError):
        raise APIError(503, 'data_invalid') from None


def get_inspection_progress(storage, incoming_dir, inspection_id, *, image_id):
    """Verify inspection existence and return full InspectionProgress DTO."""
    _ensure_inspection_exists(storage, inspection_id)

    cols = ', '.join(_PROGRESS_READING_COLUMNS)
    with storage.connection() as conn:
        rows = conn.execute(
            f'SELECT {cols} FROM meter_readings WHERE inspection_id = ? ORDER BY id DESC LIMIT ?',
            (inspection_id, _MAX_PROGRESS_READINGS + 1),
        ).fetchall()
    if len(rows) > _MAX_PROGRESS_READINGS:
        raise APIError(422, 'validation_failed')
    readings = [SimpleNamespace(**dict(zip(_PROGRESS_READING_COLUMNS, row))) for row in rows]

    hashes = received_hashes(storage, incoming_dir)
    try:
        return build_inspection_progress(storage, incoming_dir, inspection_id, readings, hashes, image_id=image_id)
    except APIError:
        raise
    except (ValueError, TypeError, KeyError, AttributeError):
        raise APIError(503, 'data_invalid') from None


def _sort_inspection_items(items):
    dated = []
    undated = []
    for item in items:
        dt = parse_iso_for_sort(item.get('started_at'))
        if dt is not None:
            dated.append((dt, item['id'], item))
        else:
            undated.append((item['id'], item))
    dated.sort(key=lambda row: (row[0], row[1]), reverse=True)
    undated.sort(key=lambda row: row[0], reverse=True)
    return [row[2] for row in dated] + [row[1] for row in undated]


def list_inspections(storage, incoming_dir, session_id, query, *, image_id, page_cache=None):
    """Return a paginated inspection list with summary counts and cursor snapshot."""
    filter_val, limit_val, cursor = parse_inspections_query(query)
    cache = page_cache if page_cache is not None else get_page_cache()
    if cursor is not None:
        return cache.get_page(
            session_id=session_id,
            path='/api/v1/inspections',
            filter_val=filter_val,
            limit=limit_val,
            cursor=cursor,
        )

    cols = ', '.join(_PROGRESS_READING_COLUMNS)
    with storage.connection() as conn:
        insp_rows = conn.execute(
            'SELECT inspection_id FROM inspections LIMIT ?',
            (_MAX_INSPECTIONS + 1,),
        ).fetchall()
        if len(insp_rows) > _MAX_INSPECTIONS:
            raise APIError(422, 'validation_failed')
        reading_rows = conn.execute(
            f"SELECT inspection_id, {cols} FROM meter_readings "
            f"WHERE inspection_id IS NOT NULL AND inspection_id != '' "
            f"ORDER BY id DESC LIMIT ?",
            (_MAX_PROGRESS_READINGS + 1,),
        ).fetchall()
        if len(reading_rows) > _MAX_PROGRESS_READINGS:
            raise APIError(422, 'validation_failed')

    insp_ids = {row[0] for row in insp_rows}
    readings_by_id = {}
    for row in reading_rows:
        ins_id = row[0]
        reading = SimpleNamespace(**dict(zip(_PROGRESS_READING_COLUMNS, row[1:])))
        readings_by_id.setdefault(ins_id, []).append(reading)

    all_ids = insp_ids | set(readings_by_id.keys())
    if len(all_ids) > _MAX_INSPECTIONS:
        raise APIError(422, 'validation_failed')

    hashes = received_hashes(storage, incoming_dir)
    all_items = []
    for ins_id in all_ids:
        ins_readings = readings_by_id.get(ins_id, [])
        try:
            progress = build_inspection_progress(storage, incoming_dir, ins_id, ins_readings, hashes, image_id=image_id)
            item = build_inspection_list_item(progress, len(ins_readings))
        except APIError:
            raise
        except (ValueError, TypeError, KeyError, AttributeError):
            raise APIError(503, 'data_invalid') from None
        all_items.append(item)

    sorted_items = _sort_inspection_items(all_items)
    action_items = [item for item in sorted_items if item['summary']['needs_action']]
    selected_items = sorted_items if filter_val == 'all' else action_items

    return cache.create_page(
        session_id=session_id,
        path='/api/v1/inspections',
        filter_val=filter_val,
        limit=limit_val,
        items=selected_items,
        all_total=len(sorted_items),
        action_total=len(action_items),
    )


def dispatch_inspection(api, method, url, session_id=None, body=None):
    """Dispatch authenticated /api/v1/inspections* requests."""
    match = re.fullmatch(r'/api/v1/inspections/([^/]+)/csv(/save)?', url.path)
    if match and method == 'POST':
        if url.query:
            raise APIError(400, 'invalid_request')
        from pc_api.inspection_csv import inspection_csv
        inspection_id = validate_inspection_id(unquote(match.group(1)))
        with _open_read_adapter(api.storage) as adapter:
            _ensure_inspection_exists(adapter, inspection_id)
            return inspection_csv(adapter, inspection_id, body, bool(match.group(2)))
    if method != 'GET':
        raise APIError(400, 'invalid_request')
    if url.path == '/api/v1/inspections':
        raw_qs = parse_qs(url.query, keep_blank_values=True)
        if set(raw_qs) - {'filter', 'limit', 'cursor'} or any(len(v) != 1 for v in raw_qs.values()):
            raise APIError(400, 'invalid_request')
        query = {k: v[0] for k, v in raw_qs.items()}
        with _open_read_adapter(api.storage) as adapter:
            return 200, list_inspections(adapter, api.incoming_dir, session_id, query, image_id=api.image_id), None
    if url.query:
        raise APIError(400, 'invalid_request')
    for pattern, handler in (
        (_STATUS_PATH_RE, get_inspection_status),
        (_PROGRESS_PATH_RE, get_inspection_progress),
    ):
        match = pattern.fullmatch(url.path)
        if match:
            inspection_id = validate_inspection_id(unquote(match.group(1)))
            with _open_read_adapter(api.storage) as adapter:
                kwargs = {'image_id': api.image_id} if handler is get_inspection_progress else {}
                return 200, handler(adapter, api.incoming_dir, inspection_id, **kwargs), None
    raise APIError(404, 'not_found')
