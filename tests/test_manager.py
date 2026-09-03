import unittest

from manager.manager import MeterManager


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

        # process_image は閾値判定を含む dict を返す。
        # 保存された記録そのものは "reading" キーに入っている
        self.assertEqual(result["val"], 50.0)
        self.assertEqual(result["stage"], "ok")
        self.assertFalse(result["is_alert"])

        reading = result["reading"]
        self.assertIsNotNone(reading.id)
        self.assertEqual(reading.device_name, "Gauge01")
        self.assertEqual(reading.value, 50.0)
        self.assertEqual(reading.stage, "ok")

    def test_threshold_alert(self):
        """閾値を超えた場合にアラートが立ち、範囲内なら立たないこと"""
        def mock_reader(value):
            def _reader(img_path):
                return {"stage": "ok", "value": value, "error": None}
            return _reader

        over = self.manager.process_image(
            "/tmp/over.jpg", "GaugeA", mock_reader(120.0), threshold_max=100.0)
        self.assertTrue(over["is_alert"])
        self.assertIn("100.0", over["alert_message"])

        under = self.manager.process_image(
            "/tmp/under.jpg", "GaugeA", mock_reader(5.0), threshold_min=10.0)
        self.assertTrue(under["is_alert"])

        normal = self.manager.process_image(
            "/tmp/ok.jpg", "GaugeA", mock_reader(50.0),
            threshold_max=100.0, threshold_min=10.0)
        self.assertFalse(normal["is_alert"])
        self.assertEqual(normal["alert_message"], "")

        # 読み取り失敗（value=None）では閾値判定を行わない
        failed = self.manager.process_image(
            "/tmp/ng.jpg", "GaugeA", mock_reader(None), threshold_max=1.0)
        self.assertFalse(failed["is_alert"])

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
