import os
import tempfile
import unittest

from manager.batch import BatchProcessor, calculate_file_hash
from manager.manager import MeterManager


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

    def test_deduplication_by_content_hash_copied_file(self):
        # 1. 元のテスト画像を作成
        img_path1 = os.path.join(self.temp_dir.name, "gauge_original.jpg")
        with open(img_path1, "wb") as f:
            f.write(b"same meter gauge image content")

        def mock_reader(path, **kwargs):
            return {"stage": "ok", "value": 50.0, "error": None}

        processor = BatchProcessor(self.manager, self.temp_dir.name)

        # 2. 1回目のバッチ実行（元画像を処理）
        res1 = processor.process_all(reader_func=mock_reader)
        self.assertEqual(res1["success"], 1)

        # 3. 同じ内容の画像を別名でコピーして配置
        img_path2 = os.path.join(self.temp_dir.name, "gauge_copy.jpg")
        with open(img_path2, "wb") as f:
            f.write(b"same meter gauge image content")

        # 4. 未処理画像一覧を取得（別名コピーだがハッシュが同一のため除外されるべき）
        unprocessed = processor.get_unprocessed_images()
        self.assertEqual(len(unprocessed), 0)

        # 5. バッチ実行しても二重取り込みされない（スキップされる）
        res2 = processor.process_all(reader_func=mock_reader)
        self.assertEqual(res2["success"], 0)

    def test_calculate_file_hash(self):
        test_file = os.path.join(self.temp_dir.name, "hash_test.dat")
        with open(test_file, "wb") as f:
            f.write(b"hello world")

        # sha256 of "hello world" is b94d27b9934d3e08a52e52d7da7dabfac484efe37a5380ee9088f7ace2efcde9
        expected = "b94d27b9934d3e08a52e52d7da7dabfac484efe37a5380ee9088f7ace2efcde9"
        self.assertEqual(calculate_file_hash(test_file), expected)


if __name__ == "__main__":
    unittest.main()