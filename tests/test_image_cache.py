import os
import shutil
import tempfile
import unittest
from unittest.mock import patch
from PIL import Image

from image_cache import get_thumbnail_path


class TestImageCache(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.cache_dir = os.path.join(self.temp_dir, "cache", "thumbs")

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _create_test_image(self, filename: str, size: tuple, color: tuple = (255, 0, 0), mode: str = "RGB") -> str:
        path = os.path.join(self.temp_dir, filename)
        img = Image.new(mode, size, color)
        img.save(path)
        return path

    def test_thumbnail_generation_size_and_extension(self):
        """縮小画像の長辺が800px以下であり、拡張子が.jpgであることを検証。"""
        # 1200x1500 (長辺1500px)
        img_path = self._create_test_image("large.png", (1200, 1500))
        
        thumb_path = get_thumbnail_path(img_path, max_size=800, quality=85, cache_dir=self.cache_dir)
        
        self.assertIsNotNone(thumb_path)
        self.assertTrue(os.path.exists(thumb_path))
        self.assertTrue(thumb_path.endswith(".jpg"))
        
        with Image.open(thumb_path) as thumb:
            self.assertEqual(thumb.format, "JPEG")
            self.assertEqual(thumb.mode, "RGB")
            width, height = thumb.size
            self.assertLessEqual(max(width, height), 800)
            self.assertEqual(height, 800)
            self.assertEqual(width, 640)

    def test_thumbnail_cache_reuse(self):
        """2回目の呼び出し時に既存のキャッシュファイルが再利用され、画像デコードが走らないことを検証。"""
        img_path = self._create_test_image("test_reuse.png", (1000, 1000))
        
        # 1回目: キャッシュ生成
        path1 = get_thumbnail_path(img_path, cache_dir=self.cache_dir)
        self.assertIsNotNone(path1)
        self.assertTrue(os.path.exists(path1))
        
        # 2回目: キャッシュ再利用（Image.openが呼ばれないことを検証）
        with patch("PIL.Image.open") as mock_open:
            path2 = get_thumbnail_path(img_path, cache_dir=self.cache_dir)
            mock_open.assert_not_called()
            
        self.assertEqual(path1, path2)

    def test_file_not_found(self):
        """元ファイルが存在しない場合にNoneを返すことを検証。"""
        non_existent = os.path.join(self.temp_dir, "non_existent.jpg")
        self.assertIsNone(get_thumbnail_path(non_existent, cache_dir=self.cache_dir))
        self.assertIsNone(get_thumbnail_path("", cache_dir=self.cache_dir))
        self.assertIsNone(get_thumbnail_path(None, cache_dir=self.cache_dir))

    def test_corrupt_file(self):
        """元ファイルが破損している場合に例外を出さずNoneを返すことを検証。"""
        corrupt_path = os.path.join(self.temp_dir, "corrupt.png")
        with open(corrupt_path, "wb") as f:
            f.write(b"not an image binary header corrupted")
            
        thumb_path = get_thumbnail_path(corrupt_path, cache_dir=self.cache_dir)
        self.assertIsNone(thumb_path)

    def test_small_image_not_enlarged(self):
        """長辺が800px未満の元画像は拡大されないことを検証。"""
        small_path = self._create_test_image("small.png", (300, 200))
        thumb_path = get_thumbnail_path(small_path, max_size=800, cache_dir=self.cache_dir)
        
        self.assertIsNotNone(thumb_path)
        with Image.open(thumb_path) as thumb:
            self.assertEqual(thumb.size, (300, 200))

    def test_rgba_image_converted_to_rgb(self):
        """RGBA画像が適切にRGBに変換されてJPEG保存できることを検証。"""
        rgba_path = self._create_test_image("transparent.png", (900, 900), color=(0, 255, 0, 128), mode="RGBA")
        thumb_path = get_thumbnail_path(rgba_path, cache_dir=self.cache_dir)
        
        self.assertIsNotNone(thumb_path)
        with Image.open(thumb_path) as thumb:
            self.assertEqual(thumb.mode, "RGB")
            self.assertEqual(thumb.format, "JPEG")


if __name__ == "__main__":
    unittest.main()
