"""Read-only inspection status routes for PC API."""
from contextlib import closing, contextmanager
import re
from types import SimpleNamespace
from urllib.parse import unquote

from manager.routes import get_manifest, inspection_status, received_hashes, validate_id
from pc_api.inspection_progress import build_inspection_progress
from pc_api.server import APIError

_MAX_MANIFEST_PHOTOS = 10000
_MAX_PROGRESS_READINGS = 10000
_STATUS_PATH_RE = re.compile(r'/api/v1/inspections/([^/]+)/status')
_PROGRESS_PATH_RE = re.compile(r'/api/v1/inspections/([^/]+)/progress')
_PROGRESS_READING_COLUMNS = (
    'id', 'device_id', 'device_name', 'device_id_source', 'value', 'status',
    'stage', 'image_sha256', 'captured_at', 'received_at', 'timestamp',
    'inspection_name', 'route_id',
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


def get_inspection_progress(storage, incoming_dir, inspection_id):
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
        return build_inspection_progress(storage, incoming_dir, inspection_id, readings, hashes)
    except APIError:
        raise
    except (ValueError, TypeError, KeyError, AttributeError):
        raise APIError(503, 'data_invalid') from None


def dispatch_inspection(api, method, url):
    """Dispatch authenticated /api/v1/inspections* requests."""
    if method != 'GET' or url.query:
        raise APIError(400, 'invalid_request')
    for pattern, handler in (
        (_STATUS_PATH_RE, get_inspection_status),
        (_PROGRESS_PATH_RE, get_inspection_progress),
    ):
        match = pattern.fullmatch(url.path)
        if match:
            inspection_id = validate_inspection_id(unquote(match.group(1)))
            with _open_read_adapter(api.storage) as adapter:
                return 200, handler(adapter, api.incoming_dir, inspection_id), None
    raise APIError(404, 'not_found')
