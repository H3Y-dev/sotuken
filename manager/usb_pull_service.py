"""
USB吸い出しサービス（run_pc.py から起動し、画面に状態を表示するための薄い包み）。

manager/usb_pull.py の UsbPuller.pull_once() をバックグラウンドスレッドで一定間隔ごとに
呼び出します。usb_pull.py 側の関数・クラスの動作は変更しません。
"""
import threading
from typing import Any, Callable, Dict, List, Optional

from manager.usb_pull import (
    REMOTE_OUTBOX_DIR,
    AdbRunner,
    UsbPuller,
    find_adb_path,
    get_default_incoming_dir,
)

DEFAULT_INTERVAL = 5.0

ADB_NOT_FOUND_MESSAGE = "adbが見つかりません。Android SDK Platform-Tools を入れてください"


class UsbPullService:
    """UsbPuller.pull_once() を一定間隔で呼び続ける小さなサービス。"""

    def __init__(
        self,
        incoming_dir: Optional[str] = None,
        interval: float = DEFAULT_INTERVAL,
        remote_outbox_dir: str = REMOTE_OUTBOX_DIR,
        adb_finder: Optional[Callable[[], Optional[str]]] = None,
        runner_factory: Optional[Callable[..., AdbRunner]] = None,
    ):
        self.incoming_dir = incoming_dir or get_default_incoming_dir()
        self.interval = interval
        self.remote_outbox_dir = remote_outbox_dir
        self._adb_finder = adb_finder or find_adb_path
        self._runner_factory = runner_factory or AdbRunner

        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._puller: Optional[UsbPuller] = None

        self._running = False
        self._adb_found = False
        self._devices: List[str] = []
        self._pulled_total = 0
        self._last_error: Optional[str] = None
        self._cycles = 0

    def start(self) -> None:
        """バックグラウンドスレッドを開始する（二重起動はしない）。"""
        with self._lock:
            if self._running:
                return
            self._stop_event.clear()
            self._running = True
            thread = threading.Thread(
                target=self._run,
                name="SotukenUsbPullThread",
                daemon=True,
            )
            self._thread = thread
            thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        """スレッドに停止を指示し、終了を待つ。"""
        with self._lock:
            self._stop_event.set()
            thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=timeout)
        with self._lock:
            self._running = False
            self._thread = None

    def status(self) -> Dict[str, Any]:
        """現在の状態を辞書で返す。"""
        with self._lock:
            return {
                "running": self._running,
                "adb_found": self._adb_found,
                "devices": list(self._devices),
                "pulled_total": self._pulled_total,
                "last_error": self._last_error,
                "interval": self.interval,
                "cycles": self._cycles,
            }

    def _run(self) -> None:
        try:
            while not self._stop_event.is_set():
                self._run_cycle()
                if self._stop_event.wait(self.interval):
                    break
        finally:
            with self._lock:
                self._running = False

    def _run_cycle(self) -> None:
        """1回分の吸い出しサイクルを実行し、状態を更新する。"""
        try:
            adb_path = self._adb_finder()
            if not adb_path:
                with self._lock:
                    self._adb_found = False
                    self._devices = []
                    self._last_error = ADB_NOT_FOUND_MESSAGE
                return

            with self._lock:
                self._adb_found = True

            puller = self._ensure_puller(adb_path)
            devices = puller.runner.get_devices()
            with self._lock:
                self._devices = list(devices)

            processed = puller.pull_once()
            with self._lock:
                self._pulled_total += processed
                self._last_error = None
        except Exception as exc:  # スレッドを止めず、状態にエラーを残す
            with self._lock:
                self._last_error = str(exc) or exc.__class__.__name__
        finally:
            with self._lock:
                self._cycles += 1

    def _ensure_puller(self, adb_path: str) -> UsbPuller:
        with self._lock:
            if self._puller is None:
                runner = self._runner_factory(adb_path=adb_path)
                self._puller = UsbPuller(
                    runner,
                    self.incoming_dir,
                    self.remote_outbox_dir,
                )
            return self._puller


# プロセス内キャッシュ（run_pc.py / app.py で共有。manager/receiver.py と同じ流儀）
_service_lock = threading.Lock()
_cached_service: Optional[UsbPullService] = None


def init_usb_pull_for_app(
    incoming_dir: Optional[str] = None,
    interval: float = DEFAULT_INTERVAL,
) -> UsbPullService:
    """app.py 用の初期化関数。同一プロセス内では1回だけ起動し、キャッシュして再利用する。"""
    global _cached_service
    with _service_lock:
        if _cached_service is not None:
            return _cached_service
        service = UsbPullService(incoming_dir=incoming_dir, interval=interval)
        service.start()
        _cached_service = service
        return service


def get_usb_pull_service() -> Optional[UsbPullService]:
    """run_pc.py が起動したサービスを返す。起動していなければ None。"""
    with _service_lock:
        return _cached_service


def get_usb_pull_status() -> Optional[Dict[str, Any]]:
    """サービスが起動していれば状態の辞書、起動していなければ None を返す。"""
    service = get_usb_pull_service()
    if service is None:
        return None
    return service.status()


def shutdown_usb_pull_for_app() -> None:
    """テスト用: 起動・キャッシュされたサービスを停止し、キャッシュをクリアする。"""
    global _cached_service
    with _service_lock:
        service = _cached_service
        _cached_service = None
    if service is not None:
        service.stop()
