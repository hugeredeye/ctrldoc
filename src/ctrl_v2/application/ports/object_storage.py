from __future__ import annotations

from typing import BinaryIO, Protocol


class ObjectStorage(Protocol):
    def put(
        self,
        key: str,
        content: BinaryIO,
        *,
        expected_sha256: str,
        expected_size_bytes: int,
    ) -> None: ...

    def get(
        self,
        key: str,
        *,
        expected_sha256: str,
        expected_size_bytes: int,
    ) -> bytes: ...

    def exists(self, key: str) -> bool: ...
