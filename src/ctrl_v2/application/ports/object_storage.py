from __future__ import annotations

from typing import BinaryIO, Protocol


class ObjectStorage(Protocol):
    def put(self, key: str, content: BinaryIO) -> None: ...

    def get(self, key: str) -> bytes: ...

    def exists(self, key: str) -> bool: ...
