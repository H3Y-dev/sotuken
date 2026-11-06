import json
import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch

from manager.storage import Storage
from manager.routes import (save_route, get_route, list_routes, delete_route,
                            route_qr_payload, save_manifest, inspection_status,
                            route_progress)


class RoutesManifestTest(unittest.TestCase):
    def setUp(self):
        self.storage = Storage(':memory:')

    def manifest(self):
        return dict(v=1, inspection_id='I-1', inspection_name='巡回', route_id=None,
                    operator='', place='', started_at='2026-11-06T01:00:00Z',
                    completed_at='2026-11-06T02:00:00Z', missing=[], extra=[],
                    photos=[dict(file_name='a.jpg', sha256='a' * 64, device_id='A',
                                 device_id_source='manual', captured_at='2026-11-06T01:10:00Z')])

    def test_route_crud_and_order(self):
        route = save_route(self.storage, '巡回', [{'id': 'B', 'name': 'B計'}, {'id': 'A', 'name': 'A計'}])
        self.assertEqual([d['id'] for d in get_route(self.storage, route['route_id'])['devices']], ['B', 'A'])
        self.assertEqual(list_routes(self.storage)['routes'][0]['count'], 2)
        route = save_route(self.storage, '編集', route['devices'][::-1], route['route_id'])
        self.assertEqual(route['devices'][0]['id'], 'A')
        delete_route(self.storage, route['route_id'])
        self.assertIsNone(get_route(self.storage, route['route_id']))

    def test_route_validation_and_qr(self):
        with self.assertRaises(ValueError):
            save_route(self.storage, '巡回', [{'id': '日本語', 'name': '計器'}])
        route = save_route(self.storage, '巡回', [{'id': 'A', 'name': '計器'}])
        self.assertEqual(json.loads(route_qr_payload(route).split(':', 1)[1]), route)
        route['devices'] *= 100
        self.assertIsNone(route_qr_payload(route))

    def test_manifest_before_photo_and_overwrite(self):
        self.assertEqual(inspection_status(self.storage, 'I-1')['state'], '受信中')
        self.assertEqual(save_manifest(self.storage, 'I-1', self.manifest())['missing_photos'], ['a.jpg'])
        self.storage.save_reading('a.jpg', '計器', {'inspection_id': 'I-1'}, image_sha256='a' * 64)
        self.assertEqual(inspection_status(self.storage, 'I-1')['state'], '完了')
        manifest = self.manifest()
        manifest['photos'].append(dict(manifest['photos'][0], file_name='b.jpg', sha256='b' * 64))
        self.assertEqual(save_manifest(self.storage, 'I-1', manifest)['matched'], 1)
        self.assertEqual(inspection_status(self.storage, 'I-1')['missing_photos'], ['b.jpg'])

    def test_manifest_validation(self):
        for field, value in [('v', True), ('inspection_id', 'other'), ('photos', [{}]), ('missing', [12])]:
            with self.subTest(field=field), self.assertRaises(ValueError):
                save_manifest(self.storage, 'I-1', dict(self.manifest(), **{field: value}))

    def test_progress_uses_photos_over_claims(self):
        route = dict(devices=[dict(id='A', name='A計'), dict(id='B', name='B計')])
        rows = route_progress(route, [dict(device_id='A'), dict(device_id='Z')],
                              dict(missing=['A'], extra=['A', 'Y']))
        self.assertEqual([(r['機器ID'], r['撮影状態']) for r in rows],
                         [('A', '撮影済み'), ('B', '未撮影'), ('Z', '追加'), ('Y', '追加（未着）')])

    def test_old_reading(self):
        self.storage.save_reading('old.jpg', '旧機器', {})
        self.assertIsNone(self.storage.get_all_readings()[0].route_id)

    def test_received_file_before_ocr_is_hashed_once_and_invalidated(self):
        import hashlib
        from manager.routes import arrived_manifest_devices
        from manager.batch import calculate_file_hash
        with tempfile.TemporaryDirectory() as directory:
            image = Path(directory) / 'renamed.jpg'
            manifest = self.manifest()
            manifest['photos'][0]['sha256'] = hashlib.sha256(b'image').hexdigest()
            save_manifest(self.storage, 'I-1', manifest, directory)
            image.write_bytes(b'image')
            with patch('manager.batch.calculate_file_hash', wraps=calculate_file_hash) as calculate:
                self.assertEqual(inspection_status(self.storage, 'I-1', directory)['state'], '完了')
                self.assertEqual(inspection_status(self.storage, 'I-1', directory)['state'], '完了')
                self.assertEqual(calculate.call_count, 1)
                self.assertEqual(arrived_manifest_devices(self.storage, manifest, [], directory), [dict(device_id='A')])
                image.write_bytes(b'changed image')
                self.assertEqual(inspection_status(self.storage, 'I-1', directory)['state'], '不足あり')
                self.assertEqual(calculate.call_count, 2)

    def test_route_id_sidecar_storage_reprocess_and_export(self):
        from manager.sidecar import load_sidecar
        from manager.receiver import validate_sidecar_metadata
        from manager.reprocess import reprocess_image
        from manager.export import export_to_csv, export_to_jsonl
        import csv
        import hashlib
        with tempfile.TemporaryDirectory() as directory:
            image = Path(directory) / 'a.jpg'
            from PIL import Image
            Image.new('RGB', (12, 12)).save(image)
            image.with_suffix('.json').write_text(json.dumps(dict(local_id='a', route_id='R-1')), encoding='utf-8')
            self.assertEqual(load_sidecar(str(image)).route_id, 'R-1')
            for value, expected in [('R-1', 'R-1'), ('不正', None), (None, None), ('x' * 65, None)]:
                metadata = dict(route_id=value)
                self.assertIsNone(validate_sidecar_metadata(metadata))
                self.assertEqual(metadata['route_id'], expected)
            self.storage.save_reading(str(image), '計器', dict(route_id='R-1'), image_sha256=hashlib.sha256(image.read_bytes()).hexdigest())
            with patch('manager.reprocess.meter_pipeline.read_meter', return_value={'stage': 'ok', 'value': 1}):
                reprocess_image(self.storage, str(image), 'test')
            self.assertEqual([r.route_id for r in self.storage.get_all_readings()], ['R-1', 'R-1'])
            csv_path, json_path = Path(directory) / 'readings.csv', Path(directory) / 'readings.jsonl'
            export_to_csv(self.storage.get_all_readings(), csv_path)
            export_to_jsonl(self.storage.get_all_readings(), json_path)
            with csv_path.open(encoding='utf-8-sig', newline='') as stream:
                self.assertEqual(next(csv.DictReader(stream))['route_id'], 'R-1')
            self.assertEqual(json.loads(json_path.read_text(encoding='utf-8').splitlines()[0])['route_id'], 'R-1')

    def test_route_id_late_sidecar(self):
        from manager.ingest import apply_sidecar
        from manager.sidecar import SidecarMetadata
        # Same update path as the P1 inspection metadata, without altering device identity.
        self.storage.save_reading('a.jpg', '計器', {}, image_sha256='a' * 64)
        apply_sidecar(self.storage, 'a' * 64, SidecarMetadata(route_id='R-1'))
        self.assertEqual(self.storage.get_all_readings()[0].route_id, 'R-1')


if __name__ == '__main__':
    unittest.main()
