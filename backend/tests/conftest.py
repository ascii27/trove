from __future__ import annotations

import os

import pytest

from app import db


@pytest.fixture
def db_path(tmp_path):
    path = str(tmp_path / "trove_test.db")
    db.init_db(path)
    return path


@pytest.fixture
def conn(db_path):
    c = db.connect(db_path)
    try:
        yield c
    finally:
        c.close()


@pytest.fixture
def client(tmp_path, monkeypatch):
    """A TestClient wired to a temp DB with the background worker disabled."""
    from fastapi.testclient import TestClient

    path = str(tmp_path / "trove_api.db")
    monkeypatch.setenv("TROVE_DB_PATH", path)
    monkeypatch.setenv("TROVE_DISABLE_WORKER", "1")

    from app.main import create_app

    app = create_app()
    with TestClient(app) as tc:
        yield tc
