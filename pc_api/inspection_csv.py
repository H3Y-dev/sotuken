from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory

from manager.export import export_inspection_csv, filter_readings, latest_per_device
from manager.storage import MeterReading
from pc_api.server import APIError, READING_COLUMNS, SELECT_READINGS


def inspection_csv(storage, inspection_id, body, save):
    if not isinstance(body, dict) or set(body) - {'device_name', 'date_from', 'date_to'}:
        raise APIError(400, 'invalid_request')
    if any(not isinstance(v, str) or len(v) > 256 for v in body.values()):
        raise APIError(422, 'validation_failed')
    filters = dict(body)
    try:
        for key in ('date_from', 'date_to'):
            if key in filters:
                value = filters[key]
                if len(value) != 10 or date.fromisoformat(value).isoformat() != value:
                    raise ValueError()
                filters[key] = date.fromisoformat(value)
        if filters.get('date_from') and filters.get('date_to') and filters['date_from'] > filters['date_to']:
            raise ValueError()
    except ValueError:
        raise APIError(422, 'validation_failed') from None
    with storage.connection() as conn:
        rows = conn.execute(SELECT_READINGS + ' WHERE inspection_id = ? ORDER BY id DESC LIMIT 10001', (inspection_id,)).fetchall()
    if len(rows) > 10000:
        raise APIError(422, 'validation_failed')
    readings = [MeterReading(**dict(zip(READING_COLUMNS, row)), raw_data=None) for row in rows]
    try:
        selected = latest_per_device(filter_readings(readings, inspection_id=inspection_id, **filters))
    except (ValueError, TypeError, AttributeError):
        raise APIError(503, 'data_invalid') from None
    if save:
        return 200, {'filename': Path(export_inspection_csv(selected)).name}, None
    with TemporaryDirectory() as directory:
        path = Path(export_inspection_csv(selected, out_dir=directory))
        return 200, (path.read_bytes(), path.name), 'text/csv; charset=utf-8'
