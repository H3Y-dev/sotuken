"""Isolated PC Receiver and Ingestion Server for E2E testing."""
from __future__ import annotations

import json
import os
import shutil
import socket
import tempfile
import threading
import time
from typing import Optional, List, Dict, Any

from manager.storage import Storage
from manager.routes import save_route, list_routes, get_route, init_tables
from manager.receiver import ReceiverServer, load_or_create_pc_config
from manager.watcher import FolderWatcher
from manager.ingest import ingest_result, apply_sidecar
from manager.batch import calculate_file_hash


def find_free_port(start_port: int = 18765) -> int:
    for port in range(start_port, start_port + 100):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("0.0.0.0", port))
                return port
            except OSError:
                continue
    raise RuntimeError("No free port found")


class PcTestServer:
    def __init__(self, base_dir: Optional[str] = None, port: Optional[int] = None):
        self.temp_dir = base_dir or tempfile.mkdtemp(prefix="sotuken_e2e_")
        self.port = port or find_free_port()
        self.incoming_dir = os.path.join(self.temp_dir, "incoming")
        self.images_dir = os.path.join(self.temp_dir, "images")
        self.overlays_dir = os.path.join(self.temp_dir, "overlays")
        self.db_path = os.path.join(self.temp_dir, "test_manager.db")
        self.config_path = os.path.join(self.temp_dir, "pc_config.json")

        os.makedirs(self.incoming_dir, exist_ok=True)
        os.makedirs(self.images_dir, exist_ok=True)
        os.makedirs(self.overlays_dir, exist_ok=True)

        self.storage = Storage(self.db_path)
        with self.storage.connection() as conn:
            init_tables(conn)

        self.config = load_or_create_pc_config(self.config_path)
        self.token = self.config["token"]
        self.receiver_id = self.config["receiver_id"]

        self.receiver_server: Optional[ReceiverServer] = None
        self.receiver_thread: Optional[threading.Thread] = None
        self.watcher: Optional[FolderWatcher] = None
        self.watcher_thread: Optional[threading.Thread] = None
        self._stopped = False

    def setup_route(self, name: str, devices: List[Dict[str, str]], route_id: Optional[str] = None) -> Dict[str, Any]:
        return save_route(self.storage, name, devices, route_id=route_id)

    def start_receiver(self) -> None:
        if self.receiver_server is not None:
            return
        self.receiver_server = ReceiverServer(
            ("0.0.0.0", self.port),
            token=self.token,
            incoming_dir=self.incoming_dir,
            receiver_id=self.receiver_id,
            db_path=self.db_path,
        )
        self.receiver_thread = threading.Thread(
            target=self.receiver_server.serve_forever,
            name="PcTestReceiverServer",
            daemon=True,
        )
        self.receiver_thread.start()

    def stop_receiver(self) -> None:
        if self.receiver_server is not None:
            self.receiver_server.shutdown()
            self.receiver_server.server_close()
            if self.receiver_thread:
                self.receiver_thread.join(timeout=5)
            self.receiver_server = None
            self.receiver_thread = None

    def start_watcher(self) -> None:
        if self.watcher is not None:
            return

        def skip_if(img_path: str) -> bool:
            try:
                h = calculate_file_hash(img_path)
                return h in self.storage.get_processed_hashes()
            except Exception:
                return False

        def on_pipeline_result(img_path: str, sidecar: Any, result: Dict[str, Any]):
            ingest_result(
                self.storage,
                img_path,
                sidecar,
                result,
                self.images_dir,
                self.overlays_dir,
            )

        def on_sidecar_updated(img_path: str, sidecar: Any):
            h = calculate_file_hash(img_path)
            apply_sidecar(self.storage, h, sidecar)

        self.watcher = FolderWatcher(
            self.incoming_dir,
            on_pipeline_result=on_pipeline_result,
            on_sidecar_updated=on_sidecar_updated,
            skip_pipeline_if=skip_if,
            auto_run_pipeline=True,
            use_vlm=False,
        )
        self.watcher.start()

    def stop_watcher(self) -> None:
        if self.watcher is not None:
            self.watcher.stop()
            self.watcher = None

    def start(self) -> None:
        self.start_receiver()
        self.start_watcher()

    def stop(self, cleanup: bool = False) -> None:
        self._stopped = True
        self.stop_watcher()
        self.stop_receiver()
        if cleanup and os.path.exists(self.temp_dir):
            try:
                shutil.rmtree(self.temp_dir, ignore_errors=True)
            except Exception:
                pass
