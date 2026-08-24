import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from manager import MeterManager


class TestMeterManager(unittest.TestCase):

    def setUp(self):
        self.manager = MeterManager(":memory:")

    def test_process_image_success(self):
        def mock_reader_ok(img_path):
            return {
                "stage": "ok",
                "value": 50.0,
                "ratio": 0.5,
                "angle_deg": 90.0,
                "error": None,
            }

        result = self.manager.process_image(
            image_path="/tmp/test.jpg",
            device_name="Gauge01",
            reader_func=mock_reader_ok,
        )

        self.assertIsNotNone(result.id)
        self.assertEqual(result.device_name, "Gauge01")
        self.assertEqual(result.value, 50.0)
        self.assertEqual(result.stage, "ok")

    def test_formatting_methods(self):
        def mock_reader_ok(img_path):
            return {"stage": "ok", "value": 42.5, "error": None}

        def mock_reader_ng(img_path):
            return {"stage": "needle", "value": None, "error": "Not found"}

        self.manager.process_image("/tmp/1.jpg", "GaugeA", mock_reader_ok)
        self.manager.process_image("/tmp/2.jpg", "GaugeB", mock_reader_ng)

        # CLI整形のテスト
        cli_output = self.manager.format_history_for_cli()
        self.assertIn("GaugeA", cli_output)
        self.assertIn("42.50", cli_output)
        self.assertIn("N/A", cli_output)

        # UI整形のテスト
        ui_output = self.manager.format_history_for_ui()
        self.assertEqual(len(ui_output), 2)
        self.assertEqual(ui_output[0]["status"], "FAILED")  # 降順のため先頭はNGデータ
        self.assertEqual(ui_output[1]["status"], "SUCCESS")


if __name__ == "__main__":
    unittest.main()