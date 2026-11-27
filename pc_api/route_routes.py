"""Saved route and route QR routes for PC API."""
import io
from urllib.parse import unquote

from manager.routes import (
    delete_route,
    get_route,
    list_routes,
    route_qr_payload,
    save_route,
    validate_id,
)
from pc_api.server import APIError

_ROUTE_PREFIX = '/api/v1/routes'
_INPUT_KEYS = frozenset(('name', 'devices'))
_DEVICE_KEYS = frozenset(('id', 'name'))


def _parse_route_id(raw_id):
    route_id = unquote(raw_id)
    if route_id in ('.', '..'):
        raise APIError(400, 'invalid_request')
    try:
        validate_id(route_id)
    except ValueError:
        raise APIError(400, 'invalid_request') from None
    return route_id


def _validate_body(body):
    if not isinstance(body, dict) or set(body) != _INPUT_KEYS:
        raise APIError(400, 'invalid_request')
    if not isinstance(body['devices'], list):
        raise APIError(400, 'invalid_request')
    for device in body['devices']:
        if not isinstance(device, dict) or set(device) != _DEVICE_KEYS:
            raise APIError(400, 'invalid_request')


def _save(storage, name, devices, route_id=None):
    try:
        return save_route(storage, name, devices, route_id=route_id)
    except (ValueError, TypeError):
        raise APIError(422, 'validation_failed') from None


def _route_dto(route):
    return {**route, 'qr_payload': route_qr_payload(route)}


def dispatch_routes(storage, method, path, body):
    """Dispatch authenticated /api/v1/routes* requests."""
    if path == _ROUTE_PREFIX:
        if method == 'GET':
            result = list_routes(storage)
            return 200, {'items': result['routes']}, None
        if method == 'POST':
            _validate_body(body)
            return 201, _route_dto(_save(storage, body['name'], body['devices'])), None
        raise APIError(400, 'invalid_request')

    if not path.startswith(_ROUTE_PREFIX + '/'):
        raise APIError(404, 'not_found')
    remainder = path[len(_ROUTE_PREFIX) + 1:]

    if method == 'GET' and remainder.endswith('/qr') and '/' not in remainder[:-3]:
        route = get_route(storage, _parse_route_id(remainder[:-3]))
        if route is None:
            raise APIError(404, 'not_found')
        payload = route_qr_payload(route)
        if payload is None:
            raise APIError(422, 'validation_failed')
        import qrcode
        buf = io.BytesIO()
        qrcode.make(payload).save(buf, format='PNG')
        return 200, buf.getvalue(), 'image/png'

    if '/' in remainder:
        raise APIError(404, 'not_found')

    if method == 'GET':
        route = get_route(storage, _parse_route_id(remainder))
        if route is None:
            raise APIError(404, 'not_found')
        return 200, _route_dto(route), None

    if method == 'PUT':
        route_id = _parse_route_id(remainder)
        if get_route(storage, route_id) is None:
            raise APIError(404, 'not_found')
        _validate_body(body)
        return 200, _route_dto(_save(storage, body['name'], body['devices'], route_id)), None

    if method == 'DELETE':
        route_id = _parse_route_id(remainder)
        if get_route(storage, route_id) is None:
            raise APIError(404, 'not_found')
        delete_route(storage, route_id)
        return 204, None, None

    raise APIError(400, 'invalid_request')
