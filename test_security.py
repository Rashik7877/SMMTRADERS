"""Security-focused tests for the SuperAdmin layer.

Covers authentication, session handling, CSRF, rate limiting, fail-closed
behaviour and the migration tool's rehearsal modes. All tests use scratch
databases from conftest.py and never touch production data.
"""

import hashlib
import os
import secrets
import sqlite3
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import auth
import db
import main
from fastapi.testclient import TestClient

TEST_USERNAME = "SMMTRADERS"
TEST_PASSWORD = "test-password-123"

PROTECTED_API = [
    ("GET", "/api/settings"),
    ("PUT", "/api/settings"),
    ("GET", "/api/bookings"),
    ("GET", "/api/bookings/1"),
    ("GET", "/api/bookings/by-token/SMM0001"),
    ("GET", "/api/scan?code=SMM0001"),
    ("GET", "/api/reports/daily?date=2026-01-01"),
    ("GET", "/api/reports/weekly?date=2026-01-01"),
    ("GET", "/api/reports/monthly?month=2026-01"),
    ("GET", "/api/reports/custom?start=2026-01-01&end=2026-01-31"),
    ("GET", "/api/reports/pdf?report_type=daily&date=2026-01-01"),
    ("POST", "/api/bookings"),
    ("POST", "/api/bookings/1/collect"),
    ("POST", "/api/bookings/1/payment"),
    ("POST", "/api/auth/logout"),
]


# --- Authentication ---------------------------------------------------------

def test_login_success_sets_hardened_cookie(raw_client):
    resp = raw_client.post(
        "/api/auth/login", json={"username": TEST_USERNAME, "password": TEST_PASSWORD}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["username"] == TEST_USERNAME
    assert body["csrf_token"]
    cookie = resp.headers["set-cookie"]
    assert auth.SESSION_COOKIE in cookie
    assert "HttpOnly" in cookie
    assert "SameSite=lax" in cookie
    assert "Path=/" in cookie


def test_login_wrong_password_and_unknown_user_share_message(raw_client):
    wrong_pw = raw_client.post(
        "/api/auth/login", json={"username": TEST_USERNAME, "password": "wrong-pass"}
    )
    unknown = raw_client.post(
        "/api/auth/login", json={"username": "nobody", "password": TEST_PASSWORD}
    )
    assert wrong_pw.status_code == 401
    assert unknown.status_code == 401
    assert wrong_pw.json()["detail"] == unknown.json()["detail"]
    assert wrong_pw.json()["detail"] == "Invalid username or password."


def test_username_match_is_case_insensitive(raw_client):
    resp = raw_client.post(
        "/api/auth/login", json={"username": "smmtraders", "password": TEST_PASSWORD}
    )
    assert resp.status_code == 200


def test_login_failure_leaks_no_configuration_details(raw_client):
    resp = raw_client.post(
        "/api/auth/login", json={"username": TEST_USERNAME, "password": "nope"}
    )
    text = resp.text.lower()
    for needle in ("scrypt", "hash", "session_secret", "tracedb", "turso", ".db", "sqlite"):
        assert needle not in text


def test_login_without_configuration_returns_503(raw_client, monkeypatch):
    monkeypatch.delenv("ADMIN_PASSWORD_HASH", raising=False)
    resp = raw_client.post(
        "/api/auth/login", json={"username": TEST_USERNAME, "password": TEST_PASSWORD}
    )
    assert resp.status_code == 503
    assert "scrypt" not in resp.text.lower()


def test_missing_password_hash_blocks_session_resolution(raw_client, monkeypatch):
    login = raw_client.post(
        "/api/auth/login", json={"username": TEST_USERNAME, "password": TEST_PASSWORD}
    )
    assert login.status_code == 200
    monkeypatch.delenv("ADMIN_PASSWORD_HASH", raising=False)
    assert raw_client.get("/api/settings").status_code == 401


def test_login_without_session_secret_returns_503(raw_client, monkeypatch):
    monkeypatch.delenv("SESSION_SECRET", raising=False)
    resp = raw_client.post(
        "/api/auth/login", json={"username": TEST_USERNAME, "password": TEST_PASSWORD}
    )
    assert resp.status_code == 503


# --- Rate limiting ----------------------------------------------------------

def test_rate_limit_blocks_after_five_failures(raw_client):
    for _ in range(5):
        resp = raw_client.post(
            "/api/auth/login",
            json={"username": TEST_USERNAME, "password": "wrong"},
        )
        assert resp.status_code == 401
    blocked = raw_client.post(
        "/api/auth/login", json={"username": TEST_USERNAME, "password": "wrong"}
    )
    assert blocked.status_code == 429
    # Even the correct password is refused while the window is active.
    still_blocked = raw_client.post(
        "/api/auth/login", json={"username": TEST_USERNAME, "password": TEST_PASSWORD}
    )
    assert still_blocked.status_code == 429


def test_successful_login_clears_failure_counter(raw_client):
    for _ in range(3):
        raw_client.post(
            "/api/auth/login", json={"username": TEST_USERNAME, "password": "wrong"}
        )
    ok = raw_client.post(
        "/api/auth/login", json={"username": TEST_USERNAME, "password": TEST_PASSWORD}
    )
    assert ok.status_code == 200
    for _ in range(4):
        resp = raw_client.post(
            "/api/auth/login", json={"username": TEST_USERNAME, "password": "wrong"}
        )
        assert resp.status_code == 401  # counter restarted, still below limit


# --- Default-deny for protected endpoints -----------------------------------

@pytest.mark.parametrize("method,path", PROTECTED_API)
def test_unauthenticated_requests_are_rejected(raw_client, method, path):
    resp = raw_client.request(method, path, json={})
    assert resp.status_code == 401
    assert resp.json()["detail"] == "Not authenticated"


def test_root_redirects_to_login_when_anonymous(raw_client):
    resp = raw_client.get("/", follow_redirects=False)
    assert resp.status_code == 302
    assert resp.headers["location"] == "/login"


def test_root_serves_app_when_authenticated(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert "html" in resp.headers["content-type"]


def test_login_page_redirects_away_when_authenticated(client):
    resp = client.get("/login", follow_redirects=False)
    assert resp.status_code == 302
    assert resp.headers["location"] == "/"


def test_public_paths_are_reachable_without_a_session(raw_client):
    assert raw_client.get("/health").status_code == 200
    assert raw_client.get("/login").status_code == 200
    assert raw_client.get("/api/auth/session").status_code == 200
    assert raw_client.get("/static/js/app.js").status_code == 200


def test_health_endpoint_exposes_no_secrets(raw_client):
    body = raw_client.get("/health").json()
    assert body == {"status": "ok"}


# --- CSRF -------------------------------------------------------------------

def test_state_change_without_csrf_header_is_rejected(raw_client):
    raw_client.post(
        "/api/auth/login", json={"username": TEST_USERNAME, "password": TEST_PASSWORD}
    )
    resp = raw_client.post("/api/bookings", json={
        "customer_name": "X", "phone": "9876543210", "function_date": "2026-12-01",
    })
    assert resp.status_code == 403
    assert "csrf" in resp.json()["detail"].lower()


def test_state_change_with_wrong_csrf_token_is_rejected(raw_client):
    raw_client.post(
        "/api/auth/login", json={"username": TEST_USERNAME, "password": TEST_PASSWORD}
    )
    resp = raw_client.post(
        "/api/bookings",
        json={"customer_name": "X", "phone": "9876543210", "function_date": "2026-12-01"},
        headers={"X-CSRF-Token": "forged-token"},
    )
    assert resp.status_code == 403


def test_reads_do_not_require_csrf(raw_client):
    raw_client.post(
        "/api/auth/login", json={"username": TEST_USERNAME, "password": TEST_PASSWORD}
    )
    assert raw_client.get("/api/settings").status_code == 200


def test_csrf_token_rotates_on_new_login(raw_client):
    first = raw_client.post(
        "/api/auth/login", json={"username": TEST_USERNAME, "password": TEST_PASSWORD}
    ).json()["csrf_token"]
    second = raw_client.post(
        "/api/auth/login", json={"username": TEST_USERNAME, "password": TEST_PASSWORD}
    ).json()["csrf_token"]
    assert first and second and first != second


# --- Sessions ---------------------------------------------------------------

def test_logout_invalidates_the_session(raw_client):
    login = raw_client.post(
        "/api/auth/login", json={"username": TEST_USERNAME, "password": TEST_PASSWORD}
    )
    csrf = login.json()["csrf_token"]
    assert raw_client.post(
        "/api/auth/logout", headers={"X-CSRF-Token": csrf}
    ).status_code == 200
    assert raw_client.get("/api/settings").status_code == 401


def test_login_rotates_away_the_previous_session(raw_client):
    first = raw_client.post(
        "/api/auth/login", json={"username": TEST_USERNAME, "password": TEST_PASSWORD}
    )
    old_cookie = raw_client.cookies.get(auth.SESSION_COOKIE)
    assert old_cookie
    second = raw_client.post(
        "/api/auth/login", json={"username": TEST_USERNAME, "password": TEST_PASSWORD}
    )
    assert second.status_code == 200
    # Replay the previous cookie: it must no longer be accepted.
    raw_client.cookies.set(auth.SESSION_COOKIE, old_cookie)
    assert raw_client.get("/api/settings").status_code == 401


def test_expired_session_is_rejected(raw_client, db_path):
    login = raw_client.post(
        "/api/auth/login", json={"username": TEST_USERNAME, "password": TEST_PASSWORD}
    )
    assert login.status_code == 200
    token = raw_client.cookies.get(auth.SESSION_COOKIE).rpartition(".")[0]
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    past = (datetime.now(timezone.utc) - timedelta(minutes=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    with sqlite3.connect(db_path) as conn:
        conn.execute("UPDATE sessions SET expires_at = ? WHERE token_hash = ?", (past, token_hash))
    assert raw_client.get("/api/settings").status_code == 401


def test_tampered_cookie_signature_is_rejected(raw_client):
    raw_client.post(
        "/api/auth/login", json={"username": TEST_USERNAME, "password": TEST_PASSWORD}
    )
    cookie = raw_client.cookies.get(auth.SESSION_COOKIE)
    token, _, signature = cookie.rpartition(".")
    forged = token + "." + ("A" if signature[-1] != "A" else "B") + signature[1:]
    raw_client.cookies.set(auth.SESSION_COOKIE, forged)
    assert raw_client.get("/api/settings").status_code == 401


def test_cookie_signed_with_other_secret_is_rejected(raw_client, monkeypatch):
    token = secrets.token_urlsafe(32)
    monkeypatch.setenv("SESSION_SECRET", "attacker-controlled-secret")
    forged = f"{token}.{auth._sign(token)}"
    monkeypatch.setenv("SESSION_SECRET", "test-session-secret-never-used-in-production")
    raw_client.cookies.set(auth.SESSION_COOKIE, forged)
    assert raw_client.get("/api/settings").status_code == 401


def test_session_endpoint_reports_state(raw_client):
    assert raw_client.get("/api/auth/session").json() == {
        "authenticated": False, "csrf_token": None, "username": None,
    }
    raw_client.post(
        "/api/auth/login", json={"username": TEST_USERNAME, "password": TEST_PASSWORD}
    )
    body = raw_client.get("/api/auth/session").json()
    assert body["authenticated"] is True
    assert body["username"] == TEST_USERNAME
    assert body["csrf_token"]


# --- Fail-closed database behaviour -----------------------------------------

def test_vercel_without_turso_configuration_returns_503(raw_client, monkeypatch):
    # Sign in while SQLite is still available, then switch to a
    # Vercel-without-Turso environment: resolving the session must fail
    # closed with 503 rather than leaking or falling back.
    assert raw_client.post(
        "/api/auth/login", json={"username": TEST_USERNAME, "password": TEST_PASSWORD}
    ).status_code == 200
    monkeypatch.setenv("VERCEL", "1")
    monkeypatch.delenv("TURSO_DATABASE_URL", raising=False)
    monkeypatch.delenv("TURSO_AUTH_TOKEN", raising=False)
    resp = raw_client.get("/api/settings")
    assert resp.status_code == 503
    assert "turso" not in resp.text.lower()
    assert "sqlite" not in resp.text.lower()


def test_vercel_login_without_database_returns_503(raw_client, monkeypatch):
    monkeypatch.setenv("VERCEL", "1")
    monkeypatch.delenv("TURSO_DATABASE_URL", raising=False)
    resp = raw_client.post(
        "/api/auth/login", json={"username": TEST_USERNAME, "password": TEST_PASSWORD}
    )
    assert resp.status_code == 503


def test_health_still_works_without_database(raw_client, monkeypatch):
    monkeypatch.setenv("VERCEL", "1")
    monkeypatch.delenv("TURSO_DATABASE_URL", raising=False)
    assert raw_client.get("/health").status_code == 200


# --- Password hashing -------------------------------------------------------

def test_password_hash_is_salted_and_verifies():
    h1 = auth.hash_password("same-password")
    h2 = auth.hash_password("same-password")
    assert h1 != h2  # random salt each time
    assert auth.verify_password("same-password", h1)
    assert auth.verify_password("same-password", h2)
    assert not auth.verify_password("different", h1)


@pytest.mark.parametrize("stored", ["", "garbage", "bcrypt$1$2", "scrypt$bad"])
def test_verify_password_survives_malformed_hashes(stored):
    assert auth.verify_password("anything", stored) is False


# --- Concurrency ------------------------------------------------------------

def test_concurrent_bookings_get_unique_tokens(db_path, monkeypatch):
    monkeypatch.setattr(db, "SQLITE_PATH", db_path)
    with TestClient(main.app):
        pass  # create the schema

    def create(index):
        payload = main.CreateBookingSchema(
            customer_name=f"Customer {index}",
            phone="9876543210",
            function_date="2026-12-01",
            mutton_qty=1.0,
            chicken_qty=0.0,
        )
        last_error = None
        for _ in range(4):  # tolerate momentary SQLite lock contention
            try:
                return main.create_booking(payload)["token_number"]
            except Exception as exc:  # noqa: BLE001 - retry then re-raise
                last_error = exc
        raise last_error

    workers = 8
    with ThreadPoolExecutor(max_workers=workers) as pool:
        tokens = list(pool.map(create, range(workers)))

    assert len(tokens) == workers
    assert len(set(tokens)) == workers  # every token unique
    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(
            "SELECT COUNT(*), COUNT(DISTINCT token_number) FROM bookings"
        ).fetchone()
    assert rows[0] == rows[1] == workers


# --- Migration tool rehearsal ----------------------------------------------

MIGRATION = str(Path(__file__).parent / "scripts" / "migrate_sqlite_to_turso.py")


def _run_migration(source, target, *extra):
    env = dict(os.environ)
    env["PYTHONPATH"] = str(Path(__file__).parent)
    return subprocess.run(
        [sys.executable, MIGRATION, "--sqlite", source, "--target-sqlite", target,
         "--report", str(Path(target).parent / "report.txt"), *extra],
        capture_output=True, text=True, env=env,
    )


def _seed_source(path):
    import db as dbmod

    with dbmod.connect_sqlite(str(path)) as conn:
        dbmod.ensure_schema(conn)
        conn.execute(
            "INSERT INTO bookings (token_number, customer_name, phone, booking_date,"
            " function_date, mutton_qty, mutton_price_per_kg, chicken_qty,"
            " chicken_price_per_kg, grand_total, advance_paid, balance, status)"
            " VALUES ('SMM0001', 'Seed', '9876543210', '2026-01-01', '2026-02-01',"
            " 2.0, 100.0, 0.0, 0.0, 200.0, 50.0, 150.0, 'pending')"
        )
        conn.execute(
            "INSERT INTO payments (booking_id, amount, payment_date, notes)"
            " VALUES (last_insert_rowid(), 50.0, '2026-01-01', 'Advance')"
        )
        conn.commit()


def test_migration_rehearsal_is_idempotent(tmp_path):
    source = tmp_path / "src.db"
    target = tmp_path / "tgt.db"
    _seed_source(source)
    first = _run_migration(str(source), str(target))
    assert first.returncode == 0, first.stdout + first.stderr
    assert "PASS" in first.stdout
    second = _run_migration(str(source), str(target))
    assert second.returncode == 0, second.stdout + second.stderr
    assert "PASS" in second.stdout
    with sqlite3.connect(target) as conn:
        assert conn.execute("SELECT COUNT(*) FROM bookings").fetchone()[0] == 1


def test_migration_detects_conflicts_and_copies_nothing(tmp_path):
    source = tmp_path / "src.db"
    target = tmp_path / "tgt.db"
    _seed_source(source)
    assert _run_migration(str(source), str(target)).returncode == 0
    with sqlite3.connect(target) as conn:
        conn.execute("DELETE FROM payments")
        conn.execute("DELETE FROM bookings")
        conn.execute(
            "INSERT INTO bookings (id, token_number, customer_name, phone,"
            " booking_date, function_date, grand_total, advance_paid, balance)"
            " VALUES (77, 'SMM0001', 'Foreign', '0', '2026-01-01', '2026-01-01',"
            " 0, 0, 0)"
        )
        conn.commit()
    result = _run_migration(str(source), str(target))
    assert result.returncode == 1
    assert "CONFLICT" in (result.stdout + result.stderr).upper()
    with sqlite3.connect(target) as conn:  # untouched apart from the foreign row
        assert conn.execute("SELECT COUNT(*) FROM bookings").fetchone()[0] == 1
        assert conn.execute("SELECT id FROM bookings").fetchone()[0] == 77


def test_migration_verify_only_passes_on_matching_target(tmp_path):
    source = tmp_path / "src.db"
    target = tmp_path / "tgt.db"
    _seed_source(source)
    assert _run_migration(str(source), str(target)).returncode == 0
    result = _run_migration(str(source), str(target), "--verify-only")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "PASS" in result.stdout


def test_migration_report_contains_no_customer_data(tmp_path):
    source = tmp_path / "src.db"
    target = tmp_path / "tgt.db"
    _seed_source(source)
    report = tmp_path / "report.txt"
    result = _run_migration(str(source), str(target))
    assert result.returncode == 0
    text = report.read_text(encoding="utf-8")
    assert "Seed" not in text
    assert "9876543210" not in text
    assert "PASS" in text
