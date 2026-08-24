import os
import sys
import unittest
from unittest.mock import MagicMock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from manager import MeterManager


class TestIntegrationReadMeterAndManager(unittest.TestCase):

    def setUp(self):
        # テスト用のインメモリDBを持つManagerを初期化
        self.manager = MeterManager(":memory:")

    def test_integration_successful_reading(self):
        # 画像認識モジュール (read_meter) の戻り値をモック化
        mock_read_meter = MagicMock(
            return_value={
                "stage": "ok",
                "value": 75.2,
                "ratio": 0.752,
                "angle_deg": 135.0,
                "error": None,
            }
        )

        image_path = "tests/fixtures/sample_meter.jpg"
        device_name = "Pressure_Gauge_01"

        # Manager経由で画像処理〜DB保存を実行
        result = self.manager.process_image(
            image_path=image_path,
            device_name=device_name,
            reader_func=mock_read_meter,
        )

        # 1. read_meter が正しい引数で呼び出されたか検証
        mock_read_meter.assert_called_once_with(image_path)

        # 2. 返却された MeterReading オブジェクトの属性を検証
        self.assertIsNotNone(result.id)
        self.assertEqual(result.device_name, device_name)
        self.assertEqual(result.value, 75.2)
        self.assertEqual(result.stage, "ok")
        self.assertEqual(result.image_path, image_path)

        # 3. DBから取得した履歴データと整合しているか検証
        history = self.manager.get_history()
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0].id, result.id)

    def test_integration_failed_reading(self):
        # 画像認識失敗（針が見つからない場合）のモック
        mock_read_meter = MagicMock(
            return_value={
                "stage": "needle",
                "value": None,
                "ratio": None,
                "angle_deg": None,
                "error": "Needle detection failed",
            }
        )

        image_path = "tests/fixtures/bad_meter.jpg"
        device_name = "Pressure_Gauge_02"

        result = self.manager.process_image(
            image_path=image_path,
            device_name=device_name,
            reader_func=mock_read_meter,
        )

        # 失敗時のデータが適切に処理・保存されたか検証
        self.assertIsNotNone(result.id)
        self.assertIsNone(result.value)
        self.assertEqual(result.stage, "needle")

        # UI向け出力の確認
        ui_data = self.manager.format_history_for_ui()
        self.assertEqual(ui_data[0]["status"], "FAILED")


if __name__ == "__main__":
    unittest.main()