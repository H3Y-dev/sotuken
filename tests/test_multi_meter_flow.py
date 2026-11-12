import tempfile
import unittest
from unittest.mock import patch

from tools.multi_meter_flow import run_flow


class MultiMeterFlowTest(unittest.TestCase):
    def test_http_manifest_and_progress_without_ocr(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch('tools.multi_meter_flow.execute_pipeline',
                       return_value={'stage': 'ok', 'value': 12.5}) as pipeline:
                result = run_flow(directory, synthetic_fixtures=True)
            self.assertEqual(6, pipeline.call_count)
            self.assertEqual('受信中', result['before']['state'])
            self.assertEqual('完了', result['received']['state'])
            self.assertEqual(6, result['received']['matched'])
            self.assertEqual('完了', result['after']['state'])
            self.assertEqual(400, result['rejected_manifest']['status'])
            self.assertEqual('list', result['rejected_manifest']['original']['photos'][3]['device_id_source'])
            self.assertEqual('不足あり', result['missing_transport']['state'])
            self.assertEqual(5, result['missing_transport']['matched'])
            self.assertEqual([result['sent'][0]['file_name']], result['missing_transport']['missing_photos'])
            self.assertEqual(6, len(result['rows']))
            self.assertEqual(['FLOW-005'], [r['機器ID'] for r in result['progress']
                                          if r['撮影状態'] == '未撮影'])
            self.assertEqual(['FLOW-006'], [r['機器ID'] for r in result['progress']
                                          if r['撮影状態'] == '追加'])
            self.assertEqual(6, len(result['arrived_before_ocr']))
            self.assertEqual([], result['arrived_after_ocr'])
            self.assertTrue(all(r['inspection_id'] == 'I-MULTI-20261112' for r in result['rows']))
            self.assertEqual(['sidecar_qr'] * 3 + ['sidecar', 'sidecar_qr', 'pc_qr'],
                             [r['device_id_source'] for r in result['rows']])
            self.assertTrue(all(r['value'] == 12.5 for r in result['rows']))
            self.assertEqual(5, len(result['devices']))
            self.assertEqual(result['progress'], result['progress_before_ocr'])


if __name__ == '__main__':
    unittest.main()
