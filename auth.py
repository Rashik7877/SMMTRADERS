"""SuperAdmin session authentication for SMMTRADERS.

Design notes:

* Credentials come only from environment variables (``ADMIN_USERNAME``,
  ``ADMIN_PASSWORD_HASH``).  Passwords are verified against a salted scrypt
  hash; plaintext is never stored, logged or shipped to the browser.
* Sessions are server-side rows in the database, so they work across
  serverless invocations.  The cookie holds ``<token>.<hmac>``; only the
  SHA-256 of the token is stored, so a database leak cannot be replayed.
* A per-session CSRF token is issued at login and required as the
  ``X-CSRF-Token`` header on every state-changing request.
* Login attempts are rate limited per username + client address using the
  ``login_attempts`` table (shared across invocations).
* Missing configuration fails closed: no session can be created or resolved.
"""

import base64
import hashlib
import hmac
import os
import secrets
from datetime import datetime, timedelta, timezone

from db import DatabaseConfigError, get_db

SESSION_COOKIE = "smm_session"
SESSION_TTL = timedelta(days=7)
LOGIN_WINDOW_MINUTES = 15
LOGIN_MAX_ATTEMPTS = 5
DEFAULT_USERNAME = "SMMTRADERS"

_SCRYPT_N = 2 ** 14
_SCRYPT_R = 8
_SCRYPT_P = 1


# --- Configuration ----------------------------------------------------------

def admin_username() -> str:
    return (os.environ.get("ADMIN_USERNAME") or DEFAULT_USERNAME).strip()


def password_hash_configured() -> bool:
    return bool((os.environ.get("ADMIN_PASSWORD_HASH") or "").strip())


def session_secret() -> str:
    return os.environ.get("SESSION_SECRET") or ""


def credentials_configured() -> bool:
    return password_hash_configured() and bool(session_secret())


# --- Password hashing -------------------------------------------------------

def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    derived = hashlib.scrypt(
        password.encode("utf-8"), salt=salt, n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P,
        dklen=32,
    )
    return "scrypt${}${}${}${}${}".format(
        _SCRYPT_N, _SCRYPT_R, _SCRYPT_P,
        base64.b64encode(salt).decode(), base64.b64encode(derived).decode(),
    )


def verify_password(password: str, stored: str) -> bool:
    try:
        algorithm, n, r, p, salt_b64, hash_b64 = (stored or "").split("$")
        if algorithm != "scrypt":
            return False
        salt = base64.b64decode(salt_b64)
        expected = base64.b64decode(hash_b64)
        derived = hashlib.scrypt(
            password.encode("utf-8"), salt=salt, n=int(n), r=int(r), p=int(p),
            dklen=len(expected),
        )
        return hmac.compare_digest(derived, expected)
    except Exception:
        return False


# --- Time helpers -----------------------------------------------------------

def _now() -> datetime:
    return datetime.now(timezone.utc)


def _now_iso() -> str:
    return _now().strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_iso(text: str) -> datetime:
    return datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


# --- Sessions ---------------------------------------------------------------

def _sign(token: str) -> str:
    secret = session_secret().encode("utf-8")
    return base64.urlsafe_b64encode(
        hmac.new(secret, token.encode("utf-8"), hashlib.sha256).digest()
    ).decode().rstrip("=")


def _cookie_valid(value: str) -> bool:
    if not value or "." not in value:
        return False
    token, _, signature = value.rpartition(".")
    if not token or not signature:
        return False
    return hmac.compare_digest(_sign(token), signature)


def create_session(username: str) -> tuple:
    """Create a fresh session; returns (cookie_value, csrf_token)."""
    token = secrets.token_urlsafe(32)
    csrf_token = secrets.token_urlsafe(24)
    now = _now()
    with get_db() as conn:
        conn.execute(
            "INSERT INTO sessions (token_hash, csrf_token, username,"
            " created_at, expires_at) VALUES (?, ?, ?, ?, ?)",
            (
                hashlib.sha256(token.encode("utf-8")).hexdigest(),
                csrf_token,
                username,
                now.strftime("%Y-%m-%dT%H:%M:%SZ"),
                (now + SESSION_TTL).strftime("%Y-%m-%dT%H:%M:%SZ"),
            ),
        )
    return f"{token}.{_sign(token)}", csrf_token


def resolve_session(cookie_value: str):
    """Return the session dict for a valid, unexpired cookie, else None."""
    if not credentials_configured() or not _cookie_valid(cookie_value or ""):
        return None
    token = cookie_value.rpartition(".")[0]
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    try:
        with get_db() as conn:
            row = conn.execute(
                "SELECT token_hash, csrf_token, username, expires_at"
                " FROM sessions WHERE token_hash = ?",
                (token_hash,),
            ).fetchone()
    except DatabaseConfigError:
        # Misconfiguration must surface as 503, never as a silent 401.
        raise
    except Exception:
        return None
    if not row:
        return None
    try:
        if _parse_iso(row["expires_at"]) <= _now():
            delete_session(token_hash)
            return None
    except Exception:
        return None
    return {
        "token_hash": row["token_hash"],
        "csrf_token": row["csrf_token"],
        "username": row["username"],
    }


def delete_session(token_hash: str) -> None:
    try:
        with get_db() as conn:
            conn.execute("DELETE FROM sessions WHERE token_hash = ?", (token_hash,))
    except Exception:
        pass


def invalidate_existing_session(cookie_value: str) -> None:
    """Drop the session a cookie points at (used before re-login)."""
    if not cookie_value or not _cookie_valid(cookie_value):
        return
    token = cookie_value.rpartition(".")[0]
    delete_session(hashlib.sha256(token.encode("utf-8")).hexdigest())


def csrf_matches(session: dict, header_value: str) -> bool:
    return hmac.compare_digest(session.get("csrf_token", ""), header_value or "")


# --- Login rate limiting ----------------------------------------------------

def _client_key(username: str, client_address: str) -> str:
    raw = f"{(username or '').strip().lower()}|{client_address or ''}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def rate_limit_key(username: str, client_address: str) -> str:
    """Public name for the username + client-address rate limit key."""
    return _client_key(username, client_address)


def rate_limited(key: str, window_minutes: int = LOGIN_WINDOW_MINUTES) -> bool:
    cutoff = (_now() - timedelta(minutes=window_minutes)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    with get_db() as conn:
        row = conn.execute(
            "SELECT COUNT(*) FROM login_attempts"
            " WHERE attempt_key = ? AND attempted_at >= ?",
            (key, cutoff),
        ).fetchone()
        return int(row[0]) >= LOGIN_MAX_ATTEMPTS


def record_failure(key: str) -> None:
    with get_db() as conn:
        conn.execute(
            "INSERT INTO login_attempts (attempt_key, attempted_at) VALUES (?, ?)",
            (key, _now_iso()),
        )
        # Opportunistic cleanup keeps the table small.
        old = (_now() - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
        conn.execute("DELETE FROM login_attempts WHERE attempted_at < ?", (old,))


def clear_failures(key: str) -> None:
    with get_db() as conn:
        conn.execute("DELETE FROM login_attempts WHERE attempt_key = ?", (key,))


# --- Request helpers --------------------------------------------------------

def client_address(request) -> str:
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    if request.client:
        return request.client.host
    return ""


def session_from_request(request):
    return resolve_session(request.cookies.get(SESSION_COOKIE))


def origin_accepted(request) -> bool:
    """Same-origin check for login (no session yet, so no CSRF token)."""
    origin = request.headers.get("origin")
    if not origin:
        return True  # non-browser clients (curl/tests) are not CSRF-capable
    host = request.headers.get("host") or ""
    if not host:
        return False
    return origin in (f"http://{host}", f"https://{host}")


def cookie_options() -> dict:
    secure = os.environ.get("VERCEL") == "1" or os.environ.get(
        "COOKIE_SECURE", ""
    ).lower() in ("1", "true", "yes")
    return {
        "httponly": True,
        "secure": secure,
        "samesite": "lax",
        "path": "/",
        "max_age": int(SESSION_TTL.total_seconds()),
    }


def set_login_cookie(response, cookie_value: str) -> None:
    options = cookie_options()
    response.set_cookie(SESSION_COOKIE, cookie_value, **options)


def clear_login_cookie(response) -> None:
    options = cookie_options()
    response.delete_cookie(SESSION_COOKIE, path=options["path"])
