"""ADB and UIAutomator helper module for emulator E2E testing."""
from __future__ import annotations

import os
import re
import subprocess
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Optional, Tuple, List, Dict, Any


def get_adb_path() -> str:
    local_app_data = os.environ.get("LOCALAPPDATA", "")
    path = os.path.join(local_app_data, "Android", "Sdk", "platform-tools", "adb.exe")
    if os.path.exists(path):
        return path
    return "adb"


def get_emulator_path() -> str:
    local_app_data = os.environ.get("LOCALAPPDATA", "")
    path = os.path.join(local_app_data, "Android", "Sdk", "emulator", "emulator.exe")
    if os.path.exists(path):
        return path
    return "emulator"


class AdbClient:
    def __init__(self, serial: Optional[str] = None):
        self.adb = get_adb_path()
        self.serial = serial

    def cmd(self, *args: str, timeout: float = 30) -> subprocess.CompletedProcess:
        full_args = [self.adb]
        if self.serial:
            full_args.extend(["-s", self.serial])
        full_args.extend(args)
        return subprocess.run(
            full_args,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )

    def shell(self, *args: str, timeout: float = 30) -> str:
        proc = self.cmd("shell", *args, timeout=timeout)
        if proc.returncode != 0:
            raise RuntimeError(f"adb shell failed ({proc.returncode}): {proc.stderr}\nArgs: {args}")
        return proc.stdout

    def is_connected(self) -> bool:
        proc = self.cmd("devices")
        for line in proc.stdout.splitlines():
            parts = line.strip().split()
            if len(parts) >= 2 and parts[1] == "device":
                if not self.serial or parts[0] == self.serial:
                    if not self.serial:
                        self.serial = parts[0]
                    return True
        return False

    def wait_for_boot(self, timeout: float = 120) -> bool:
        start = time.time()
        self.cmd("wait-for-device", timeout=30)
        while time.time() - start < timeout:
            try:
                out = self.shell("getprop", "sys.boot_completed").strip()
                if out == "1":
                    return True
            except Exception:
                pass
            time.sleep(2)
        return False

    def root(self) -> bool:
        proc = self.cmd("root")
        self.cmd("wait-for-device")
        time.sleep(1)
        return "restarting" in proc.stdout or proc.returncode == 0

    def connect_wifi(self) -> None:
        try:
            self.shell("svc", "wifi", "enable")
            self.shell("cmd", "wifi", "connect-network", "AndroidWifi", "open")
            time.sleep(3)
        except Exception:
            pass

    def install(self, apk_path: str) -> None:
        proc = self.cmd("install", "-r", apk_path, timeout=60)
        if proc.returncode != 0:
            raise RuntimeError(f"Failed to install APK: {proc.stderr} {proc.stdout}")

    def grant_permission(self, package: str, permission: str) -> None:
        self.shell("pm", "grant", package, permission)

    def start_app(self, package: str, activity: str) -> None:
        self.shell("am", "start", "-n", f"{package}/{activity}")

    def stop_app(self, package: str) -> None:
        self.shell("am", "force-stop", package)

    def push(self, local_path: str, remote_path: str) -> None:
        proc = self.cmd("push", local_path, remote_path)
        if proc.returncode != 0:
            raise RuntimeError(f"Failed to push {local_path} to {remote_path}: {proc.stderr}")

    def dump_ui(self) -> ET.Element:
        self.shell("uiautomator", "dump", "/data/local/tmp/ui.xml")
        xml_text = self.shell("cat", "/data/local/tmp/ui.xml")
        # uiautomator sometimes prepends "UI hierchary dumped to: ...\n"
        if "<hierarchy" in xml_text:
            xml_text = xml_text[xml_text.find("<hierarchy"):]
        return ET.fromstring(xml_text)

    def find_node(
        self,
        root: ET.Element,
        text: Optional[str] = None,
        text_contains: Optional[str] = None,
        class_name: Optional[str] = None,
    ) -> Optional[ET.Element]:
        for node in root.iter("node"):
            node_text = node.attrib.get("text", "")
            node_class = node.attrib.get("class", "")
            if text is not None and node_text != text:
                continue
            if text_contains is not None and text_contains not in node_text:
                continue
            if class_name is not None and node_class != class_name:
                continue
            return node
        return None

    def get_node_center(self, node: ET.Element) -> Tuple[int, int]:
        bounds = node.attrib["bounds"]  # [x1,y1][x2,y2]
        m = re.match(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", bounds)
        if not m:
            raise ValueError(f"Invalid bounds: {bounds}")
        x1, y1, x2, y2 = map(int, m.groups())
        return (x1 + x2) // 2, (y1 + y2) // 2

    def tap(self, x: int, y: int) -> None:
        self.shell("input", "tap", str(x), str(y))

    def tap_node(self, node: ET.Element) -> None:
        cx, cy = self.get_node_center(node)
        self.tap(cx, cy)

    def tap_text(self, text: str, timeout: float = 10, contains: bool = False) -> bool:
        start = time.time()
        while time.time() - start < timeout:
            root = self.dump_ui()
            node = self.find_node(root, text=None if contains else text, text_contains=text if contains else None)
            if node is not None:
                self.tap_node(node)
                return True
            time.sleep(1)
        return False

    def input_text(self, text: str) -> None:
        # adb shell input text encodes spaces as %s
        safe_text = text.replace(" ", "%s")
        self.shell("input", "text", safe_text)

    def keyevent(self, code: int) -> None:
        self.shell("input", "keyevent", str(code))

    def swipe(self, x1: int, y1: int, x2: int, y2: int, duration_ms: int = 300) -> None:
        self.shell("input", "swipe", str(x1), str(y1), str(x2), str(y2), str(duration_ms))

    def screencap(self, local_dest: str) -> None:
        os.makedirs(os.path.dirname(os.path.abspath(local_dest)), exist_ok=True)
        raw = self.cmd("exec-out", "screencap", "-p")
        # In text mode, binary output may be mangled, so run with raw stdout
        proc = subprocess.run(
            [self.adb] + (["-s", self.serial] if self.serial else []) + ["exec-out", "screencap", "-p"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        if proc.returncode == 0:
            with open(local_dest, "wb") as f:
                f.write(proc.stdout)
        else:
            raise RuntimeError(f"screencap failed: {proc.stderr.decode('utf-8', errors='replace')}")

    def sql_exec(self, db_path: str, sql: str) -> str:
        args = [self.adb]
        if self.serial:
            args.extend(["-s", self.serial])
        args.extend(["shell", "sqlite3", db_path])
        proc = subprocess.run(
            args,
            input=sql,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
        )
        if proc.returncode != 0:
            raise RuntimeError(f"sqlite3 failed: {proc.stderr} for SQL: {sql}")
        return proc.stdout

    def sql_query(self, db_path: str, sql: str) -> List[List[str]]:
        out = self.sql_exec(db_path, sql)
        rows = []
        for line in out.splitlines():
            if line.strip():
                rows.append(line.split("|"))
        return rows
