import os

from manager.routes import _file_hash


def pending_images(incoming_dir, storage):
    """Return the count and first five names of received, unprocessed images."""
    processed = storage.get_processed_hashes()
    count, names = 0, []
    try:
        files = os.scandir(incoming_dir)
    except FileNotFoundError:
        return count, names
    with files:
        for entry in sorted(files, key=lambda item: item.name):
            if not entry.name.lower().endswith(('.jpg', '.jpeg', '.png')):
                continue
            try:
                if not entry.is_file(follow_symlinks=False):
                    continue
                stat = entry.stat(follow_symlinks=False)
                digest = _file_hash(entry.path, stat.st_size, stat.st_mtime_ns)
            except FileNotFoundError:
                continue  # A concurrent importer may have moved the image.
            if digest not in processed:
                count += 1
                if len(names) < 5:
                    names.append(entry.name)
    return count, names
