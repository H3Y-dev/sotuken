"""
USB接続スマホからの撮影画像自動吸い出しスクリプト（段階3: USB自動吸い出し）。
adb経由で接続端末内の outbox フォルダを監視し、撮影画像およびサイドカーJSONを
incoming/ フォルダへ取り込みます。
標準ライブラリ（argparse, os, shutil, subprocess, sys, time, typing）のみで構成されます。
"""
import argparse
import os
import shutil
import subprocess
import sys
import time
from typing import Callable, Dict, List, Optional, Tuple

# リモート端末側の送信箱パス
REMOTE_OUTBOX_DIR = "/sdcard/Android/data/jp.sotuken.metercapture/files/outbox"

# 取り込み対象の画像拡張子（小文字）
SUPPORTED_IMAGE_EXTS = (".jpg", ".jpeg", ".png")


def get_default_incoming_dir() -> str:
    """incoming/ ディレクトリの既定パスを返す（リポジトリ直下の incoming/）。"""
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(repo_root, "incoming")


def find_adb_path(
    env: Optional[Dict[str, str]] = None,
    which_fn: Optional[Callable[[str], Optional[str]]] = None,
    isfile_fn: Optional[Callable[[str], bool]] = None,
) -> Optional[str]:
    """
    adb 実行ファイルのパスを探索する。
    探索順序:
      1. 環境変数 ADB
      2. PATH
      3. %LOCALAPPDATA%\\Android\\Sdk\\platform-tools\\adb.exe
    見つからない場合は None を返す。
    """
    if env is None:
        env = os.environ
    if which_fn is None:
        which_fn = shutil.which
    if isfile_fn is None:
        isfile_fn = os.path.isfile

    # 1. 環境変数 ADB
    adb_env = env.get("ADB")
    if adb_env and isfile_fn(adb_env):
        return adb_env

    # 2. PATH
    path_adb = which_fn("adb")
    if path_adb and isfile_fn(path_adb):
        return path_adb

    # 3. %LOCALAPPDATA%\Android\Sdk\platform-tools\adb.exe
    local_app_data = env.get("LOCALAPPDATA")
    if local_app_data:
        sdk_adb = os.path.join(local_app_data, "Android", "Sdk", "platform-tools", "adb.exe")
        if isfile_fn(sdk_adb):
            return sdk_adb

    return None


class AdbRunner:
    """ADBコマンドを実行する標準ランナー。"""

    def __init__(self, adb_path: str = "adb"):
        self.adb_path = adb_path

    def run_cmd(self, args: List[str]) -> Tuple[int, str, str]:
        """adb <args> を実行し (returncode, stdout, stderr) を返す。"""
        cmd = [self.adb_path] + args
        try:
            proc = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            return proc.returncode, proc.stdout, proc.stderr
        except OSError as exc:
            return 1, "", str(exc)

    def get_devices(self) -> List[str]:
        """接続中の state == 'device' な端末シリアル一覧を返す。"""
        code, out, _ = self.run_cmd(["devices"])
        if code != 0:
            return []
        devices: List[str] = []
        for line in out.strip().splitlines():
            line = line.strip()
            if not line or line.startswith("List of devices attached"):
                continue
            parts = line.split()
            if len(parts) >= 2 and parts[1] == "device":
                devices.append(parts[0])
        return devices

    def list_outbox_files(self, serial: str, remote_dir: str) -> List[str]:
        """指定端末のリモートフォルダ内のファイル名一覧を返す。"""
        code, out, _ = self.run_cmd(["-s", serial, "shell", "ls", "-1", remote_dir])
        if code != 0:
            return []
        files: List[str] = []
        for line in out.strip().splitlines():
            fname = line.strip()
            if fname and not fname.startswith("ls:") and not fname.startswith("error:"):
                files.append(fname)
        return files

    def get_remote_file_size(self, serial: str, remote_path: str) -> Optional[int]:
        """リモートファイルのバイトサイズを取得する。"""
        code, out, _ = self.run_cmd(["-s", serial, "shell", "stat", "-c", "%s", remote_path])
        if code == 0:
            val = out.strip()
            if val.isdigit():
                return int(val)
        code, out, _ = self.run_cmd(["-s", serial, "shell", "ls", "-l", remote_path])
        if code == 0:
            parts = out.strip().split()
            for part in parts[3:]:
                if part.isdigit():
                    return int(part)
        return None

    def pull(self, serial: str, remote_path: str, local_dest: str) -> bool:
        """指定端末からローカルへファイルを pull する。"""
        code, _, _ = self.run_cmd(["-s", serial, "pull", remote_path, local_dest])
        return code == 0 and os.path.exists(local_dest)

    def remove(self, serial: str, remote_path: str) -> bool:
        """指定端末のリモートファイルを削除する。"""
        code, _, _ = self.run_cmd(["-s", serial, "shell", "rm", remote_path])
        return code == 0


def find_complete_pairs(filenames: List[str]) -> List[Tuple[str, str]]:
    """
    リモートフォルダ内のファイル名一覧から、完全な (JSONファイル名, 画像ファイル名) の組を抽出する。
    - *.part は無視する。
    - 同一ベース名の <base>.json と <base>.<jpg|jpeg|png> が両方そろったもののみを対象とする。
    - 孤立ファイルは無視する。
    """
    clean_files = [f for f in filenames if not f.lower().endswith(".part")]

    json_map: Dict[str, str] = {}
    image_map: Dict[str, str] = {}

    for fname in clean_files:
        lower = fname.lower()
        if lower.endswith(".json"):
            base = fname[:-5]
            json_map[base] = fname
        else:
            for ext in SUPPORTED_IMAGE_EXTS:
                if lower.endswith(ext):
                    base = fname[:-len(ext)]
                    if base not in image_map:
                        image_map[base] = fname
                    break

    pairs: List[Tuple[str, str]] = []
    for base in sorted(json_map.keys()):
        if base in image_map:
            pairs.append((json_map[base], image_map[base]))

    return pairs


def pull_pair(
    runner: AdbRunner,
    serial: str,
    json_name: str,
    image_name: str,
    incoming_dir: str,
    remote_outbox_dir: str = REMOTE_OUTBOX_DIR,
) -> bool:
    """
    1組の (JSON, 画像) を指定端末から incoming/ へ取り込む。
    - 既に incoming/ に画像が存在する場合は受信済みとみなし、端末側ファイルを削除する。
    - JSONを .part で pull してサイズ検証後、正式名へリネーム。
    - 続いて画像を .part で pull してサイズ検証後、正式名へリネーム。
    - 両方が正式に保存された後、端末側の2ファイルを削除する。
    - サイズ不一致やエラー時は何も残さずロールバックし、端末側ファイルを保持する。
    """
    os.makedirs(incoming_dir, exist_ok=True)
    remote_json_path = f"{remote_outbox_dir}/{json_name}"
    remote_image_path = f"{remote_outbox_dir}/{image_name}"

    final_json_path = os.path.join(incoming_dir, json_name)
    final_image_path = os.path.join(incoming_dir, image_name)

    # 1. 既に画像が存在する場合は受信済みとして扱い、端末側のファイルを削除する
    if os.path.exists(final_image_path):
        print(f"[USB吸い出し] 既に受信済みのためスキップ（端末側のファイルを削除）: {image_name} (端末: {serial})")
        runner.remove(serial, remote_json_path)
        runner.remove(serial, remote_image_path)
        return True

    part_json_path = os.path.join(incoming_dir, f"{json_name}.part")
    part_image_path = os.path.join(incoming_dir, f"{image_name}.part")

    # 残骸があれば事前に削除
    for p in (part_json_path, part_image_path):
        if os.path.exists(p):
            try:
                os.remove(p)
            except OSError:
                pass

    json_created_in_this_run = False

    # 2. JSON の吸い出し
    remote_json_size = runner.get_remote_file_size(serial, remote_json_path)
    if remote_json_size is None or remote_json_size < 0:
        print(f"[USB吸い出し] リモートJSONのサイズ取得に失敗しました: {json_name} (端末: {serial})")
        return False

    if not runner.pull(serial, remote_json_path, part_json_path):
        print(f"[USB吸い出し] JSONの取得に失敗しました: {json_name} (端末: {serial})")
        if os.path.exists(part_json_path):
            try:
                os.remove(part_json_path)
            except OSError:
                pass
        return False

    local_json_size = os.path.getsize(part_json_path)
    if local_json_size != remote_json_size:
        print(
            f"[USB吸い出し] JSONサイズ不一致（期待: {remote_json_size}, 実際: {local_json_size}）: "
            f"{json_name} (端末: {serial})"
        )
        if os.path.exists(part_json_path):
            try:
                os.remove(part_json_path)
            except OSError:
                pass
        return False

    try:
        os.replace(part_json_path, final_json_path)
        json_created_in_this_run = True
    except OSError as exc:
        print(f"[USB吸い出し] JSONのリネームに失敗しました: {exc}")
        if os.path.exists(part_json_path):
            try:
                os.remove(part_json_path)
            except OSError:
                pass
        return False

    # 3. 画像の吸い出し
    def rollback():
        if os.path.exists(part_image_path):
            try:
                os.remove(part_image_path)
            except OSError:
                pass
        if json_created_in_this_run and os.path.exists(final_json_path):
            try:
                os.remove(final_json_path)
            except OSError:
                pass

    remote_image_size = runner.get_remote_file_size(serial, remote_image_path)
    if remote_image_size is None or remote_image_size < 0:
        print(f"[USB吸い出し] リモート画像のサイズ取得に失敗しました: {image_name} (端末: {serial})")
        rollback()
        return False

    if not runner.pull(serial, remote_image_path, part_image_path):
        print(f"[USB吸い出し] 画像の取得に失敗しました: {image_name} (端末: {serial})")
        rollback()
        return False

    local_image_size = os.path.getsize(part_image_path)
    if local_image_size != remote_image_size:
        print(
            f"[USB吸い出し] 画像サイズ不一致（期待: {remote_image_size}, 実際: {local_image_size}）: "
            f"{image_name} (端末: {serial})"
        )
        rollback()
        return False

    try:
        os.replace(part_image_path, final_image_path)
    except OSError as exc:
        print(f"[USB吸い出し] 画像のリネームに失敗しました: {exc}")
        rollback()
        return False

    # 4. 両方完了後に端末側ファイルを削除
    runner.remove(serial, remote_json_path)
    runner.remove(serial, remote_image_path)
    print(f"[USB吸い出し] 吸い出し完了: {image_name} (端末: {serial})")
    return True


def pull_cycle(
    runner: AdbRunner,
    incoming_dir: str,
    remote_outbox_dir: str = REMOTE_OUTBOX_DIR,
) -> int:
    """
    1回の吸い出しサイクルを実行する。
    処理した（または重複処理した）ペアの数を返す。
    """
    devices = runner.get_devices()
    total_processed = 0
    for device in devices:
        remote_files = runner.list_outbox_files(device, remote_outbox_dir)
        pairs = find_complete_pairs(remote_files)
        for json_name, image_name in pairs:
            if pull_pair(runner, device, json_name, image_name, incoming_dir, remote_outbox_dir):
                total_processed += 1
    return total_processed


class UsbPuller:
    """USB自動吸い出し制御クラス。"""

    def __init__(
        self,
        runner: AdbRunner,
        incoming_dir: str,
        remote_outbox_dir: str = REMOTE_OUTBOX_DIR,
    ):
        self.runner = runner
        self.incoming_dir = incoming_dir
        self.remote_outbox_dir = remote_outbox_dir

    def pull_once(self) -> int:
        """1回の吸い出しサイクルを実行する。"""
        return pull_cycle(self.runner, self.incoming_dir, self.remote_outbox_dir)


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="USB接続スマホからの撮影画像自動吸い出しスクリプト")
    parser.add_argument(
        "--interval",
        type=float,
        default=5.0,
        help="吸い出し間隔（秒、デフォルト: 5）",
    )
    parser.add_argument(
        "--incoming",
        default=get_default_incoming_dir(),
        help="保存先incomingディレクトリ（デフォルト: リポジトリ直下の incoming/）",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="1回のみ実行して終了（テスト・手動検証用）",
    )
    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)
    adb_path = find_adb_path()
    if not adb_path:
        sys.stderr.write(
            "[USB吸い出し] エラー: adb コマンドが見つかりません。\n"
            "探索順序: 環境変数 ADB → PATH → %LOCALAPPDATA%\\Android\\Sdk\\platform-tools\\adb.exe\n"
            "Android SDK Platform-Tools をインストールするか、PATH または環境変数 ADB を設定してください。\n"
        )
        return 1

    incoming_dir = os.path.abspath(args.incoming)
    os.makedirs(incoming_dir, exist_ok=True)
    runner = AdbRunner(adb_path=adb_path)

    print(f"[USB吸い出し] 監視開始: 間隔={args.interval}秒, 保存先={incoming_dir}, adb={adb_path}")
    if args.once:
        pull_cycle(runner, incoming_dir)
        print("[USB吸い出し] --once が指定されたため終了します。")
        return 0

    print("[USB吸い出し] 停止するには Ctrl+C を押してください。")
    try:
        while True:
            pull_cycle(runner, incoming_dir)
            time.sleep(args.interval)
    except KeyboardInterrupt:
        print("\n[USB吸い出し] 停止しました。")
        return 0


if __name__ == "__main__":
    sys.exit(main())
