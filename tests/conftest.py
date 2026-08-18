from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from ctrl_v2.interfaces.http.app import create_app
from ctrl_v2.interfaces.http.config import Settings


@pytest.fixture()
def client(tmp_path):
    settings = Settings(
        database_url=f"sqlite:///{(tmp_path / 'ctrl.db').as_posix()}",
        object_storage_root=tmp_path / "private-objects",
        create_schema=True,
        log_level="INFO",
    )
    app = create_app(settings)
    with TestClient(app) as test_client:
        yield test_client
