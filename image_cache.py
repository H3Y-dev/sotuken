import hashlib
import os
import time
from typing import Optional
from PIL import Image

DEFAULT_CACHE_DIR = ".cache/thumbs"
DEFAULT_MAX_SIZE = 800
DEFAULT_QUALITY = 85


def get_thumbnail_path(
    image_path: Optional[str],
    max_size: int = DEFAULT_MAX_SIZE,
    quality: int = DEFAULT_QUALITY,
    cache_dir: str = DEFAULT_CACHE_DIR,
) -> Optional[str]:
    """元画像の縮小画像（長辺800px、JPEG品質85）のパスを取得・生成する。

    元ファイルの隣ではなく、.gitignore済みのキャッシュ置き場に保存して再利用する。
    元ファイルが存在しない、または壊れている場合は None を返す。
    """
    if not image_path or not isinstance(image_path, str):
        return None

    if not os.path.isfile(image_path):
        return None

    try:
        mtime = int(os.path.getmtime(image_path))

        # 元ファイルのSHA-1ハッシュ計算
        h = hashlib.sha1()
        with open(image_path, "rb") as f:
            while chunk := f.read(65536):
                h.update(chunk)
        sha1_hex = h.hexdigest()

        os.makedirs(cache_dir, exist_ok=True)
        cache_file_name = f"{sha1_hex}_{mtime}.jpg"
        cache_path = os.path.join(cache_dir, cache_file_name)

        # 既存キャッシュが存在すれば再利用
        if os.path.exists(cache_path) and os.path.getsize(cache_path) > 0:
            return cache_path

        # 縮小画像の生成
        with Image.open(image_path) as img:
            img_to_save = img.copy()

        # JPEG保存のためRGBモードに変換（色は元と同じ）
        if img_to_save.mode != "RGB":
            img_to_save = img_to_save.convert("RGB")

        # 長辺max_size（800px）に縮小（800px以下の場合は拡大しない）
        img_to_save.thumbnail((max_size, max_size), Image.Resampling.LANCZOS)

        # アトミックに保存
        temp_cache_path = f"{cache_path}.{os.getpid()}.{time.time_ns()}.tmp"
        img_to_save.save(temp_cache_path, "JPEG", quality=quality)
        os.replace(temp_cache_path, cache_path)

        return cache_path

    except Exception:
        # 画像破損・読み込み不可などのエラー時は安全に None を返す
        return None
