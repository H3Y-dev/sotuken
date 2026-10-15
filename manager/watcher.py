import os
import threading
import time
from typing import Any, Callable, Dict, List, Optional, Set
from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

from manager.sidecar import load_sidecar, SidecarMetadata
from manager.pipeline_caller import execute_pipeline

VALID_IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png")


class ImageEventHandler(FileSystemEventHandler):
    """監視フォルダ内への画像作成・移動イベントを処理するハンドラ"""

    def __init__(
        self,
        callback: Callable[[str], None],
        valid_exts: tuple = VALID_IMAGE_EXTENSIONS,
        sidecar_callback: Optional[Callable[[str], None]] = None,
    ):
        super().__init__()
        self.callback = callback
        self.valid_exts = tuple(ext.lower() for ext in valid_exts)
        self.sidecar_callback = sidecar_callback

    def _is_valid_image(self, path: str) -> bool:
        return any(path.lower().endswith(ext) for ext in self.valid_exts)

    def _handle_sidecar(self, event, path: str):
        # JSONは書き込み途中で created、書き終わりで modified が来るので両方拾う
        if self.sidecar_callback and not event.is_directory and path.lower().endswith(".json"):
            self.sidecar_callback(os.path.abspath(path))

    def on_created(self, event):
        if not event.is_directory and self._is_valid_image(event.src_path):
            self.callback(os.path.abspath(event.src_path))
        self._handle_sidecar(event, event.src_path)

    def on_modified(self, event):
        self._handle_sidecar(event, event.src_path)

    def on_moved(self, event):
        if not event.is_directory and self._is_valid_image(event.dest_path):
            self.callback(os.path.abspath(event.dest_path))
        self._handle_sidecar(event, event.dest_path)


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
        on_pipeline_result: Optional[Callable[[str, Optional[SidecarMetadata], Dict[str, Any]], None]] = None,
        auto_run_pipeline: bool = False,
        use_vlm: bool = False,
        valid_exts: tuple = VALID_IMAGE_EXTENSIONS,
        on_sidecar_updated: Optional[Callable[[str, SidecarMetadata], None]] = None,
    ):
        self.watch_dir = os.path.abspath(watch_dir)
        self.on_image_detected = on_image_detected
        self.on_item_detected = on_item_detected
        self.on_pipeline_result = on_pipeline_result
        self.on_sidecar_updated = on_sidecar_updated
        self.auto_run_pipeline = auto_run_pipeline
        self.use_vlm = use_vlm
        self.valid_exts = tuple(ext.lower() for ext in valid_exts)
        self.detected_images: List[str] = []
        self._detected_set: Set[str] = set()
        # 画像ごとに最後に渡したサイドカー。同じ内容を何度も反映しないために持つ
        self._last_sidecar: Dict[str, Optional[SidecarMetadata]] = {}
        # start() のメインスレッドと Observer スレッドが同時に読み直すと、古いJSONの反映が
        # 新しい反映を上書きしうる。読み込みから反映・記憶までをまとめて直列化する
        self._sidecar_lock = threading.Lock()

        self._observer: Optional[Observer] = None
        self._handler = ImageEventHandler(
            callback=self._handle_detected_image,
            valid_exts=self.valid_exts,
            sidecar_callback=self._handle_sidecar_json,
        )

    def _handle_sidecar_json(self, json_path: str):
        """検出済み画像の同名JSONが後から届いた（または書き終わった）ときに通知する。

        画像より先に届いたJSONは、画像検出時に load_sidecar で読まれるのでここでは何もしない。
        空・半書き・不正なJSONは load_sidecar が None を返すので無視し、完成時の再イベントを待つ。
        """
        if not self.on_sidecar_updated:
            return
        base = os.path.normcase(os.path.splitext(json_path)[0])
        image_path = next(
            (p for p in self.detected_images if os.path.normcase(os.path.splitext(p)[0]) == base),
            None,
        )
        if image_path is not None:
            self._refresh_sidecar(image_path)

    def _refresh_sidecar(self, image_path: str):
        """同名JSONを読み直し、前回渡した内容から変わっていれば on_sidecar_updated で知らせる。

        パイプライン後・監視開始直後にも呼ぶ。そこで届いたJSONにはイベントが来ないため。
        """
        if not self.on_sidecar_updated:
            return
        with self._sidecar_lock:
            sidecar = load_sidecar(image_path)
            if sidecar is None or sidecar == self._last_sidecar.get(image_path):
                return
            try:
                self.on_sidecar_updated(image_path, sidecar)
                self._last_sidecar[image_path] = sidecar
            except Exception as exc:
                # 例外で Observer スレッドを止めると以降の画像を取りこぼすため、記録して続ける
                print(f"[サイドカー反映] 失敗: {image_path}: {exc}")

    def _handle_detected_image(self, image_path: str):
        abs_path = os.path.abspath(image_path)
        if abs_path not in self._detected_set:
            self._detected_set.add(abs_path)
            self.detected_images.append(abs_path)
            sidecar = load_sidecar(abs_path)
            self._last_sidecar[abs_path] = sidecar
            if self.on_image_detected:
                self.on_image_detected(abs_path)
            if self.on_item_detected:
                self.on_item_detected(abs_path, sidecar)
            if self.auto_run_pipeline or self.on_pipeline_result:
                result = execute_pipeline(abs_path, use_vlm=self.use_vlm)
                if self.on_pipeline_result:
                    self.on_pipeline_result(abs_path, sidecar, result)
            # 処理中に届いた・書き終わったJSONを、再OCRせず既存記録へ反映する
            self._refresh_sidecar(abs_path)

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
                    self._last_sidecar[full_path] = sidecar
                    if self.on_image_detected:
                        self.on_image_detected(full_path)
                    if self.on_item_detected:
                        self.on_item_detected(full_path, sidecar)
                    if self.auto_run_pipeline or self.on_pipeline_result:
                        result = execute_pipeline(full_path, use_vlm=self.use_vlm)
                        if self.on_pipeline_result:
                            self.on_pipeline_result(full_path, sidecar, result)
                    self._refresh_sidecar(full_path)
        return new_found

    def start(self):
        """フォルダ監視を開始（watchdog Observerを起動）"""
        if self._observer and self._observer.is_alive():
            return

        os.makedirs(self.watch_dir, exist_ok=True)
        self._observer = Observer()
        self._observer.schedule(self._handler, path=self.watch_dir, recursive=False)
        self._observer.start()
        # 初回走査中や監視開始前に届いたJSONにはイベントが来ないので、開始後に読み直す。
        for image_path in list(self.detected_images):
            self._refresh_sidecar(image_path)

    def stop(self, timeout: float = 2.0):
        """フォルダ監視を停止"""
        if self._observer:
            self._observer.stop()
            self._observer.join(timeout=timeout)
            self._observer = None

    def is_running(self) -> bool:
        """監視が実行中かどうかを返す"""
        return bool(self._observer and self._observer.is_alive())
