"""Shared pytest fixtures.

Every test runs against a throwaway SQLite database in ``tmp_path``; the
production ``smm_traders.db`` is never opened. Test-scoped credentials are
forced into the environment here so results never depend on the developer's
own ``.env`` values (and so a stale real secret can never be used).
"""

import os
import tempfile

# Never load a developer's .env into the test process, and never let the app
# pick up real secrets or database URLs.
os.environ["SMM_SKIP_DOTENV"] = "1"

# Guard: point the app at scratch files before importing it. The env var is
# honoured by db.SQLITE_PATH at import time.
os.environ["SMM_TRADERS_DB"] = os.path.join(
    tempfile.mkdtemp(prefix="smm_guard_"), "import_guard.db"
)
os.environ.pop("TURSO_DATABASE_URL", None)
os.environ.pop("TURSO_AUTH_TOKEN", None)
os.environ["ADMIN_USERNAME"] = "SMMTRADERS"
os.environ["SESSION_SECRET"] = "test-session-secret-never-used-in-production"
os.environ["COOKIE_SECURE"] = "0"

import pytest  # noqa: E402

import auth  # noqa: E402
import db  # noqa: E402
import main  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

TEST_PASSWORD = "test-password-123"
os.environ["ADMIN_PASSWORD_HASH"] = auth.hash_password(TEST_PASSWORD)


class AuthedClient:
    """TestClient wrapper that signs in and adds the CSRF header for writes."""

    def __init__(self, client, csrf_token, username):
        self._client = client
        self.csrf_token = csrf_token
        self.username = username

    def _headers(self, method, headers):
        merged = dict(headers or {})
        if method.upper() in ("POST", "PUT", "PATCH", "DELETE"):
            merged.setdefault("X-CSRF-Token", self.csrf_token)
        return merged

    def request(self, method, url, **kwargs):
        kwargs["headers"] = self._headers(method, kwargs.get("headers"))
        return self._client.request(method, url, **kwargs)

    def get(self, url, **kwargs):
        return self._client.get(url, **kwargs)

    def post(self, url, **kwargs):
        return self.request("POST", url, **kwargs)

    def put(self, url, **kwargs):
        return self.request("PUT", url, **kwargs)

    def delete(self, url, **kwargs):
        return self.request("DELETE", url, **kwargs)

    def __getattr__(self, name):
        return getattr(self._client, name)


@pytest.fixture()
def raw_client(tmp_path, monkeypatch):
    """Unauthenticated client backed by a fresh scratch database."""
    monkeypatch.setattr(db, "SQLITE_PATH", str(tmp_path / "test.db"))
    with TestClient(main.app) as c:
        yield c


@pytest.fixture()
def client(raw_client):
    """Signed-in client (CSRF header injected automatically on writes)."""
    resp = raw_client.post(
        "/api/auth/login",
        json={"username": os.environ["ADMIN_USERNAME"], "password": TEST_PASSWORD},
    )
    assert resp.status_code == 200, resp.text
    return AuthedClient(raw_client, resp.json()["csrf_token"], os.environ["ADMIN_USERNAME"])


@pytest.fixture()
def db_path(tmp_path, monkeypatch):
    """Path of the scratch database a client fixture is using."""
    path = str(tmp_path / "test.db")
    monkeypatch.setattr(db, "SQLITE_PATH", path)
    return path
