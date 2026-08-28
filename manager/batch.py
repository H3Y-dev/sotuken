import os
from glob import glob
from typing import List, Dict, Any
from manager.manager import MeterManager

class BatchProcessor:
    def __init__(self, manager: MeterManager, input_dir: str):
        self.manager = manager
        self.input_dir = input_dir

    def get_unprocessed_images(self) -> List[str]:
        """フォルダ内の画像一覧を取得し、既存DBと照合して未処理のパスのみ返す"""
        extensions = ('*.jpg', '*.jpeg', '*.png', '*.JPG', '*.PNG')
        all_files = []
        for ext in extensions:
            all_files.extend(glob(os.path.join(self.input_dir, ext)))
        
        # DB内の履歴を取得して重複を除外
        processed_paths = {row['image_path'] for row in self.manager.format_history_for_ui()}
        return [f for f in all_files if os.path.abspath(f) not in processed_paths]

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
                use_vlm=False
            )
            if res.stage == "ok":
                results["success"] += 1
            else:
                results["failed"] += 1
                
        return results