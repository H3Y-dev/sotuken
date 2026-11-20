import http.client
import json
from pathlib import Path
from unittest.mock import patch

from test_pc_inspection_status import InspectionStatusAPITests
from manager.export import export_inspection_csv, filter_readings, latest_per_device


class InspectionCSVTests(InspectionStatusAPITests):
    def setUp(self):
        super().setUp()
        with self.storage.connection() as conn:
            for name, stamp in [('A', '2026-11-18T09:00:00'), ('A', '2026-11-19T09:00:00'), ('B', '2026-11-18T10:00:00')]:
                conn.execute('INSERT INTO meter_readings (timestamp, device_name, value, stage, image_path, inspection_id) VALUES (?, ?, ?, ?, ?, ?)', (stamp, name, 12, 'done', 'image.png', 'I-1'))

    def post(self, payload=b'{}', suffix='', headers=None, auth=True):
        conn = http.client.HTTPConnection('127.0.0.1', self.api.port, timeout=3)
        h = {'Content-Type': 'application/json', 'Origin': f'http://127.0.0.1:{self.api.port}', 'X-CSRF-Token': self.csrf_token}
        if auth:
            h['Cookie'] = self.session_cookie
        h.update(headers or {})
        conn.request('POST', '/api/v1/inspections/I-1/csv' + suffix, body=payload, headers=h)
        res = conn.getresponse()
        result = (res.status, res.read(), dict(res.getheaders()))
        conn.close()
        return result

    def test_bytes_filters_and_empty(self):
        for filters in ({}, {'device_name': 'A', 'date_to': '2026-11-18'}, {'device_name': 'missing'}):
            status, data, headers = self.post(json.dumps(filters).encode())
            self.assertEqual(status, 200)
            parsed = dict(filters)
            if 'date_to' in parsed:
                from datetime import date
                parsed['date_to'] = date.fromisoformat(parsed['date_to'])
            rows = latest_per_device(filter_readings(self.api.storage.readings(), inspection_id='I-1', **parsed))
            expected = Path(export_inspection_csv(rows, out_dir=self.root)).read_bytes()
            self.assertEqual(data, expected)
            self.assertIn('filename*=', headers['Content-Disposition'])

    def test_validation_and_security(self):
        for payload, status in [(b'{"x":1}', 400), (b'{"device_name":"a","device_name":"b"}', 400), (b'{"date_from":"2026-02-30"}', 422), (b'{"date_from":"2026-11-19","date_to":"2026-11-18"}', 422), (json.dumps({'device_name':'x'*257}).encode(), 422), (b' '*4097, 413)]:
            self.assertEqual(self.post(payload)[0], status)
        self.assertEqual(self.post(auth=False)[0], 401)
        self.assertEqual(self.post(headers={'X-CSRF-Token': 'bad'})[0], 403)
        self.assertEqual(self.post(headers={'Origin': 'http://evil'})[0], 403)

    def test_save_collision_and_download_cleanup(self):
        with patch('manager.export._documents_dir', return_value=self.root):
            first = json.loads(self.post(suffix='/save')[1])['filename']
            second = json.loads(self.post(suffix='/save')[1])['filename']
            self.assertNotEqual(first, second)
            self.assertTrue((self.root / 'メーター点検' / first).exists())
        import pc_api.inspection_csv as module
        from tempfile import TemporaryDirectory
        with TemporaryDirectory(dir=self.root) as base:
            with patch.object(module, 'TemporaryDirectory', side_effect=lambda: TemporaryDirectory(dir=base)):
                self.assertEqual(self.post()[0], 200)
            self.assertEqual(list(Path(base).iterdir()), [])

    def test_reading_limit(self):
        with self.storage.connection() as conn:
            conn.executemany(
                "INSERT INTO meter_readings (timestamp, device_name, value, stage, image_path, inspection_id) VALUES (?, ?, ?, ?, ?, ?)",
                [('2026-11-18T09:00:00', 'A', 1, 'done', 'x', 'I-1')] * 9997)
        self.assertEqual(self.post()[0], 200)
        with self.storage.connection() as conn:
            conn.execute("INSERT INTO meter_readings (timestamp, device_name, value, stage, image_path, inspection_id) VALUES (?, ?, ?, ?, ?, ?)", ('2026-11-18T09:00:00', 'A', 1, 'done', 'x', 'I-1'))
        self.assertEqual(self.post()[0], 422)
