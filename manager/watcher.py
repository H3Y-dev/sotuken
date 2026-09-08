import os
import time
from typing import Callable, List, Optional, Set
from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

from manager.sidecar import load_sidecar, SidecarMetadata

VALID_IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png")


class ImageEventHandler(FileSystemEventHandler):
    """監視フォルダ内への画像作成・移動イベントを処理するハンドラ"""

    def __init__(self, callback: Callable[[str], None], valid_exts: tuple = VALID_IMAGE_EXTENSIONS):
        super().__init__()
        self.callback = callback
        self.valid_exts = tuple(ext.lower() for ext in valid_exts)

    def _is_valid_image(self, path: str) -> bool:
        return any(path.lower().endswith(ext) for ext in self.valid_exts)

    def on_created(self, event):
        if not event.is_directory and self._is_valid_image(event.src_path):
            self.callback(os.path.abspath(event.src_path))

    def on_moved(self, event):
        if not event.is_directory and self._is_valid_image(event.dest_path):
            self.callback(os.path.abspath(event.dest_path))


class FolderWatcher:
    """
    指定フォルダを監視し、新規画像が追加された際にコールバックを呼び出すウォッチャー。
    watchdog によるリアルタイム監視および、手動走査（scan_existing）を提供。
    """

    def __init__(
        self,
        watch_dir: str,
        on_image_detected: Optional[Callable[[str], None]] = None,
        on_item_detected: Optional[Callable[[str, Optional[SidecarMetadata]], None]] = None,
        valid_exts: tuple = VALID_IMAGE_EXTENSIONS,
    ):
        self.watch_dir = os.path.abspath(watch_dir)
        self.on_image_detected = on_image_detected
        self.on_item_detected = on_item_detected
        self.valid_exts = tuple(ext.lower() for ext in valid_exts)
        self.detected_images: List[str] = []
        self._detected_set: Set[str] = set()

        self._observer: Optional[Observer] = None
        self._handler = ImageEventHandler(
            callback=self._handle_detected_image,
            valid_exts=self.valid_exts,
        )

    def _handle_detected_image(self, image_path: str):
        abs_path = os.path.abspath(image_path)
        if abs_path not in self._detected_set:
            self._detected_set.add(abs_path)
            self.detected_images.append(abs_path)
            sidecar = load_sidecar(abs_path)
            if self.on_image_detected:
                self.on_image_detected(abs_path)
            if self.on_item_detected:
                self.on_item_detected(abs_path, sidecar)

    def scan_existing(self) -> List[str]:
        """現在監視フォルダ内に存在する未検出の新規画像を走査して検出する"""
        if not os.path.exists(self.watch_dir):
            return []

        new_found = []
        for fname in sorted(os.listdir(self.watch_dir)):
            if any(fname.lower().endswith(ext) for ext in self.valid_exts):
                full_path = os.path.abspath(os.path.join(self.watch_dir, fname))
                if full_path not in self._detected_set:
                    self._detected_set.add(full_path)
                    self.detected_images.append(full_path)
                    new_found.append(full_path)
                    sidecar = load_sidecar(full_path)
                    if self.on_image_detected:
                        self.on_image_detected(full_path)
                    if self.on_item_detected:
                        self.on_item_detected(full_path, sidecar)
        return new_found

    def start(self):
        """フォルダ監視を開始（watchdog Observerを起動）"""
        if self._observer and self._observer.is_alive():
            return

        os.makedirs(self.watch_dir, exist_ok=True)
        self._observer = Observer()
        self._observer.schedule(self._handler, path=self.watch_dir, recursive=False)
        self._observer.start()

    def stop(self, timeout: float = 2.0):
        """フォルダ監視を停止"""
        if self._observer:
            self._observer.stop()
            self._observer.join(timeout=timeout)
            self._observer = None

    def is_running(self) -> bool:
        """監視が実行中かどうかを返す"""
        return bool(self._observer and self._observer.is_alive())
