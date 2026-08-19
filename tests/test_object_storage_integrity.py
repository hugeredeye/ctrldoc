from __future__ import annotations

import hashlib
import os
import stat
from io import BytesIO

import pytest

from ctrl_v2.domain.exceptions import ObjectIntegrityError
from ctrl_v2.infrastructure.object_storage import PrivateFileObjectStorage


def _digest(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _put(storage: PrivateFileObjectStorage, key: str, payload: bytes) -> None:
    storage.put(
        key,
        BytesIO(payload),
        expected_sha256=_digest(payload),
        expected_size_bytes=len(payload),
    )


def _get(storage: PrivateFileObjectStorage, key: str, payload: bytes) -> bytes:
    return storage.get(
        key,
        expected_sha256=_digest(payload),
        expected_size_bytes=len(payload),
    )


def test_mutated_object_fails_closed(tmp_path):
    storage = PrivateFileObjectStorage(tmp_path / "objects")
    payload = b"trusted-source-bytes"
    key = f"workspace/documents/version/{_digest(payload)}"
    _put(storage, key, payload)

    (storage.root / key).write_bytes(b"tampered-source-bytes")

    with pytest.raises(ObjectIntegrityError, match="integrity verification"):
        _get(storage, key, payload)


def test_truncated_object_fails_closed(tmp_path):
    storage = PrivateFileObjectStorage(tmp_path / "objects")
    payload = b"trusted-source-bytes"
    key = f"workspace/documents/version/{_digest(payload)}"
    _put(storage, key, payload)

    with (storage.root / key).open("r+b") as output:
        output.truncate(4)

    with pytest.raises(ObjectIntegrityError, match="integrity verification"):
        _get(storage, key, payload)


def test_second_put_with_different_bytes_is_rejected(tmp_path):
    storage = PrivateFileObjectStorage(tmp_path / "objects")
    original = b"immutable-original"
    replacement = b"replacement-content"
    key = f"workspace/documents/version/{_digest(original)}"
    _put(storage, key, original)

    with pytest.raises(ObjectIntegrityError, match="integrity verification"):
        storage.put(
            key,
            BytesIO(replacement),
            expected_sha256=_digest(original),
            expected_size_bytes=len(original),
        )

    assert _get(storage, key, original) == original


def test_same_content_put_is_idempotent_and_leaves_no_temporary_file(tmp_path):
    storage = PrivateFileObjectStorage(tmp_path / "objects")
    payload = b"idempotent-content"
    key = f"workspace/documents/version/{_digest(payload)}"

    _put(storage, key, payload)
    _put(storage, key, payload)

    destination = storage.root / key
    assert _get(storage, key, payload) == payload
    assert not list(destination.parent.glob("*.tmp"))
    if os.name != "nt":
        assert stat.S_IMODE(storage.root.stat().st_mode) == 0o700
        assert stat.S_IMODE(destination.stat().st_mode) == 0o600


def test_put_rejects_incorrect_expected_metadata_without_publishing(tmp_path):
    storage = PrivateFileObjectStorage(tmp_path / "objects")
    payload = b"actual-content"
    key = f"workspace/documents/version/{'0' * 64}"

    with pytest.raises(ObjectIntegrityError, match="integrity verification"):
        storage.put(
            key,
            BytesIO(payload),
            expected_sha256="0" * 64,
            expected_size_bytes=len(payload),
        )

    assert not storage.exists(key)


def test_object_key_must_bind_expected_digest(tmp_path):
    storage = PrivateFileObjectStorage(tmp_path / "objects")
    payload = b"content-bound-identity"

    with pytest.raises(ObjectIntegrityError, match="does not bind"):
        storage.put(
            "workspace/documents/version/not-content-addressed",
            BytesIO(payload),
            expected_sha256=_digest(payload),
            expected_size_bytes=len(payload),
        )


def test_object_key_cannot_escape_private_root(tmp_path):
    storage = PrivateFileObjectStorage(tmp_path / "objects")

    with pytest.raises(ValueError, match="Invalid object key"):
        storage.exists("../outside")
