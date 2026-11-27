"""Manual image reading endpoint for PC API (POST /api/v1/manual-readings)."""
import email.policy
from email.parser import BytesParser
import math
import os
from pathlib import Path
import tempfile

from manager.qr_label import validate_device_name
from pc_api.server import APIError

_ALLOWED_EXTENSIONS = frozenset(('.jpg', '.jpeg', '.png'))
_TEXT_FIELDS = frozenset(('device_name', 'threshold_min', 'threshold_max'))
_ALLOWED_FIELDS = _TEXT_FIELDS | {'image'}


def _parse_multipart(content_type, raw):
    if not content_type or not content_type.lower().startswith('multipart/form-data'):
        raise APIError(400, 'invalid_request')
    try:
        message = BytesParser(policy=email.policy.default).parsebytes(
            b'Content-Type: ' + content_type.encode('latin-1')
            + b'\r\nMIME-Version: 1.0\r\n\r\n' + raw
        )
    except (ValueError, TypeError):
        raise APIError(400, 'invalid_request') from None
    if not message.is_multipart():
        raise APIError(400, 'invalid_request')

    fields, files, seen = {}, {}, set()
    for part in message.iter_parts():
        name = part.get_param('name', header='content-disposition')
        if not isinstance(name, str) or not name:
            raise APIError(400, 'invalid_request')
        if name in seen:
            raise APIError(400, 'invalid_request')
        seen.add(name)
        if name not in _ALLOWED_FIELDS:
            raise APIError(400, 'invalid_request')
        if part.is_multipart():
            raise APIError(400, 'invalid_request')
        filename = part.get_filename()
        try:
            payload = part.get_payload(decode=True)
        except (ValueError, TypeError):
            raise APIError(400, 'invalid_request') from None
        if payload is None:
            raise APIError(400, 'invalid_request')
        if name == 'image':
            if filename is None:
                raise APIError(400, 'invalid_request')
            files[name] = (filename, payload)
        else:
            if filename is not None:
                raise APIError(400, 'invalid_request')
            try:
                fields[name] = payload.decode('utf-8')
            except UnicodeError:
                raise APIError(400, 'invalid_request') from None
    return fields, files


def _parse_float(fields, key, default):
    if key not in fields:
        return default
    try:
        value = float(fields[key])
    except (TypeError, ValueError):
        raise APIError(422, 'validation_failed') from None
    if not math.isfinite(value):
        raise APIError(422, 'validation_failed')
    return value


def dispatch_manual_reading(api, body):
    """Handle an authenticated multipart manual-reading upload."""
    if not isinstance(body, tuple) or len(body) != 2:
        raise APIError(400, 'invalid_request')
    content_type, raw = body
    fields, files = _parse_multipart(content_type, raw)

    if 'device_name' not in fields:
        raise APIError(422, 'validation_failed')
    try:
        device_name = validate_device_name(fields['device_name'])
    except ValueError:
        raise APIError(422, 'validation_failed') from None

    threshold_min = _parse_float(fields, 'threshold_min', 0.0)
    threshold_max = _parse_float(fields, 'threshold_max', 40.0)
    if threshold_min > threshold_max:
        raise APIError(422, 'validation_failed')

    if 'image' not in files:
        raise APIError(400, 'invalid_request')
    filename, data = files['image']
    extension = os.path.splitext(filename)[1].lower()
    if extension not in _ALLOWED_EXTENSIONS:
        raise APIError(422, 'validation_failed')
    if not data:
        raise APIError(422, 'validation_failed')

    reader_func = api.reader_func
    if reader_func is None:
        from manager.pipeline_caller import execute_pipeline
        reader_func = execute_pipeline

    from manager.manager import MeterManager

    with tempfile.TemporaryDirectory() as temp_dir:
        temp_file = Path(temp_dir) / ('upload' + extension)
        temp_file.write_bytes(data)
        manager = MeterManager(str(api.storage.path))
        result = manager.process_image(
            image_path=str(temp_file),
            device_name=device_name,
            reader_func=reader_func,
            threshold_max=threshold_max,
            threshold_min=threshold_min,
            overlays_dir=str(api.overlays_dir),
            images_dir=str(api.images_dir),
        )

    saved = result.get('reading')
    row = api.storage.reading(saved.id) if saved is not None else None
    if row is None:
        row = saved
    if row is None:
        raise APIError(503, 'data_invalid')
    return 201, {
        'reading': api.dto(row),
        'is_alert': bool(result['is_alert']),
        'alert_message': result.get('alert_message'),
        'stage': result.get('stage'),
        'value': result.get('val'),
    }, None
