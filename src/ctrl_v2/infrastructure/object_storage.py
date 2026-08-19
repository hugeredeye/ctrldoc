from __future__ import annotations

import hashlib
import os
import re
from pathlib import Path
from typing import BinaryIO
from uuid import uuid4

from ctrl_v2.domain.exceptions import ObjectIntegrityError

_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")
_CHUNK_SIZE = 1024 * 1024


class PrivateFileObjectStorage:
    """Create-only local storage with content-bound, verified object reads."""

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self._ensure_private_directory(self.root)

    def _path(self, key: str) -> Path:
        candidate = (self.root / key).resolve()
        if self.root not in candidate.parents:
            raise ValueError("Invalid object key")
        return candidate

    def put(
        self,
        key: str,
        content: BinaryIO,
        *,
        expected_sha256: str,
        expected_size_bytes: int,
    ) -> None:
        self._validate_expectations(expected_sha256, expected_size_bytes)
        self._validate_content_bound_key(key, expected_sha256)
        destination = self._path(key)
        self._ensure_private_directory(destination.parent)
        temporary = destination.parent / f".{destination.name}.{uuid4().hex}.tmp"
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        digest = hashlib.sha256()
        size_bytes = 0
        try:
            with os.fdopen(descriptor, "wb") as output:
                while chunk := content.read(_CHUNK_SIZE):
                    digest.update(chunk)
                    size_bytes += len(chunk)
                    output.write(chunk)
                output.flush()
                os.fsync(output.fileno())
            self._assert_integrity(
                digest.hexdigest(),
                size_bytes,
                expected_sha256,
                expected_size_bytes,
            )
            try:
                os.link(temporary, destination)
            except FileExistsError:
                self._read_verified_path(
                    destination,
                    expected_sha256,
                    expected_size_bytes,
                )
                return
            os.chmod(destination, 0o600)
            self._fsync_directory(destination.parent)
            self._read_verified_path(
                destination,
                expected_sha256,
                expected_size_bytes,
            )
        finally:
            temporary.unlink(missing_ok=True)

    def get(
        self,
        key: str,
        *,
        expected_sha256: str,
        expected_size_bytes: int,
    ) -> bytes:
        self._validate_expectations(expected_sha256, expected_size_bytes)
        self._validate_content_bound_key(key, expected_sha256)
        return self._read_verified_path(
            self._path(key),
            expected_sha256,
            expected_size_bytes,
        )

    def exists(self, key: str) -> bool:
        return self._path(key).is_file()

    @staticmethod
    def _validate_expectations(expected_sha256: str, expected_size_bytes: int) -> None:
        if _SHA256_PATTERN.fullmatch(expected_sha256) is None or expected_size_bytes < 0:
            raise ObjectIntegrityError("Stored object metadata is invalid")

    @staticmethod
    def _validate_content_bound_key(key: str, expected_sha256: str) -> None:
        if expected_sha256 not in key:
            raise ObjectIntegrityError("Object key does not bind the expected SHA-256")

    @staticmethod
    def _assert_integrity(
        actual_sha256: str,
        actual_size_bytes: int,
        expected_sha256: str,
        expected_size_bytes: int,
    ) -> None:
        if actual_sha256 != expected_sha256 or actual_size_bytes != expected_size_bytes:
            raise ObjectIntegrityError("Stored object failed integrity verification")

    def _read_verified_path(
        self,
        path: Path,
        expected_sha256: str,
        expected_size_bytes: int,
    ) -> bytes:
        try:
            payload = path.read_bytes()
        except FileNotFoundError as exc:
            raise ObjectIntegrityError("Stored object is missing") from exc
        self._assert_integrity(
            hashlib.sha256(payload).hexdigest(),
            len(payload),
            expected_sha256,
            expected_size_bytes,
        )
        return payload

    @staticmethod
    def _ensure_private_directory(path: Path) -> None:
        path.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(path, 0o700)

    @staticmethod
    def _fsync_directory(path: Path) -> None:
        try:
            descriptor = os.open(path, os.O_RDONLY)
        except OSError:
            return
        try:
            os.fsync(descriptor)
        except OSError:
            pass
        finally:
            os.close(descriptor)
