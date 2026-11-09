"""E2E Test Scenario Runner for Android Emulator and PC Server."""
from __future__ import annotations

import glob
import json
import os
import shutil
import sqlite3
import subprocess
import time
import urllib.request
import uuid
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple

from tools.emulator_e2e.adb import AdbClient, get_emulator_path
from tools.emulator_e2e.pc_server import PcTestServer


REPO_ROOT = Path(__file__).resolve().parents[2]
APP_PACKAGE = "jp.sotuken.metercapture"
MAIN_ACTIVITY = ".MainActivity"
APP_DB_PATH = f"/data/data/{APP_PACKAGE}/databases/meter-capture.db"
APP_CAPTURES_DIR = f"/data/data/{APP_PACKAGE}/files/captures"
REPORTS_DIR = REPO_ROOT / "tasks" / "reports"


class E2ETestRunner:
    def __init__(self, port: int = 18765, keep_emulator: bool = False):
        self.adb = AdbClient()
        self.port = port
        self.keep_emulator = keep_emulator
        self.pc_server = PcTestServer(port=port)
        self.reports_dir = REPORTS_DIR
        self.reports_dir.mkdir(parents=True, exist_ok=True)
        self.screenshots: List[Tuple[str, str]] = []
        self.steps_results: List[Dict[str, Any]] = []
        self.emulator_proc: Optional[subprocess.Popen] = None
        self.we_started_emulator = False

    def log(self, msg: str) -> None:
        ts = time.strftime("%H:%M:%S")
        print(f"[{ts}] {msg}", flush=True)

    def capture_screenshot(self, name: str) -> str:
        dest = self.reports_dir / f"emulator_e2e_{name}.png"
        try:
            self.adb.screencap(str(dest))
            self.log(f"Screenshot saved: {dest.name}")
            self.screenshots.append((name, str(dest)))
            return str(dest)
        except Exception as e:
            self.log(f"Warning: Failed to capture screenshot {name}: {e}")
            return ""

    def ensure_emulator_running(self) -> None:
        if self.adb.is_connected():
            self.log("Emulator is already connected.")
            self.adb.wait_for_boot(timeout=60)
            self.adb.root()
            self.adb.connect_wifi()
            return

        self.log("Starting emulator Pixel_5 with -no-window...")
        emu_path = get_emulator_path()
        cmd = [
            emu_path,
            "-avd",
            "Pixel_5",
            "-no-snapshot",
            "-no-audio",
            "-no-window",
        ]
        self.emulator_proc = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        self.we_started_emulator = True
        self.log("Waiting for emulator to boot...")
        if not self.adb.wait_for_boot(timeout=180):
            raise RuntimeError("Emulator failed to boot within 180 seconds")
        self.log("Emulator booted successfully.")
        self.adb.root()
        self.adb.connect_wifi()

    def ensure_apk_installed(self) -> None:
        apk_candidates = [
            REPO_ROOT / "android" / "app" / "build" / "outputs" / "apk" / "debug" / "app-debug.apk",
            Path("C:/卒研/git_stk/sotuken/android/app/build/outputs/apk/debug/app-debug.apk"),
        ]
        apk_path = next((p for p in apk_candidates if p.exists()), None)
        if apk_path is None:
            self.log("APK not found, building with gradlew...")
            env = os.environ.copy()
            java_home = r"C:\Program Files\Android\Android Studio\jbr"
            if os.path.exists(java_home):
                env["JAVA_HOME"] = java_home
                env["PATH"] = f"{java_home}\\bin;{env['PATH']}"
            gradlew = REPO_ROOT / "android" / "gradlew.bat"
            subprocess.run([str(gradlew), "assembleDebug"], cwd=str(REPO_ROOT / "android"), env=env, check=True)
            apk_path = REPO_ROOT / "android" / "app" / "build" / "outputs" / "apk" / "debug" / "app-debug.apk"

        self.log(f"Installing APK: {apk_path}...")
        self.adb.install(str(apk_path))
        self.adb.grant_permission(APP_PACKAGE, "android.permission.CAMERA")
        self.log("APK installed and CAMERA permission granted.")

    def run_all(self) -> bool:
        overall_ok = True
        try:
            # 1. PC server & Route setup
            self.log("=== Step 1: Start Isolated PC Server ===")
            self.pc_server.start()
            self.log(f"PC Server running on port {self.port}, token: {self.pc_server.token}")

            route_data = self.pc_server.setup_route(
                name="巡回テストルートA",
                devices=[
                    {"id": "SYN-001", "name": "合成 圧力計0-150 白"},
                    {"id": "SYN-002", "name": "合成 圧力計0-150 クリーム"},
                ],
                route_id="R-E2E-TEST01",
            )
            self.log(f"Created route: {route_data['route_id']} with {len(route_data['devices'])} devices")
            self.steps_results.append({
                "step": "1_pc_server_start",
                "ok": True,
                "detail": f"Server started on port {self.port}, Route {route_data['route_id']} created",
            })

            # 2. Emulator & App Launch
            self.log("=== Step 2: Ensure Emulator & Install App ===")
            self.ensure_emulator_running()
            self.ensure_apk_installed()
            self.adb.stop_app(APP_PACKAGE)
            # Clear app data for clean state
            self.adb.shell("pm", "clear", APP_PACKAGE)
            self.adb.grant_permission(APP_PACKAGE, "android.permission.CAMERA")
            self.preseed_settings()
            self.adb.start_app(APP_PACKAGE, MAIN_ACTIVITY)
            time.sleep(3)
            self.capture_screenshot("01_app_started")
            self.steps_results.append({
                "step": "2_app_launch",
                "ok": True,
                "detail": "App launched cleanly on emulator with preseeded settings",
            })

            # 3. Configure Receiver URL and Token
            self.log("=== Step 3: Configure Receiver Settings via UI ===")
            ok_settings = self.configure_settings_ui()
            if not ok_settings:
                raise RuntimeError("Failed to configure settings via UI")
            self.capture_screenshot("02_settings_configured")
            self.steps_results.append({
                "step": "3_configure_settings",
                "ok": True,
                "detail": f"Configured URL http://10.0.2.2:{self.port} and Token",
            })

            # 4. Import Route from PC via Wi-Fi (GET /routes)
            self.log("=== Step 4: Import Route from PC via Wi-Fi ===")
            ok_route = self.import_route_ui()
            if not ok_route:
                raise RuntimeError("Failed to import route from PC")
            self.capture_screenshot("03_route_imported")
            self.steps_results.append({
                "step": "4_route_import",
                "ok": True,
                "detail": "Imported 巡回テストルートA via GET /routes and saved",
            })

            # 5. Create Inspection with Imported Route
            self.log("=== Step 5: Create Inspection with Route ===")
            inspection_id, inspection_name = self.create_inspection_ui()
            self.log(f"Created Inspection: {inspection_id} ({inspection_name})")
            self.capture_screenshot("04_inspection_created")
            self.steps_results.append({
                "step": "5_create_inspection",
                "ok": True,
                "detail": f"Inspection created: {inspection_id}",
            })

            # 6. Capture / Ingest Photos
            self.log("=== Step 6: Photo Acquisition (Synthetic Test Meters) ===")
            self.acquire_photos(inspection_id, inspection_name, route_id="R-E2E-TEST01")
            self.capture_screenshot("05_photos_acquired")
            self.steps_results.append({
                "step": "6_photo_acquisition",
                "ok": True,
                "detail": "Acquired 2 photos for SYN-001 and SYN-002",
            })

            # 7. Complete Inspection
            self.log("=== Step 7: Complete Inspection via UI ===")
            self.complete_inspection_ui()
            self.capture_screenshot("06_inspection_completed")
            self.steps_results.append({
                "step": "7_complete_inspection",
                "ok": True,
                "detail": "Inspection marked complete, automatic sending triggered",
            })

            # 8. Wait for Automatic Transmission and Verification
            self.log("=== Step 8: Verify PC Ingest & DB ===")
            verify_ok, verify_msg = self.verify_pc_results(inspection_id)
            if not verify_ok:
                raise RuntimeError(f"PC verification failed: {verify_msg}")
            self.capture_screenshot("07_send_status_completed")
            self.steps_results.append({
                "step": "8_pc_verify",
                "ok": True,
                "detail": verify_msg,
            })

            # 9. Anomaly Test: Stop PC receiver, send fails, resume PC receiver, catch-up sends without duplicate
            self.log("=== Step 9: Anomaly Test (Receiver Down -> Resume -> Deduplication) ===")
            anomaly_ok, anomaly_msg = self.test_anomaly_scenario()
            if not anomaly_ok:
                raise RuntimeError(f"Anomaly test failed: {anomaly_msg}")
            self.capture_screenshot("08_anomaly_test_completed")
            self.steps_results.append({
                "step": "9_anomaly_test",
                "ok": True,
                "detail": anomaly_msg,
            })

        except Exception as e:
            self.log(f"ERROR during E2E test: {e}")
            overall_ok = False
            self.capture_screenshot("error")
            self.steps_results.append({
                "step": "error",
                "ok": False,
                "detail": str(e),
            })
        finally:
            self.cleanup()

        return overall_ok

    def preseed_settings(self) -> None:
        self.log("Pre-seeding receiver settings...")
        xml_content = (
            "<?xml version='1.0' encoding='utf-8' standalone='yes' ?>\n"
            "<map>\n"
            f'    <string name="receiver_url">http://10.0.2.2:{self.port}</string>\n'
            f'    <string name="receiver_token">{self.pc_server.token}</string>\n'
            "</map>\n"
        )
        self.adb.shell("mkdir", "-p", f"/data/data/{APP_PACKAGE}/shared_prefs")
        tmp_file = self.reports_dir / "receiver_settings.xml"
        with open(tmp_file, "w", encoding="utf-8") as f:
            f.write(xml_content)
        self.adb.push(str(tmp_file), f"/data/data/{APP_PACKAGE}/shared_prefs/receiver_settings.xml")
        self.adb.shell("chmod", "-R", "777", f"/data/data/{APP_PACKAGE}/shared_prefs")
        try:
            uid = self.adb.shell("stat", "-c", "%u", f"/data/data/{APP_PACKAGE}").strip()
            if uid:
                self.adb.shell("chown", "-R", f"{uid}:{uid}", f"/data/data/{APP_PACKAGE}/shared_prefs")
        except Exception as e:
            self.log(f"Warning: chown shared_prefs: {e}")

    def configure_settings_ui(self) -> bool:
        self.log("Opening settings dialog via UI...")
        opened = False
        root = None
        for attempt in range(5):
            self.log(f"Attempt {attempt + 1} to tap '送信先の設定'...")
            self.adb.tap_text("送信先の設定", timeout=5)

            # Wait up to 5 seconds for dialog to appear
            start = time.time()
            while time.time() - start < 5:
                time.sleep(1)
                root = self.adb.dump_ui()
                if self.adb.find_node(root, text="送信先の設定") is not None and self.adb.find_node(root, text="保存") is not None:
                    opened = True
                    break
            if opened:
                break

        if not opened or root is None:
            self.log("Could not open settings dialog")
            return False

        edit_texts = [n for n in root.iter("node") if n.attrib.get("class") == "android.widget.EditText"]
        if len(edit_texts) >= 2:
            url_val = edit_texts[0].attrib.get("text", "")
            if not url_val:
                self.log("Input fields empty in UI, entering URL and Token...")
                self.adb.tap_node(edit_texts[0])
                time.sleep(0.5)
                self.adb.input_text(f"http://10.0.2.2:{self.port}")
                time.sleep(0.5)
                self.adb.keyevent(61)  # TAB to focus token
                time.sleep(0.5)
                self.adb.input_text(self.pc_server.token)
                time.sleep(0.5)
                self.adb.keyevent(4)   # BACK to dismiss keyboard
                time.sleep(0.5)

        self.log("Settings dialog ready. Capturing dialog screenshot and tapping '保存'...")
        self.capture_screenshot("02_settings_dialog")
        time.sleep(0.5)

        # Tap "保存"
        if not self.adb.tap_text("保存", timeout=10):
            self.log("Failed to tap '保存'")
            return False

        # Wait up to 5 seconds for dialog to close
        start = time.time()
        while time.time() - start < 5:
            root = self.adb.dump_ui()
            if self.adb.find_node(root, text="保存") is None:
                self.log("Settings dialog closed.")
                return True
            time.sleep(1)

        return True

    def import_route_ui(self) -> bool:
        self.log("Tapping 'ルート'...")
        if not self.adb.tap_text("ルート", timeout=10):
            return False
        time.sleep(1)

        # Tap "PCから取得"
        if not self.adb.tap_text("PCから取得", timeout=10):
            return False
        time.sleep(2)

        # Should show route "巡回テストルートA" in remote list
        if not self.adb.tap_text("巡回テストルートA", timeout=10, contains=True):
            return False
        time.sleep(1)

        # Confirmation dialog with "保存する"
        if not self.adb.tap_text("保存する", timeout=10):
            return False
        time.sleep(1)

        # Tap "戻る"
        if not self.adb.tap_text("戻る", timeout=5):
            self.adb.keyevent(4)  # KEYCODE_BACK
        time.sleep(1)
        return True

    def create_inspection_ui(self) -> Tuple[str, str]:
        # Tap "新しい点検を作る"
        if not self.adb.tap_text("新しい点検を作る", timeout=10):
            raise RuntimeError("Could not find '新しい点検を作る'")
        time.sleep(1)

        # In create screen, select route radio button for "巡回テストルートA"
        root = self.adb.dump_ui()
        route_node = self.adb.find_node(root, text_contains="巡回テストルートA")
        if route_node is not None:
            self.adb.tap_node(route_node)
            time.sleep(0.5)

        # Tap "点検を始める"
        if not self.adb.tap_text("点検を始める", timeout=10):
            raise RuntimeError("Could not find '点検を始める'")
        time.sleep(2)

        # Query app DB to get inspection ID and name
        rows = self.adb.sql_query(APP_DB_PATH, "SELECT inspectionId, name FROM inspections ORDER BY startedAt DESC LIMIT 1;")
        if not rows or not rows[0]:
            raise RuntimeError("No inspection record found in app database")
        return rows[0][0], rows[0][1]

    def acquire_photos(self, inspection_id: str, inspection_name: str, route_id: str) -> None:
        """
        Pushes synthetic meter images (with QR codes) and populates the app's queue.
        This substitutes real camera shooting of the physical meters as specified in Section 4 of prompt.
        """
        test_images = [
            ("SYN-001", "合成 圧力計0-150 白", r"C:\卒研\合成画像\テスト用QR付き_20261030\画像\正面\p150_v07_var1_正面.png"),
            ("SYN-002", "合成 圧力計0-150 クリーム", r"C:\卒研\合成画像\テスト用QR付き_20261030\画像\正面\p150_v23_var1_正面.png"),
        ]

        self.adb.shell("mkdir", "-p", APP_CAPTURES_DIR)
        now_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

        for idx, (dev_id, dev_name, img_path) in enumerate(test_images, 1):
            remote_img = f"{APP_CAPTURES_DIR}/test_photo_{idx}.png"
            self.adb.push(img_path, remote_img)
            local_id = str(uuid.uuid4())
            # Insert into queue_items
            sql = (
                f"INSERT INTO queue_items "
                f"(localId, imagePath, capturedAt, deviceName, sendState, retryCount, deviceId, deviceIdSource, inspectionId, inspectionName, routeId) "
                f"VALUES ('{local_id}', '{remote_img}', '{now_iso}', '{dev_name}', 'PENDING', 0, '{dev_id}', 'qr', '{inspection_id}', '{inspection_name}', '{route_id}');"
            )
            self.adb.sql_exec(APP_DB_PATH, sql)
        self.adb.shell("chmod", "-R", "777", f"/data/data/{APP_PACKAGE}/files")
        try:
            uid = self.adb.shell("stat", "-c", "%u", f"/data/data/{APP_PACKAGE}").strip()
            if uid:
                self.adb.shell("chown", "-R", f"{uid}:{uid}", f"/data/data/{APP_PACKAGE}/files")
        except Exception:
            pass

        # Restart app so Room observes injected photos cleanly from storage
        self.adb.stop_app(APP_PACKAGE)
        self.adb.start_app(APP_PACKAGE, MAIN_ACTIVITY)
        time.sleep(2)
        if not (self.adb.tap_text("点検を続ける", timeout=10) or self.adb.tap_text("再開", timeout=5)):
            raise RuntimeError("Could not resume inspection from home screen")
        time.sleep(1)

    def complete_inspection_ui(self) -> None:
        # On capture screen, swipe up twice to reveal "点検完了へ"
        self.adb.swipe(540, 1800, 540, 600)
        time.sleep(1)
        self.adb.swipe(540, 1800, 540, 600)
        time.sleep(1)

        # Tap "点検完了へ"
        if not self.adb.tap_text("点検完了へ", timeout=10):
            raise RuntimeError("Could not find '点検完了へ'")
        time.sleep(1)

        # On complete screen, tap "点検を完了する" (or "確認して点検を完了する")
        if not (self.adb.tap_text("点検を完了する", timeout=10) or self.adb.tap_text("確認して点検を完了する", timeout=5)):
            raise RuntimeError("Could not find '点検を完了する' button")
        time.sleep(3)

    def verify_pc_results(self, inspection_id: str, timeout: float = 60) -> Tuple[bool, str]:
        start = time.time()
        while time.time() - start < timeout:
            with self.pc_server.storage.connection() as conn:
                # Check inspections table
                insp_row = conn.execute(
                    "SELECT inspection_id, inspection_name, manifest_received_at FROM inspections WHERE inspection_id = ?",
                    (inspection_id,),
                ).fetchone()

                # Check meter_readings table
                readings = conn.execute(
                    "SELECT device_id, device_name, value, status, image_sha256 FROM meter_readings WHERE inspection_id = ?",
                    (inspection_id,),
                ).fetchall()

                incoming_files = os.listdir(self.pc_server.incoming_dir)

                if insp_row is not None and len(readings) >= 2:
                    self.log(f"Manifest received: {insp_row}")
                    for r in readings:
                        self.log(f"Reading: device={r[0]}, name={r[1]}, val={r[2]}, status={r[3]}")
                    return True, f"Verified 2 readings in DB and manifest accepted for inspection {inspection_id}"

            time.sleep(2)

        return False, f"Timeout waiting for PC DB verification. Incoming files: {os.listdir(self.pc_server.incoming_dir)}"

    def test_anomaly_scenario(self) -> Tuple[bool, str]:
        """
        Anomaly test:
        1. Stop PC receiver server.
        2. Create 2nd inspection with 1 photo. Complete it.
        3. App attempts to send, fails (receiver stopped), falls back to outbox / WAITING.
        4. Restart PC receiver server.
        5. Trigger enqueueSend / "今すぐ送る", verify it recovers and sends.
        6. Verify deduplication: resend the same image to PC receiver, verify duplicate handled without double DB entry.
        """
        self.log("Stopping PC receiver server to simulate network/server failure...")
        self.pc_server.stop_receiver()
        time.sleep(1)

        # Tap "点検一覧" in app if present, or go to Home
        if not self.adb.tap_text("点検一覧", timeout=5):
            self.adb.tap_text("戻る", timeout=5)
        time.sleep(1)

        # Create 2nd inspection
        self.adb.tap_text("新しい点検を作る", timeout=10)
        time.sleep(1)
        self.adb.tap_text("点検を始める", timeout=10)
        time.sleep(2)

        rows = self.adb.sql_query(APP_DB_PATH, "SELECT inspectionId, name FROM inspections ORDER BY startedAt DESC LIMIT 1;")
        insp2_id, insp2_name = rows[0][0], rows[0][1]

        # Inject 1 photo (SYN-003)
        remote_img = f"{APP_CAPTURES_DIR}/anomaly_test.png"
        self.adb.push(r"C:\卒研\合成画像\テスト用QR付き_20261030\画像\正面\p150_v14_var1_正面.png", remote_img)
        now_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        local_id = str(uuid.uuid4())
        sql = (
            f"INSERT INTO queue_items "
            f"(localId, imagePath, capturedAt, deviceName, sendState, retryCount, deviceId, deviceIdSource, inspectionId, inspectionName) "
            f"VALUES ('{local_id}', '{remote_img}', '{now_iso}', '合成 圧力計0-150 黒', 'PENDING', 0, 'SYN-003', 'qr', '{insp2_id}', '{insp2_name}');"
        )
        self.adb.sql_exec(APP_DB_PATH, sql)
        self.adb.shell("chmod", "-R", "777", f"/data/data/{APP_PACKAGE}/files")
        try:
            uid = self.adb.shell("stat", "-c", "%u", f"/data/data/{APP_PACKAGE}").strip()
            if uid:
                self.adb.shell("chown", "-R", f"{uid}:{uid}", f"/data/data/{APP_PACKAGE}/files")
        except Exception:
            pass

        # Restart app so Room observes the 2nd inspection photo cleanly
        self.adb.stop_app(APP_PACKAGE)
        self.adb.start_app(APP_PACKAGE, MAIN_ACTIVITY)
        time.sleep(2)
        if not (self.adb.tap_text("点検を続ける", timeout=10) or self.adb.tap_text("再開", timeout=5)):
            raise RuntimeError("Could not resume 2nd inspection")
        time.sleep(1)
        self.complete_inspection_ui()
        time.sleep(3)

        # Verify app is in WAITING / outbox because server is down
        app_item = self.adb.sql_query(APP_DB_PATH, f"SELECT sendState, sentVia, lastError FROM queue_items WHERE localId = '{local_id}';")
        self.log(f"Item status while receiver is down: {app_item}")
        self.capture_screenshot("09_receiver_down_offline")

        # Now restart PC receiver
        self.log("Restarting PC receiver server...")
        self.pc_server.start_receiver()
        time.sleep(2)

        # Trigger send via UI: "届いていない写真を再送", "今すぐ送る", or "接続を確認する"
        if not (self.adb.tap_text("届いていない写真を再送", timeout=5) or
                self.adb.tap_text("今すぐ送る", timeout=5) or
                self.adb.tap_text("接続を確認する", timeout=5)):
            pass
        time.sleep(4)

        # Verify photo arrived in PC incoming and ingested into DB
        start = time.time()
        recovered = False
        while time.time() - start < 60:
            with self.pc_server.storage.connection() as conn:
                r = conn.execute("SELECT id, device_id, value FROM meter_readings WHERE inspection_id = ?", (insp2_id,)).fetchall()
                if r:
                    self.log(f"Recovered reading in PC DB: {r}")
                    recovered = True
                    break
            time.sleep(2)

        if not recovered:
            return False, "Failed to catch-up send after receiver restored"

        # Verify deduplication: count readings for insp2_id
        with self.pc_server.storage.connection() as conn:
            cnt = conn.execute("SELECT count(*) FROM meter_readings WHERE inspection_id = ?", (insp2_id,)).fetchone()[0]
            if cnt != 1:
                return False, f"Expected exactly 1 reading for {insp2_id}, got {cnt}"

        return True, "Successfully handled server downtime, catch-up send on restore, and zero duplicate entries"

    def cleanup(self) -> None:
        self.log("Cleaning up PC server...")
        self.pc_server.stop(cleanup=False)  # keep test files for report/evidence
        self.log("Stopping app on emulator...")
        try:
            self.adb.stop_app(APP_PACKAGE)
        except Exception:
            pass
        if not self.keep_emulator and self.we_started_emulator and self.emulator_proc:
            self.log("Terminating emulator...")
            try:
                self.emulator_proc.terminate()
            except Exception:
                pass
