import os
import shutil

from manager.batch import calculate_file_hash


_SUPPORTED_EXTENSIONS = {".jpg", ".jpeg", ".png"}


def image_path_for(image_sha256: str, images_dir: str, ext: str) -> str:
    """内容ハッシュと拡張子から原画像の保存先パスを組み立てる。"""
    return os.path.abspath(os.path.join(images_dir, f"{image_sha256}{ext.lower()}"))


def store_image(src_path: str, images_dir: str) -> str:
    """原画像を内容ハッシュ名で保存し、保存先の絶対パスを返す。"""
    if not os.path.exists(src_path):
        raise FileNotFoundError(src_path)

    ext = os.path.splitext(src_path)[1].lower()
    if ext not in _SUPPORTED_EXTENSIONS:
        raise ValueError(f"Unsupported image extension: {ext}")

    stored_path = image_path_for(calculate_file_hash(src_path), images_dir, ext)
    os.makedirs(images_dir, exist_ok=True)
    if not os.path.exists(stored_path):
        shutil.copy2(src_path, stored_path)
    return stored_path


def verify_stored_image(stored_path: str) -> bool:
    """保存ファイルの名前に含まれるハッシュと内容ハッシュが一致するか確認する。"""
    expected_hash = os.path.splitext(os.path.basename(stored_path))[0]
    return calculate_file_hash(stored_path) == expected_hash
