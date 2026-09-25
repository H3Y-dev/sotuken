import io
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import main


class TestMainCli(unittest.TestCase):

    def test_read_meter_routes_to_pipeline_caller(self):
        """main.read_meter がダミー値 42.5 ではなく pipeline_caller.execute_pipeline を経由することを検証"""
        with patch("main.execute_pipeline") as mock_execute:
            mock_execute.return_value = {
                "stage": "ok",
                "value": 88.0,
                "ratio": 0.88,
                "angle_deg": 210.0,
                "error": None,
            }

            result = main.read_meter("dummy_meter.jpg")

            mock_execute.assert_called_once_with("dummy_meter.jpg", use_vlm=False)
            self.assertEqual(result["value"], 88.0)
            self.assertNotEqual(result["value"], 42.5)

    def test_main_cli_processes_image_via_real_pipeline(self):
        """CLI の --image 指定時に pipeline_caller が呼ばれ、読み取り結果が処理されることを検証"""
        with tempfile.TemporaryDirectory() as temp_dir:
            img_path = os.path.join(temp_dir, "test_gauge.jpg")
            with open(img_path, "wb") as f:
                f.write(b"dummy image data")
            db_path = os.path.join(temp_dir, "test.db")

            with patch("main.execute_pipeline") as mock_execute:
                mock_execute.return_value = {
                    "stage": "ok",
                    "value": 77.5,
                    "ratio": 0.775,
                    "angle_deg": 180.0,
                    "error": None,
                }

                stdout_buf = io.StringIO()
                test_args = [
                    "main.py",
                    "--image",
                    img_path,
                    "--device",
                    "CLI_Device",
                    "--db",
                    db_path,
                ]
                with patch.object(sys, "argv", test_args), redirect_stdout(stdout_buf):
                    main.main()

                mock_execute.assert_called_once_with(img_path, use_vlm=False)
                output = stdout_buf.getvalue()
                self.assertIn("CLI_Device", output)
                self.assertIn("77.5", output)
                self.assertNotIn("42.5", output)


if __name__ == "__main__":
    unittest.main()
