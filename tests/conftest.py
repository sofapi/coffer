"""Shared fixtures. Every test gets its own throwaway SQLite file.

DB_PATH is read at import time by db.py, so it must be set before app/db are
imported — hence the environment variable dance before the fixtures run.
"""

import os
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


@pytest.fixture()
def db_path(monkeypatch):
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "coffer.db")
        monkeypatch.setenv("DB_PATH", path)
        import db as db_module
        monkeypatch.setattr(db_module, "DB_PATH", path)
        db_module.init_db()
        yield path


@pytest.fixture()
def conn(db_path):
    import db as db_module
    connection = db_module.get_db()
    yield connection
    connection.close()


@pytest.fixture()
def client(db_path):
    import app as app_module
    app_module.app.config.update(TESTING=True)
    with app_module.app.test_client() as test_client:
        yield test_client
