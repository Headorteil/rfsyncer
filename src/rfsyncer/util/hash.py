import hashlib
from pathlib import Path

from rfsyncer.util.consts import BUF_SIZE


def hash_(file: Path) -> str:
    md5 = hashlib.md5()  # noqa: S324
    with file.open("rb") as f:
        while True:
            data = f.read(BUF_SIZE)
            if not data:
                break
            md5.update(data)
    return md5.hexdigest()
