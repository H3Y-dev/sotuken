import hashlib
import os
from typing import Any, Dict, List, Set
from manager.manager import MeterManager


def calculate_file_hash(filepath: str, chunk_size: int = 65536) -> str:
    """画像ファイルの内容からSHA-256ハッシュをチャンク単位で計算する"""
    sha256 = hashlib.sha256()
    with open(filepath, "rb") as f:
        while chunk := f.read(chunk_size):
            sha256.update(chunk)
    return sha256.hexdigest()


class BatchProcessor:
    def __init__(self, manager: MeterManager, input_dir: str):
        self.manager = manager
        self.input_dir = input_dir
        self.processed_hashes: Set[str] = set()

    def get_processed_hashes(self) -> Set[str]:
        """既存DBの履歴および本インスタンスの処理済みハッシュ一覧を取得"""
        hashes = set(self.processed_hashes)
        if self.manager:
            for row in self.manager.format_history_for_ui():
                path = row.get("image_path")
                if path and os.path.exists(path):
                    try:
                        hashes.add(calculate_file_hash(path))
                    except (OSError, IOError):
                        pass
        return hashes

    def get_unprocessed_images(self) -> List[str]:
        """フォルダ内の画像一覧を取得し、中身のハッシュ値と照合して未処理のパスのみ返す"""
        valid_exts = (".jpg", ".jpeg", ".png")
        if not os.path.exists(self.input_dir):
            return []

        all_files = []
        for fname in sorted(os.listdir(self.input_dir)):
            if any(fname.lower().endswith(ext) for ext in valid_exts):
                all_files.append(os.path.join(self.input_dir, fname))

        processed_hashes = self.get_processed_hashes()
        unprocessed = []
        seen_in_batch = set()

        for f in all_files:
            try:
                f_hash = calculate_file_hash(f)
            except (OSError, IOError):
                continue

            if f_hash not in processed_hashes and f_hash not in seen_in_batch:
                unprocessed.append(f)
                seen_in_batch.add(f_hash)

        return unprocessed

    def process_all(self, reader_func, device_name: str = "BatchDevice") -> Dict[str, int]:
        """未処理画像の一括読み取りを実行"""
        targets = self.get_unprocessed_images()
        results = {"success": 0, "failed": 0, "skipped": 0}

        for img_path in targets:
            abs_path = os.path.abspath(img_path)
            res = self.manager.process_image(
                image_path=abs_path,
                device_name=device_name,
                reader_func=reader_func,
                use_vlm=False,
            )
            if res["stage"] == "ok":
                results["success"] += 1
                try:
                    self.processed_hashes.add(calculate_file_hash(abs_path))
                except (OSError, IOError):
                    pass
            else:
                results["failed"] += 1

        return results