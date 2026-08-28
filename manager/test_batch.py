import os
import tempfile
import unittest
from manager.manager import MeterManager
from manager.batch import BatchProcessor

class TestBatchProcessor(unittest.TestCase):
    def setUp(self):
        self.manager = MeterManager(":memory:")
        self.temp_dir = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_batch_processing_and_deduplication(self):
        # 1. テスト用のダミー画像ファイルを作成
        img_path = os.path.join(self.temp_dir.name, "test_gauge.jpg")
        with open(img_path, "wb") as f:
            f.write(b"fake image data")

        # 2. モックReader関数の定義
        def mock_reader(path, **kwargs):
            return {"stage": "ok", "value": 100.0, "error": None}

        processor = BatchProcessor(self.manager, self.temp_dir.name)

        # 3. 1回目のバッチ実行（新規処理の検証）
        res1 = processor.process_all(reader_func=mock_reader)
        self.assertEqual(res1["success"], 1)

        # 4. 2回目のバッチ実行（重複スキップの検証）
        res2 = processor.process_all(reader_func=mock_reader)
        self.assertEqual(res2["success"], 0)
        self.assertEqual(len(processor.get_unprocessed_images()), 0)

if __name__ == "__main__":
    unittest.main()