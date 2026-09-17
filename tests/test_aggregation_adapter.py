import unittest
from manager.aggregation_adapter import AdapterResult, NullAdapter
from manager.record import Reading


def _make_reading(reading_id="reading-001"):
    return Reading(
        reading_id=reading_id,
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
        overlay_path=None,
    )


class TestNullAdapter(unittest.TestCase):
    def test_send_returns_all_success(self):
        readings = [_make_reading("reading-001"), _make_reading("reading-002")]
        result = NullAdapter().send(readings)
        self.assertIsInstance(result, AdapterResult)
        self.assertTrue(result.success)
        self.assertEqual(result.sent_count, 2)
        self.assertEqual(result.failed_readings, [])
        self.assertIsNone(result.error_message)

    def test_send_empty_returns_success(self):
        result = NullAdapter().send([])
        self.assertTrue(result.success)
        self.assertEqual(result.sent_count, 0)
        self.assertEqual(result.failed_readings, [])
        self.assertIsNone(result.error_message)


if __name__ == "__main__":
    unittest.main()
