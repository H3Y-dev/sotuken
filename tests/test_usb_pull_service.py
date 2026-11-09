"""
manager/usb_pull_service.py の単体テスト。

tests/test_usb_pull.py と同じ偽 ADB ランナー（FakeAdbRunner）を使い、実際の adb や
スマートフォンには触れずに、バックグラウンドスレッドの状態更新と停止を検証します。
"""
import os
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from manager.usb_pull_service import ADB_NOT_FOUND_MESSAGE, UsbPullService
from tests.test_usb_pull import FakeAdbRunner


class TestUsbPullService(unittest.TestCase):
    """USB吸い出しサービスの状態管理テスト。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.incoming_dir = os.path.join(self.tmp.name, "incoming")
        os.makedirs(self.incoming_dir, exist_ok=True)

        self.device1_outbox = os.path.join(self.tmp.name, "remote_device1")
        os.makedirs(self.device1_outbox, exist_ok=True)

    def tearDown(self):
        self.tmp.cleanup()

    def _create_remote_file(self, outbox_dir: str, name: str, content: bytes) -> None:
        p = os.path.join(outbox_dir, name)
        with open(p, "wb") as f:
            f.write(content)

    def _make_service(self, runner, adb_finder=None):
        service = UsbPullService(
            incoming_dir=self.incoming_dir,
            interval=0.01,
            adb_finder=adb_finder or (lambda: "fake-adb"),
            runner_factory=lambda adb_path: runner,
        )
        self.addCleanup(service.stop)
        return service

    def _wait_for(self, predicate, timeout: float = 5.0) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if predicate():
                return True
            time.sleep(0.01)
        return False

    def test_no_devices(self):
        """端末が0台のとき、動作中で端末一覧が空、累計0のままであること。"""
        runner = FakeAdbRunner({})
        service = self._make_service(runner)
        service.start()

        self.assertTrue(self._wait_for(lambda: service.status()["cycles"] >= 1))

        status = service.status()
        self.assertTrue(status["running"])
        self.assertTrue(status["adb_found"])
        self.assertEqual([], status["devices"])
        self.assertEqual(0, status["pulled_total"])

    def test_one_device_one_pair(self):
        """端末が1台で1組あるとき、吸い出されて pulled_total が1になること。"""
        self._create_remote_file(self.device1_outbox, "20261021T100000_test1.json", b'{"local_id": "test1"}')
        self._create_remote_file(self.device1_outbox, "20261021T100000_test1.jpg", b"fake-image-bytes")

        runner = FakeAdbRunner({"serial-1": self.device1_outbox})
        service = self._make_service(runner)
        service.start()

        self.assertTrue(self._wait_for(lambda: service.status()["pulled_total"] >= 1))

        status = service.status()
        self.assertTrue(status["running"])
        self.assertTrue(status["adb_found"])
        self.assertEqual(["serial-1"], status["devices"])
        self.assertEqual(1, status["pulled_total"])
        self.assertIsNone(status["last_error"])

        self.assertTrue(os.path.exists(os.path.join(self.incoming_dir, "20261021T100000_test1.json")))
        self.assertTrue(os.path.exists(os.path.join(self.incoming_dir, "20261021T100000_test1.jpg")))

    def test_missing_adb_keeps_running_and_sets_error(self):
        """adb が無いとき、スレッドは動いたままエラー文が状態に入ること。"""
        runner = FakeAdbRunner({})
        service = self._make_service(runner, adb_finder=lambda: None)
        service.start()

        self.assertTrue(self._wait_for(lambda: service.status()["last_error"] is not None))

        status = service.status()
        self.assertTrue(status["running"])
        self.assertFalse(status["adb_found"])
        self.assertEqual(ADB_NOT_FOUND_MESSAGE, status["last_error"])
        self.assertEqual([], status["devices"])
        self.assertEqual(0, status["pulled_total"])

    def test_stop_stops_thread(self):
        """stop() でスレッドが止まり、running が False になること。"""
        runner = FakeAdbRunner({})
        service = self._make_service(runner)
        service.start()

        self.assertTrue(self._wait_for(lambda: service.status()["cycles"] >= 1))
        self.assertTrue(service.status()["running"])

        service.stop()

        self.assertFalse(service.status()["running"])
        self.assertIsNone(service._thread)

        cycles_after_stop = service.status()["cycles"]
        time.sleep(0.05)
        self.assertEqual(cycles_after_stop, service.status()["cycles"])


if __name__ == "__main__":
    unittest.main()
