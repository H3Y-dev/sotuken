"""Device registry routes for PC API."""
from urllib.parse import unquote

from manager.devices import (
    DeviceConflict,
    create_device,
    list_devices,
    update_device,
)
from pc_api.server import APIError

_MAX_DEVICES = 1000
_INPUT_KEYS = frozenset((
    'device_name',
    'unit',
    'min_value',
    'max_value',
    'tolerance_min',
    'tolerance_max',
))
_CREATE_KEYS = _INPUT_KEYS | frozenset(('device_id',))


def _device_dto(row: dict) -> dict:
    return {
        'device_id': row['device_id'],
        'device_name': row['device_name'],
        'unit': row['unit'],
        'min_value': row['min_value'],
        'max_value': row['max_value'],
        'tolerance_min': row['tolerance_min'],
        'tolerance_max': row['tolerance_max'],
        'provisional': bool(row['provisional']),
    }


def dispatch_devices(storage, method, path, body):
    """Dispatch authenticated /api/v1/devices* requests."""
    if path == '/api/v1/devices':
        if method == 'GET':
            rows = list_devices(storage, limit=_MAX_DEVICES + 1)
            if len(rows) > _MAX_DEVICES:
                raise APIError(422, 'validation_failed')
            return 200, {'items': [_device_dto(row) for row in rows]}, None
        if method == 'POST':
            if not isinstance(body, dict) or set(body) != _CREATE_KEYS:
                raise APIError(400, 'invalid_request')
            fields = {key: body[key] for key in _INPUT_KEYS}
            try:
                row = create_device(storage, body['device_id'], fields)
            except DeviceConflict:
                raise APIError(409, 'device_conflict') from None
            except ValueError:
                raise APIError(422, 'validation_failed') from None
            return 201, _device_dto(row), None
        raise APIError(400, 'invalid_request')

    if path.startswith('/api/v1/devices/id-'):
        raw_id = path.removeprefix('/api/v1/devices/id-')
        if '/' in raw_id:
            raise APIError(404, 'not_found')
        if method != 'PUT':
            raise APIError(400, 'invalid_request')
        if not isinstance(body, dict) or set(body) != _INPUT_KEYS:
            raise APIError(400, 'invalid_request')
        device_id = unquote(raw_id)
        try:
            row = update_device(storage, device_id, body)
        except KeyError:
            raise APIError(404, 'not_found') from None
        except ValueError:
            raise APIError(422, 'validation_failed') from None
        return 200, _device_dto(row), None

    raise APIError(404, 'not_found')
