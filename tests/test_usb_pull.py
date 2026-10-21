"""
manager/usb_pull.py（段階3: USB自動吸い出し）の単体テスト。
偽の ADB ランナーを用いて、
- 完全な組（JSON→画像）の順次取得とリモート削除
- .part および孤立ファイルの無視
- サイズ不一致時のロールバックとリモート保持
- 受信済み画像の重複抑止とリモート削除
- adb 未検出時の明確な日本語エラー
- 複数端末・非 device 状態の端末の処理
を検証します。
"""
import io
import os
import shutil
import sys
import tempfile
import unittest
from typing import Any, Callable, Dict, List, Optional, Tuple

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from manager.usb_pull import (
    REMOTE_OUTBOX_DIR,
    AdbRunner,
    UsbPuller,
    find_adb_path,
    find_complete_pairs,
    main,
    pull_cycle,
    pull_pair,
)


class FakeAdbRunner(AdbRunner):
    """
    テスト用偽 ADB ランナー。
    ローカルの一時フォルダをリモート端末の送信箱に見立てて動作します。
    """

    def __init__(self, devices: Dict[str, Any]):
        super().__init__(adb_path="fake-adb")
        self.devices: Dict[str, Dict[str, Any]] = {}
        for serial, val in devices.items():
            if isinstance(val, str):
                self.devices[serial] = {"dir": val, "state": "device"}
            else:
                self.devices[serial] = val
        self.events: List[Tuple[str, str, str]] = []  # ("pull" | "remove", serial, remote_path)
        self.size_overrides: Dict[Tuple[str, str], int] = {}
        self.pull_hooks: Dict[Tuple[str, str], Callable[[str, str], None]] = {}

    def get_devices(self) -> List[str]:
        return [serial for serial, info in self.devices.items() if info.get("state") == "device"]

    def list_outbox_files(self, serial: str, remote_dir: str) -> List[str]:
        info = self.devices.get(serial)
        if not info or info.get("state") != "device":
            return []
        d = info["dir"]
        if not os.path.exists(d):
            return []
        return os.listdir(d)

    def get_remote_file_size(self, serial: str, remote_path: str) -> Optional[int]:
        if (serial, remote_path) in self.size_overrides:
            return self.size_overrides[(serial, remote_path)]
        info = self.devices.get(serial)
        if not info:
            return None
        fname = os.path.basename(remote_path)
        local_path = os.path.join(info["dir"], fname)
        if os.path.exists(local_path):
            return os.path.getsize(local_path)
        return None

    def pull(self, serial: str, remote_path: str, local_dest: str) -> bool:
        self.events.append(("pull", serial, remote_path))
        info = self.devices.get(serial)
        if not info:
            return False
        fname = os.path.basename(remote_path)
        local_src = os.path.join(info["dir"], fname)
        if not os.path.exists(local_src):
            return False
        if (serial, remote_path) in self.pull_hooks:
            self.pull_hooks[(serial, remote_path)](local_src, local_dest)
        else:
            shutil.copy2(local_src, local_dest)
        return True

    def remove(self, serial: str, remote_path: str) -> bool:
        self.events.append(("remove", serial, remote_path))
        info = self.devices.get(serial)
        if not info:
            return False
        fname = os.path.basename(remote_path)
        local_src = os.path.join(info["dir"], fname)
        if os.path.exists(local_src):
            os.remove(local_src)
            return True
        return False


class TestUsbPull(unittest.TestCase):
    """USB自動吸い出しの動作検証テスト。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.incoming_dir = os.path.join(self.tmp.name, "incoming")
        os.makedirs(self.incoming_dir, exist_ok=True)

        self.device1_outbox = os.path.join(self.tmp.name, "remote_device1")
        os.makedirs(self.device1_outbox, exist_ok=True)

    def tearDown(self):
        self.tmp.cleanup()

    def _create_remote_file(self, outbox_dir: str, name: str, content: bytes) -> str:
        p = os.path.join(outbox_dir, name)
        with open(p, "wb") as f:
            f.write(content)
        return p

    def test_complete_pair_pulled_in_order_and_remote_removed(self):
        """
        完全な組（<base>.json と <base>.jpg）が JSON → 画像の順で pull され、
        両方完了後にリモートファイルが削除されること。
        """
        json_content = b'{"local_id": "test1", "captured_at": "2026-10-21T10:00:00Z"}'
        img_content = b"\xff\xd8\xff\xe0\x00\x10JFIFfake-image-bytes"

        self._create_remote_file(self.device1_outbox, "20261021T100000_test1.json", json_content)
        self._create_remote_file(self.device1_outbox, "20261021T100000_test1.jpg", img_content)

        runner = FakeAdbRunner({"serial-1": self.device1_outbox})
        processed = pull_cycle(runner, self.incoming_dir)
        self.assertEqual(1, processed)

        # 1. 順序の検証: JSON pull → 画像 pull → リモートJSON削除 → リモート画像削除
        pull_events = [e for e in runner.events if e[0] == "pull"]
        rm_events = [e for e in runner.events if e[0] == "remove"]

        self.assertEqual(2, len(pull_events))
        self.assertTrue(pull_events[0][2].endswith("20261021T100000_test1.json"))
        self.assertTrue(pull_events[1][2].endswith("20261021T100000_test1.jpg"))

        self.assertEqual(2, len(rm_events))
        self.assertTrue(rm_events[0][2].endswith("20261021T100000_test1.json"))
        self.assertTrue(rm_events[1][2].endswith("20261021T100000_test1.jpg"))

        # 2. ローカル incoming/ の確認
        local_json = os.path.join(self.incoming_dir, "20261021T100000_test1.json")
        local_img = os.path.join(self.incoming_dir, "20261021T100000_test1.jpg")
        self.assertTrue(os.path.exists(local_json))
        self.assertTrue(os.path.exists(local_img))

        with open(local_json, "rb") as f:
            self.assertEqual(json_content, f.read())
        with open(local_img, "rb") as f:
            self.assertEqual(img_content, f.read())

        # .part ファイルが残っていないこと
        part_files = [f for f in os.listdir(self.incoming_dir) if f.endswith(".part")]
        self.assertEqual([], part_files)

        # 3. リモート側から削除されていること
        self.assertEqual([], os.listdir(self.device1_outbox))

    def test_part_files_and_orphan_files_ignored(self):
        """
        *.part ファイルや、相方のいない孤立ファイルは吸い出し対象から除外され、削除もされないこと。
        """
        # .part 一時ファイル
        self._create_remote_file(self.device1_outbox, "20261021T100000_item1.json.part", b"temp-json")
        self._create_remote_file(self.device1_outbox, "20261021T100000_item1.jpg.part", b"temp-img")
        # 孤立 JSON（画像なし）
        self._create_remote_file(self.device1_outbox, "20261021T100001_orphan_json.json", b'{"local_id": "orphan"}')
        # 孤立画像（JSONなし）
        self._create_remote_file(self.device1_outbox, "20261021T100002_orphan_img.jpg", b"orphan-img")
        # 完全な組（png画像）
        complete_json = b'{"local_id": "complete"}'
        complete_img = b"complete-png-bytes"
        self._create_remote_file(self.device1_outbox, "20261021T100003_complete.json", complete_json)
        self._create_remote_file(self.device1_outbox, "20261021T100003_complete.png", complete_img)

        runner = FakeAdbRunner({"serial-1": self.device1_outbox})
        processed = pull_cycle(runner, self.incoming_dir)
        self.assertEqual(1, processed)

        # 完全な組だけがローカルに取り込まれる
        self.assertTrue(os.path.exists(os.path.join(self.incoming_dir, "20261021T100003_complete.json")))
        self.assertTrue(os.path.exists(os.path.join(self.incoming_dir, "20261021T100003_complete.png")))
        self.assertFalse(os.path.exists(os.path.join(self.incoming_dir, "20261021T100001_orphan_json.json")))
        self.assertFalse(os.path.exists(os.path.join(self.incoming_dir, "20261021T100002_orphan_img.jpg")))

        # リモートには .part と孤立ファイルが残っていること
        remaining = os.listdir(self.device1_outbox)
        self.assertIn("20261021T100000_item1.json.part", remaining)
        self.assertIn("20261021T100000_item1.jpg.part", remaining)
        self.assertIn("20261021T100001_orphan_json.json", remaining)
        self.assertIn("20261021T100002_orphan_img.jpg", remaining)
        self.assertNotIn("20261021T100003_complete.json", remaining)
        self.assertNotIn("20261021T100003_complete.png", remaining)

    def test_json_size_mismatch_aborts_and_keeps_remote(self):
        """JSON のサイズが一致しない場合、中断してローカルを片付け、リモートを残すこと。"""
        self._create_remote_file(self.device1_outbox, "20261021T100000_bad1.json", b'{"local_id": "bad1"}')
        self._create_remote_file(self.device1_outbox, "20261021T100000_bad1.jpg", b"image-content")

        runner = FakeAdbRunner({"serial-1": self.device1_outbox})
        # リモートサイズを実際より大きい値に偽装
        remote_json_path = f"{REMOTE_OUTBOX_DIR}/20261021T100000_bad1.json"
        runner.size_overrides[("serial-1", remote_json_path)] = 9999

        processed = pull_cycle(runner, self.incoming_dir)
        self.assertEqual(0, processed)

        # incoming には何も残らない（.part も残らない）
        self.assertEqual([], os.listdir(self.incoming_dir))

        # リモートファイルは両方残る
        self.assertIn("20261021T100000_bad1.json", os.listdir(self.device1_outbox))
        self.assertIn("20261021T100000_bad1.jpg", os.listdir(self.device1_outbox))

    def test_image_size_mismatch_rolls_back_json_and_keeps_remote(self):
        """画像のサイズが一致しない場合、先行して保存された JSON もロールバックされ、リモートが残ること。"""
        self._create_remote_file(self.device1_outbox, "20261021T100000_bad2.json", b'{"local_id": "bad2"}')
        self._create_remote_file(self.device1_outbox, "20261021T100000_bad2.jpg", b"image-content")

        runner = FakeAdbRunner({"serial-1": self.device1_outbox})
        # 画像のリモートサイズを偽装
        remote_img_path = f"{REMOTE_OUTBOX_DIR}/20261021T100000_bad2.jpg"
        runner.size_overrides[("serial-1", remote_img_path)] = 9999

        processed = pull_cycle(runner, self.incoming_dir)
        self.assertEqual(0, processed)

        # incoming には JSON も画像も残らない
        self.assertEqual([], os.listdir(self.incoming_dir))

        # リモートファイルは両方残る
        self.assertIn("20261021T100000_bad2.json", os.listdir(self.device1_outbox))
        self.assertIn("20261021T100000_bad2.jpg", os.listdir(self.device1_outbox))

    def test_already_existing_image_removes_remote_without_duplication(self):
        """
        incoming/ に既に同名画像が存在する場合、受信済みと判断して二重保存せず、
        リモートファイルを削除すること。
        """
        existing_img_content = b"ORIGINAL-CONTENT-DO-NOT-OVERWRITE"
        existing_img_path = os.path.join(self.incoming_dir, "20261021T100000_dup.jpg")
        with open(existing_img_path, "wb") as f:
            f.write(existing_img_content)

        self._create_remote_file(self.device1_outbox, "20261021T100000_dup.json", b'{"local_id": "dup"}')
        self._create_remote_file(self.device1_outbox, "20261021T100000_dup.jpg", b"NEW-REMOTE-CONTENT")

        runner = FakeAdbRunner({"serial-1": self.device1_outbox})
        processed = pull_cycle(runner, self.incoming_dir)
        self.assertEqual(1, processed)

        # ローカル既存画像の内容が変わっていないこと
        with open(existing_img_path, "rb") as f:
            self.assertEqual(existing_img_content, f.read())

        # pull イベントは発生せず、remove イベントのみ発生すること
        pull_events = [e for e in runner.events if e[0] == "pull"]
        self.assertEqual(0, len(pull_events))

        rm_events = [e for e in runner.events if e[0] == "remove"]
        self.assertEqual(2, len(rm_events))

        # リモート側から削除されていること
        self.assertEqual([], os.listdir(self.device1_outbox))

    def test_multiple_devices_and_non_device_state(self):
        """
        複数端末が存在する場合、state == 'device' の端末のみから吸い出しが行われること。
        """
        device2_outbox = os.path.join(self.tmp.name, "remote_device2")
        device3_outbox = os.path.join(self.tmp.name, "remote_device3")
        os.makedirs(device2_outbox, exist_ok=True)
        os.makedirs(device3_outbox, exist_ok=True)

        self._create_remote_file(self.device1_outbox, "20261021T100000_dev1.json", b'{"dev": 1}')
        self._create_remote_file(self.device1_outbox, "20261021T100000_dev1.jpg", b"img-dev1")

        self._create_remote_file(device2_outbox, "20261021T100000_dev2.json", b'{"dev": 2}')
        self._create_remote_file(device2_outbox, "20261021T100000_dev2.jpg", b"img-dev2")

        self._create_remote_file(device3_outbox, "20261021T100000_dev3.json", b'{"dev": 3}')
        self._create_remote_file(device3_outbox, "20261021T100000_dev3.jpg", b"img-dev3")

        runner = FakeAdbRunner({
            "serial-dev1": {"dir": self.device1_outbox, "state": "device"},
            "serial-dev2": {"dir": device2_outbox, "state": "device"},
            "serial-dev3": {"dir": device3_outbox, "state": "unauthorized"},  # 無視されるべき
        })

        processed = pull_cycle(runner, self.incoming_dir)
        self.assertEqual(2, processed)

        # dev1 と dev2 は取り込まれ、リモートから削除される
        self.assertTrue(os.path.exists(os.path.join(self.incoming_dir, "20261021T100000_dev1.jpg")))
        self.assertTrue(os.path.exists(os.path.join(self.incoming_dir, "20261021T100000_dev2.jpg")))
        self.assertEqual([], os.listdir(self.device1_outbox))
        self.assertEqual([], os.listdir(device2_outbox))

        # dev3 は取り込まれず、リモートに残る
        self.assertFalse(os.path.exists(os.path.join(self.incoming_dir, "20261021T100000_dev3.jpg")))
        self.assertIn("20261021T100000_dev3.json", os.listdir(device3_outbox))
        self.assertIn("20261021T100000_dev3.jpg", os.listdir(device3_outbox))

    def test_find_adb_path_priority_and_missing(self):
        """adb探索順序（ADB環境変数 → PATH → LOCALAPPDATA）と未検出時の動作。"""
        # 1. 環境変数 ADB 最優先
        fake_env = {
            "ADB": r"C:\custom\adb.exe",
            "LOCALAPPDATA": r"C:\Users\test\AppData\Local",
        }
        res = find_adb_path(
            env=fake_env,
            which_fn=lambda _: r"C:\path\adb.exe",
            isfile_fn=lambda p: p in (r"C:\custom\adb.exe", r"C:\path\adb.exe"),
        )
        self.assertEqual(r"C:\custom\adb.exe", res)

        # 2. PATH が 2番目
        fake_env_no_adb = {"LOCALAPPDATA": r"C:\Users\test\AppData\Local"}
        res2 = find_adb_path(
            env=fake_env_no_adb,
            which_fn=lambda _: r"C:\path\adb.exe",
            isfile_fn=lambda p: p == r"C:\path\adb.exe",
        )
        self.assertEqual(r"C:\path\adb.exe", res2)

        # 3. %LOCALAPPDATA%\Android\Sdk\platform-tools\adb.exe が 3番目
        expected_sdk_adb = os.path.join(r"C:\Users\test\AppData\Local", "Android", "Sdk", "platform-tools", "adb.exe")
        res3 = find_adb_path(
            env=fake_env_no_adb,
            which_fn=lambda _: None,
            isfile_fn=lambda p: p == expected_sdk_adb,
        )
        self.assertEqual(expected_sdk_adb, res3)

        # 4. 見つからない場合は None
        res4 = find_adb_path(
            env={},
            which_fn=lambda _: None,
            isfile_fn=lambda _: False,
        )
        self.assertIsNone(res4)

    def test_main_missing_adb_prints_error_and_exits_nonzero(self):
        """adbが見つからない場合、わかりやすい日本語エラーを出力して非ゼロ終了すること。"""
        # 一時的に os.environ や PATH を細工して adb が見つからない状態にする
        saved_adb = os.environ.get("ADB")
        saved_localappdata = os.environ.get("LOCALAPPDATA")
        try:
            if "ADB" in os.environ:
                del os.environ["ADB"]
            os.environ["LOCALAPPDATA"] = os.path.join(self.tmp.name, "nonexistent")

            stderr_buf = io.StringIO()
            old_stderr = sys.stderr
            sys.stderr = stderr_buf
            try:
                # PATHを一時的に無効化して実行
                saved_path = os.environ.get("PATH", "")
                os.environ["PATH"] = self.tmp.name
                try:
                    code = main(["--once", "--incoming", self.incoming_dir])
                finally:
                    os.environ["PATH"] = saved_path
            finally:
                sys.stderr = old_stderr

            self.assertNotEqual(0, code)
            output = stderr_buf.getvalue()
            self.assertIn("adb コマンドが見つかりません", output)
            self.assertIn("探索順序", output)
        finally:
            if saved_adb is not None:
                os.environ["ADB"] = saved_adb
            if saved_localappdata is not None:
                os.environ["LOCALAPPDATA"] = saved_localappdata

    def test_adb_runner_parsers(self):
        """AdbRunner のコマンド出力パース処理の検証。"""
        runner = AdbRunner("adb")

        # devices パース
        runner.run_cmd = lambda args: (
            0,
            "List of devices attached\n"
            "emulator-5554\tdevice\n"
            "phone-1234\tunauthorized\n"
            "tablet-5678\tdevice\n",
            "",
        )
        devices = runner.get_devices()
        self.assertEqual(["emulator-5554", "tablet-5678"], devices)

        # list_outbox_files パース
        runner.run_cmd = lambda args: (
            0,
            "file1.json\n"
            "file1.jpg\n"
            "\n",
            "",
        )
        files = runner.list_outbox_files("dev1", "/dummy")
        self.assertEqual(["file1.json", "file1.jpg"], files)

        # stat -c %s パース成功時
        runner.run_cmd = lambda args: (0, "123456\n", "")
        self.assertEqual(123456, runner.get_remote_file_size("dev1", "/dummy/file"))

        # stat 失敗時、ls -l へフォールバック
        def mock_run_cmd(args):
            if "stat" in args:
                return (1, "", "stat: not found")
            if "ls" in args:
                return (0, "-rw-rw---- 1 u0_a123 u0_a123 654321 2026-10-21 10:00 file.jpg\n", "")
            return (0, "", "")

        runner.run_cmd = mock_run_cmd
        self.assertEqual(654321, runner.get_remote_file_size("dev1", "/dummy/file"))


if __name__ == "__main__":
    unittest.main()
