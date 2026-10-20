"""Shared pytest fixtures for the Instafeed test-suite."""

from __future__ import annotations

import contextlib
import os
import sys
import tempfile
import uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# The tests never touch the real Instagram API.
os.environ["INSTAFEED_DEMO"] = "1"
os.environ["INSTAFEED_SCHEDULER"] = "0"
os.environ["INSTAFEED_SECRET_KEY"] = "test-secret-key-not-for-production-use-0123456789"

# The database path must be set BEFORE `backend.config` is imported, which
# happens as soon as a test module is collected. That is why this happens at
# module level rather than inside a fixture.
_TMP_DIR = tempfile.mkdtemp(prefix="instafeed-tests-")
_DB_PATH = Path(_TMP_DIR) / f"test-{uuid.uuid4().hex[:8]}.db"
os.environ["INSTAFEED_DB_PATH"] = str(_DB_PATH)


@pytest.fixture(scope="session", autouse=True)
def _temp_database():
    """Point the app at a throwaway SQLite file and clean it up afterwards."""
    from backend import database as db

    db.init_db()
    yield _DB_PATH
    for path in _DB_PATH.parent.glob("*"):
        with contextlib.suppress(OSError):
            path.unlink()
    with contextlib.suppress(OSError):
        Path(_TMP_DIR).rmdir()


@pytest.fixture(scope="session")
def client(_temp_database):
    """A TestClient bound to the FastAPI app."""
    from fastapi.testclient import TestClient

    from backend.main import app

    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture()
def account(client):
    """Register a fresh account and return (user, token, auth headers)."""
    username = f"tester_{uuid.uuid4().hex[:8]}"
    response = client.post(
        "/api/auth/register",
        json={"username": username, "password": "sup3rsecret!", "email": "t@example.com"},
    )
    assert response.status_code == 201, response.text
    payload = response.json()
    return {
        "user": payload["user"],
        "token": payload["token"],
        "headers": {"Authorization": f"Bearer {payload['token']}"},
    }
