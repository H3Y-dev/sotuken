import unittest
from manager.record import Reading, ImageTruth


class TestRecord(unittest.TestCase):
    def test_create_reading_and_imagetruth(self):
        # Readingインスタンスの作成
        reading = Reading(
            reading_id="12345678-1234-5678-1234-567812345678",
            local_id="terminal-001",
            captured_at="2026-09-08T10:00:00+09:00",
            received_at="2026-09-08T10:01:00+09:00",
            processed_at="2026-09-08T10:02:00+09:00",
            device_name="meter_A",
            value=12.5,
            unit="MPa",
            status="ok",
            input_method="auto",
            confidence=0.95,
            image_path="images/raw/meter_A.jpg",
            image_sha256="abcdef1234567890abcdef1234567890abcdef1234567890abcdef1234567890",
            failure_stage=None,
            failure_code=None,
            failure_detail=None,
            pipeline_version="v1.0.0",
            log_path="logs/meter_A.json",
            overlay_path="overlays/meter_A.png",
        )
        self.assertEqual(reading.reading_id, "12345678-1234-5678-1234-567812345678")
        self.assertEqual(reading.value, 12.5)
        self.assertEqual(reading.status, "ok")
        self.assertEqual(reading.input_method, "auto")

        # ImageTruthインスタンスの作成
        truth = ImageTruth(
            image_sha256="abcdef1234567890abcdef1234567890abcdef1234567890abcdef1234567890",
            operator_value=12.0,
            operator_note="現場確認済み",
            scale_min=0.0,
            scale_max=20.0,
            entered_at="2026-09-08T10:05:00+09:00",
        )
        self.assertEqual(truth.image_sha256, "abcdef1234567890abcdef1234567890abcdef1234567890abcdef1234567890")
        self.assertEqual(truth.operator_value, 12.0)

    def test_reading_failure_holds_none_value(self):
        # 読み取り失敗時に value が None のまま保持されること
        reading = Reading(
            reading_id="12345678-1234-5678-1234-567812345679",
            local_id="terminal-002",
            captured_at="2026-09-08T10:00:00+09:00",
            received_at="2026-09-08T10:01:00+09:00",
            processed_at="2026-09-08T10:02:00+09:00",
            device_name=None,
            value=None,
            unit="MPa",
            status="failed",
            input_method="auto",
            confidence=None,
            image_path="images/raw/meter_B.jpg",
            image_sha256="0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
            failure_stage="needle",
            failure_code="NEEDLE_NOT_FOUND",
            failure_detail="針が検出できませんでした",
            pipeline_version="v1.0.0",
            log_path="logs/meter_B.json",
            overlay_path=None,
        )
        self.assertIsNone(reading.value)
        self.assertEqual(reading.status, "failed")
        self.assertEqual(reading.failure_stage, "needle")

    def test_status_and_input_method_are_independent(self):
        # status と input_method に別々の値（例: 自動読み取り失敗だが人が手入力）を入れて混ざらないこと
        reading = Reading(
            reading_id="12345678-1234-5678-1234-567812345680",
            local_id="terminal-003",
            captured_at="2026-09-08T10:00:00+09:00",
            received_at="2026-09-08T10:01:00+09:00",
            processed_at="2026-09-08T10:02:00+09:00",
            device_name="meter_C",
            value=15.0,
            unit="MPa",
            status="failed",
            input_method="manual",
            confidence=None,
            image_path="images/raw/meter_C.jpg",
            image_sha256="1111222233334444555566667777888899990000aaaabbbbccccddddeeeeffff",
            failure_stage="scale",
            failure_code="SCALE_NOT_FOUND",
            failure_detail="目盛りが読めないため作業者が手入力",
            pipeline_version="v1.0.0",
            log_path="logs/meter_C.json",
            overlay_path=None,
        )
        self.assertEqual(reading.status, "failed")
        self.assertEqual(reading.input_method, "manual")
        self.assertNotEqual(reading.status, reading.input_method)


if __name__ == "__main__":
    unittest.main()
