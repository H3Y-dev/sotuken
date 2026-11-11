import csv
import json
import sqlite3
import tempfile
import unittest
from contextlib import chdir, closing
from datetime import date
from pathlib import Path
from unittest import mock

from manager.batch import calculate_file_hash
from manager.export import (export_to_csv, export_to_jsonl, filter_readings,
                            inspection_devices, inspection_options)
from manager.ingest import apply_sidecar, ingest_result
from manager.receiver import validate_sidecar_metadata
from manager.reprocess import reprocess_image
from manager.sidecar import SidecarMetadata, load_sidecar
from manager.storage import MeterReading, Storage


class InspectionFilterTest(unittest.TestCase):
    def test_sidecar_validation_is_optional_and_non_rejecting(self):
        cases = [({}, (None, None)),
                 ({"inspection_id": "20261106T093000-k3f9", "inspection_name": " 巡回A "},
                  ("20261106T093000-k3f9", "巡回A")),
                 ({"inspection_id": "x" * 64, "inspection_name": "名" * 64}, ("x" * 64, "名" * 64))]
        for value in ["", "bad/id", " space ", "x" * 65, 42, [], "x\n"]:
            cases.append(({"inspection_id": value, "inspection_name": "巡回"}, (None, None)))
        for value in ["", "   ", "x" * 65, 42, [], "a\nb", "a\x7fb"]:
            cases.append(({"inspection_id": "id", "inspection_name": value}, ("id", None)))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "image.json"
            for data, expected in cases:
                with self.subTest(data=data):
                    self.assertIsNone(validate_sidecar_metadata(dict(data)))
                    path.write_text(json.dumps(data), encoding="utf-8")
                    metadata = load_sidecar(str(path))
                    self.assertEqual((metadata.inspection_id, metadata.inspection_name), expected)

    def test_legacy_migration(self):
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / "old.db")
            with closing(sqlite3.connect(path)) as conn, conn:
                conn.execute("CREATE TABLE meter_readings (id INTEGER PRIMARY KEY, timestamp TEXT, "
                             "device_name TEXT, value REAL, stage TEXT, image_path TEXT, raw_data_json TEXT)")
                conn.execute("INSERT INTO meter_readings VALUES (1, '2026-11-06', 'old', 1, 'ok', 'a.jpg', NULL)")
            storage = Storage(path)
            row = storage.get_all_readings()[0]
            self.assertEqual((row.inspection_id, row.inspection_name), (None, None))
            with storage.connection() as conn:
                self.assertIn('idx_meter_readings_inspection_id',
                              [row[1] for row in conn.execute('PRAGMA index_list(meter_readings)')])
            Storage(path)

    def test_ingest_late_sidecar_and_first_name(self):
        storage = Storage(':memory:')
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'meter.jpg'
            path.write_bytes(b'image')
            metadata = SidecarMetadata(inspection_id='round', inspection_name='最初')
            with mock.patch('manager.ingest.read_device_qr') as decode:
                decode.return_value.status = 'not_found'
                ingest_result(storage, str(path), metadata, {'stage': 'failed'},
                              str(Path(directory) / 'images'), str(Path(directory) / 'overlays'))
            row = storage.get_all_readings()[0]
            self.assertEqual((row.inspection_id, row.inspection_name), ('round', '最初'))
            storage.save_reading('meter2', 'b.jpg', {'inspection_id': 'round', 'inspection_name': '後の名前'})
            late_id = storage.save_reading('meter3', 'c.jpg', {}, image_sha256='late')
            apply_sidecar(storage, 'late', SidecarMetadata(inspection_id='round', inspection_name='別名'))
            apply_sidecar(storage, 'late', SidecarMetadata())
            rows = storage.get_all_readings()
            self.assertTrue(all(r.inspection_name == '最初' for r in rows))
            self.assertEqual(next(r for r in rows if r.id == late_id).inspection_id, 'round')

    def test_reprocess_preserves_inspection(self):
        storage = Storage(':memory:')
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'meter.jpg'
            path.write_bytes(b'image')
            storage.save_reading('meter', str(path), {'inspection_id': 'round', 'inspection_name': '巡回'},
                                 image_sha256=calculate_file_hash(str(path)))
            with mock.patch('manager.reprocess.cv2.imdecode', return_value=object()), mock.patch(
                    'meter_pipeline.read_meter', return_value={'stage': 'ok', 'value': 1}):
                reprocess_image(storage, str(path), 'v2')
            self.assertEqual([(r.inspection_id, r.inspection_name) for r in storage.get_all_readings()],
                             [('round', '巡回')] * 2)

    def test_late_first_name_and_conflicting_id_do_not_overwrite(self):
        storage = Storage(':memory:')
        storage.save_reading('meter', 'a.jpg', {'inspection_id': 'r'}, image_sha256='sha')
        apply_sidecar(storage, 'sha', SidecarMetadata(inspection_id='r', inspection_name='巡回'))
        apply_sidecar(storage, 'sha', SidecarMetadata(inspection_id='other', inspection_name='別'))
        row = storage.get_all_readings()[0]
        self.assertEqual((row.inspection_id, row.inspection_name), ('r', '巡回'))
        storage.save_reading('meter', 'b.jpg', {'inspection_id': 'r'})
        self.assertTrue(all(r.inspection_name == '巡回' for r in storage.get_all_readings()))

    def test_invalid_metadata_still_saves_record_and_rolls_back_failed_insert(self):
        storage = Storage(':memory:')
        storage.save_reading('meter', 'a.jpg', {'inspection_id': 'bad/id', 'inspection_name': 'bad'}, reading_id='a')
        self.assertIsNone(storage.get_all_readings()[0].inspection_id)
        with self.assertRaises(sqlite3.IntegrityError):
            storage.save_reading('meter', 'b.jpg', {'inspection_id': 'r', 'inspection_name': 'rollback'}, reading_id='a')
        storage.save_reading('meter', 'b.jpg', {'inspection_id': 'r', 'inspection_name': 'first'}, reading_id='b')
        self.assertEqual(storage.get_all_readings()[0].inspection_name, 'first')

    def test_combined_filter_options_and_exports(self):
        storage = Storage(':memory:')
        for name, day, inspection in [('A', '06', 'r'), ('A', '07', 'r'), ('B', '06', 'r'), ('A', '06', None)]:
            storage.save_reading(name, 'a.jpg', {'captured_at': f'2026-11-{day}T12:00:00Z',
                                               'inspection_id': inspection, 'inspection_name': '巡回' if inspection else None})
        readings = storage.get_all_readings()
        selected = filter_readings(readings, 'A', date(2026, 11, 6), date(2026, 11, 6), inspection_id='r')
        self.assertEqual(len(selected), 1)
        self.assertEqual(len(filter_readings(readings, inspection_id='')), 1)
        self.assertEqual(len(filter_readings(readings)), 4)
        self.assertEqual(inspection_options(readings), [('r', '巡回', 3)])
        with tempfile.TemporaryDirectory() as directory:
            csv_path, json_path = Path(directory) / 'out.csv', Path(directory) / 'out.jsonl'
            export_to_csv(selected, csv_path)
            export_to_jsonl(selected, json_path)
            with csv_path.open(encoding='utf-8-sig', newline='') as stream:
                reader = csv.DictReader(stream)
                self.assertEqual(reader.fieldnames[-3:], ['inspection_id', 'inspection_name', 'route_id'])
                csv_rows = list(reader)
            json_rows = [json.loads(line) for line in json_path.read_text(encoding='utf-8').splitlines()]
            self.assertEqual(len(csv_rows), len(selected))
            self.assertEqual(len(json_rows), len(selected))
            self.assertEqual(csv_rows[0]['inspection_id'], 'r')
            self.assertEqual(json_rows[0]['inspection_name'], '巡回')

    def test_device_summary_sources_missing_and_multiple_images(self):
        rows = [MeterReading('meter', 1, 'ok', 'a.jpg', device_id=device_id,
                             device_id_source=source, captured_at=f'2026-11-06T{hour}:00:00Z')
                for device_id, source, hour in [('A', 'sidecar_qr', '09'), ('A', 'manual', '10'),
                                                ('B', 'pc_qr', '11'), (None, None, '12'),
                                                ('C', 'qr', '13'), ('D', 'sidecar_manual', '14')]]
        summary = {r['機器ID']: r for r in inspection_devices(rows)}
        self.assertEqual(summary['A']['写真の枚数'], 2)
        self.assertEqual(summary['A']['最後の撮影時刻'], '2026-11-06T10:00:00Z')
        self.assertEqual(summary['A']['情報の出所'], 'スマホ(QR)、スマホ(手入力)')
        self.assertEqual(summary['B']['情報の出所'], 'PC(画像のQR)')
        self.assertEqual(summary['C']['情報の出所'], 'スマホ(QR)')
        self.assertEqual(summary['D']['情報の出所'], 'スマホ(手入力)')
        self.assertEqual(summary['機器IDなし']['情報の出所'], 'なし')
        self.assertEqual(summary['機器IDなし']['写真の枚数'], 1)


class InspectionFilterAppTest(unittest.TestCase):
    def test_selected_round_summary_combined_filter_and_export(self):
        from streamlit import cache_data, cache_resource
        from streamlit.testing.v1 import AppTest
        app_path = Path(__file__).resolve().parents[1] / 'app.py'
        cache_data.clear()
        cache_resource.clear()
        self.addCleanup(cache_data.clear)
        self.addCleanup(cache_resource.clear)
        with tempfile.TemporaryDirectory() as directory:
            storage = Storage(str(Path(directory) / 'manager.db'))
            for name, device_id, inspection_id, day in [('A', 'A', 'r', '06'), ('A', 'A', 'r', '07'),
                                                        ('B', None, 'r', '06'), ('A', None, None, '06')]:
                storage.save_reading(name, 'a.jpg', {'stage': 'ok', 'status': 'ok', 'value': 1,
                    'device_id': device_id, 'device_id_source': 'sidecar_qr' if device_id else None,
                    'captured_at': f'2026-11-{day}T09:00:00Z',
                    'inspection_id': inspection_id, 'inspection_name': '巡回' if inspection_id else None})
            with chdir(directory), mock.patch('manager.receiver.init_receiver_for_app',
                    return_value={'running': False, 'error': 'test'}):
                at = AppTest.from_file(str(app_path), default_timeout=30).run()
                self.assertFalse(at.exception)
                at.radio(key='page').set_value('点検').run()
                inspection = next(s for s in at.selectbox if s.label == '点検')
                inspection.select('r').run()
                self.assertFalse(at.exception)
                self.assertIn('この点検のメーター一覧', [s.value for s in at.subheader])
                table = at.dataframe[0].value
                self.assertEqual(table['写真の枚数'].tolist(), [2, 1])
                self.assertIn('機器IDなしの写真: 1枚', [c.value for c in at.caption])
                next(s for s in at.selectbox if s.label == '機器名').select('A').run()
                at.date_input[0].set_value(date(2026, 11, 6))
                at.date_input[1].set_value(date(2026, 11, 6)).run()
                next(b for b in at.button if b.label == 'CSVを書き出す').click().run()
                self.assertFalse(at.exception)
                with open('readings_export.csv', encoding='utf-8-sig', newline='') as stream:
                    exported = list(csv.DictReader(stream))
                self.assertEqual(len(exported), 1)
                self.assertEqual(exported[0]['inspection_id'], 'r')
                next(b for b in at.button if b.label == 'JSONLを書き出す').click().run()
                self.assertEqual(len(Path('readings_export.jsonl').read_text(encoding='utf-8').splitlines()), 1)
                inspection.select('').run()
                self.assertFalse(at.exception)
                self.assertNotIn('この点検のメーター一覧', [s.value for s in at.subheader])
                self.assertEqual(len(at.dataframe[0].value), 1)
                inspection.select(None).run()
                self.assertNotIn('この点検のメーター一覧', [s.value for s in at.subheader])
