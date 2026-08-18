from __future__ import annotations

from pathlib import Path
from typing import BinaryIO


class PrivateFileObjectStorage:
    """Local Stage 1 adapter. Its root is never mounted by the HTTP application."""

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        candidate = (self.root / key).resolve()
        if self.root not in candidate.parents:
            raise ValueError("Invalid object key")
        return candidate

    def put(self, key: str, content: BinaryIO) -> None:
        destination = self._path(key)
        destination.parent.mkdir(parents=True, exist_ok=True)
        with destination.open("wb") as output:
            while chunk := content.read(1024 * 1024):
                output.write(chunk)

    def get(self, key: str) -> bytes:
        return self._path(key).read_bytes()

    def exists(self, key: str) -> bool:
        return self._path(key).is_file()
