import calendar
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta, timezone
import logging
import os
import re
import time
import traceback
import uuid
from typing import Any, Dict, List, Optional, Tuple

from fastapi import FastAPI, HTTPException, Query, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator, model_validator

import auth
import db
from db import DATABASE_ERRORS, DatabaseConfigError, get_db
from pdf_reports import build_report_pdf

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")

logger = logging.getLogger("smmtraders")

# Performance diagnostics. Always-on and cheap: every response carries a
# Server-Timing header so the browser devtools show where the time went. A
# one-line summary is logged at DEBUG level; set SMM_PERF=1 to raise it to
# INFO and SMM_PERF_VERBOSE=1 to include the per-statement breakdown.
# Only timings, HTTP verbs, paths (never query strings), status codes and SQL
# keywords/table names are ever recorded - no customer data or values.
_PERF_LOG = os.environ.get("SMM_PERF") == "1"
_PERF_VERBOSE = os.environ.get("SMM_PERF_VERBOSE") == "1"
_PERF_LOG_LEVEL = logging.INFO if _PERF_LOG else logging.DEBUG

# Time JSON serialisation into the request's perf stats without touching any
# endpoint. This is the only global patch; it forwards to the original method
# and never alters the bytes that are sent.
_original_json_render = JSONResponse.render


def _timed_json_render(self, content):
    stats = db.current_perf()
    if stats is None:
        return _original_json_render(self, content)
    started = time.perf_counter()
    try:
        return _original_json_render(self, content)
    finally:
        stats.json_seconds += time.perf_counter() - started


JSONResponse.render = _timed_json_render

# Environment values that must never be written to the logs.
_SENSITIVE_ENV_VARS = (
    "TURSO_DATABASE_URL",
    "TURSO_AUTH_TOKEN",
    "ADMIN_PASSWORD_HASH",
    "SESSION_SECRET",
)


def redact_secrets(text: str) -> str:
    """Replace any configured secret value in ``text`` with ``***``."""
    for name in _SENSITIVE_ENV_VARS:
        value = os.environ.get(name)
        if value:
            text = text.replace(value, "***")
    return text


# Local convenience: load a .env file so start.bat works out of the box.
# Vercel injects real environment variables, and the test suite skips this
# (SMM_SKIP_DOTENV=1) so scratch credentials are never overridden.
if os.environ.get("SMM_SKIP_DOTENV") != "1":
    try:
        from dotenv import load_dotenv

        load_dotenv(os.path.join(BASE_DIR, ".env"), override=False)
    except ImportError:
        pass

IST = timezone(timedelta(hours=5, minutes=30))


def now_ist() -> datetime:
    """Business-local (India Standard Time) wall clock.

    Vercel runs in UTC; using IST keeps booking/collection dates identical to
    the locally hosted application.
    """
    return datetime.now(IST)


def init_db():
    with get_db() as conn:
        db.ensure_schema(conn)
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM settings WHERE id = 1")
        if cursor.fetchone()[0] == 0:
            cursor.execute("""
                INSERT INTO settings (
                    id, business_name, address, phone,
                    mutton_biriyani_price, chicken_65_price,
                    collection_date, collection_time, receipt_footer,
                    financial_start_date, financial_end_date
                ) VALUES (
                    1, 'SM MOIDEEN TRADERS', 'Tenkasi, Tamil Nadu', '9876543210',
                    2500.0, 350.0, '', '12:00',
                    '', '', ''
                )
            """)
        conn.commit()


# --- Validation helpers ---

INDIAN_MOBILE_RE = re.compile(r"^(?:\+91|91|0)?([6-9]\d{9})$")
PHONE_CLEAN_RE = re.compile(r"[\s\-().]")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
TIME_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


def normalize_phone(raw: Optional[str]) -> str:
    """Validate and normalise a customer phone number.

    Only Indian 10-digit mobile numbers starting with 6-9 are allowed.
    Returns the bare 10-digit number. Raises ValueError otherwise.
    """
    if raw is None:
        raise ValueError("Phone number is required")
    cleaned = PHONE_CLEAN_RE.sub("", str(raw).strip())
    if not cleaned:
        raise ValueError("Phone number is required")
    if not cleaned.startswith("+"):
        cleaned = cleaned.replace("+", "")
    if any(ch.isalpha() for ch in cleaned):
        raise ValueError("Phone number cannot contain letters")

    indian = INDIAN_MOBILE_RE.fullmatch(cleaned)
    if indian:
        return indian.group(1)

    raise ValueError(
        "Enter a valid 10-digit mobile number starting with 6, 7, 8 or 9 (e.g. 9876543210)."
    )


def parse_iso_date(value: Optional[str], label: str) -> Optional[date]:
    text = (value or "").strip()
    if not text:
        return None
    if not DATE_RE.fullmatch(text):
        raise ValueError(f"{label} must be a valid date in YYYY-MM-DD format")
    try:
        return datetime.strptime(text, "%Y-%m-%d").date()
    except ValueError:
        raise ValueError(f"{label} must be a valid calendar date")


def validate_time_value(value: Optional[str], label: str) -> str:
    text = (value or "").strip()
    if not text:
        return ""
    if not TIME_RE.fullmatch(text):
        raise ValueError(f"{label} must be a valid time in HH:MM (24 hour) format")
    return text


def parse_scan_payload(raw: Optional[str]) -> Tuple[Optional[str], Optional[int]]:
    """Return (compact_token, numeric_identifier) for a scanned SMM code.

    The established QR identifier is the fixed prefix ``S M M `` followed by a
    variable numeric identifier. Scanner noise (line breaks, leading/trailing
    spaces, repeated spaces) is normalised away. Returns (None, None) when the
    payload does not follow the format at all.
    """
    if raw is None:
        return None, None
    text = str(raw).replace("\r", " ").replace("\n", " ").replace("\t", " ")
    compact = re.sub(r"\s+", "", text).upper()
    match = re.fullmatch(r"SMM(\d{1,9})", compact)
    if not match:
        return None, None
    return compact, int(match.group(1))


def resolve_scan_code(conn: db.Connection, raw: Optional[str]) -> Dict[str, Any]:
    """Look up the booking referenced by a scanned SMM code.

    Raises HTTPException(400) for malformed codes and HTTPException(404) when no
    (or more than one) booking matches, so a wrong customer can never be served.
    """
    compact, identifier = parse_scan_payload(raw)
    if identifier is None:
        raise HTTPException(
            status_code=400,
            detail="Malformed QR code. Expected the format 'S M M <number>'.",
        )

    cursor = conn.cursor()
    cursor.execute(
        "SELECT id FROM bookings WHERE UPPER(token_number) = ?", (compact,)
    )
    row = cursor.fetchone()

    if not row:
        # The numeric identifier may be stored with or without zero padding
        # (e.g. scanned "S M M 1" maps to the stored token "SMM0001").
        padded = f"SMM{identifier:04d}"
        cursor.execute(
            "SELECT id FROM bookings WHERE UPPER(token_number) = ?", (padded.upper(),)
        )
        candidates = cursor.fetchall()
        if len(candidates) > 1:
            raise HTTPException(
                status_code=409,
                detail="This QR code matches more than one booking. Please contact the administrator.",
            )
        row = candidates[0] if candidates else None

    if not row:
        # Safeguard against zero-padding ambiguity: match by numeric value but
        # only for genuine SMM tokens, and refuse ambiguous matches.
        cursor.execute(
            "SELECT id FROM bookings WHERE UPPER(token_number) LIKE 'SMM%' "
            "AND CAST(SUBSTR(UPPER(token_number), 4) AS INTEGER) = ?",
            (identifier,),
        )
        candidates = cursor.fetchall()
        if len(candidates) > 1:
            raise HTTPException(
                status_code=409,
                detail="This QR code matches more than one booking. Please contact the administrator.",
            )
        row = candidates[0] if candidates else None

    if not row:
        raise HTTPException(
            status_code=404,
            detail=f"No booking matches the scanned code ({compact}).",
        )
    return get_booking_with_payments(conn, row["id"])


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup must never take the whole process down. A database problem is
    # reported per request as 503 (fail closed) instead of a blanket
    # "Application startup failed" crash that 500s every route, including the
    # static UI. Diagnostics are logged with secret values redacted.
    try:
        init_db()
    except Exception as exc:  # broad on purpose: never crash at startup
        logger.error(
            "Startup database initialisation failed (%s). The app will still "
            "start; database-backed routes will return 503 until the "
            "connection is fixed. Verify TURSO_DATABASE_URL, TURSO_AUTH_TOKEN "
            "and outbound network access.\n%s",
            type(exc).__name__,
            redact_secrets(traceback.format_exc()),
        )
    yield


app = FastAPI(title="SM MOIDEEN TRADERS API", lifespan=lifespan)

# The app is same-origin (API and UI on one deployment), so cross-origin
# access stays disabled unless the owner explicitly lists allowed origins in
# CORS_ALLOW_ORIGINS (comma separated). Wildcard origins are never used now
# that authentication relies on cookies.
_allowed_origins = [
    o.strip()
    for o in os.environ.get("CORS_ALLOW_ORIGINS", "").split(",")
    if o.strip()
]
if _allowed_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_allowed_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )


# --- Authentication ---------------------------------------------------------
#
# Server-side session guard. Everything that is not explicitly public requires
# a valid SuperAdmin session, so new endpoints are protected by default
# (fail closed). State-changing methods additionally require the session's
# CSRF token.

PUBLIC_PATHS = {
    "/",
    "/login",
    "/health",
    "/favicon.ico",
    "/api/auth/login",
    "/api/auth/session",
}
PUBLIC_PREFIXES = ("/static",)



@app.middleware("http")
async def require_session(request: Request, call_next):
    path = request.url.path
    try:
        if path in PUBLIC_PATHS or path.startswith(PUBLIC_PREFIXES):
            if path == "/" and auth.session_from_request(request) is None:
                return RedirectResponse(url="/login", status_code=302)
            return await call_next(request)

        session = auth.session_from_request(request)
        if session is None:
            if path.startswith("/api/"):
                return JSONResponse(
                    status_code=401, content={"detail": "Not authenticated"}
                )
            return RedirectResponse(url="/login", status_code=302)

        if request.method in ("POST", "PUT", "PATCH", "DELETE"):
            if not auth.csrf_matches(
                session, request.headers.get("x-csrf-token", "")
            ):
                return JSONResponse(
                    status_code=403, content={"detail": "CSRF validation failed"}
                )

        request.state.session = session
        return await call_next(request)
    except DatabaseConfigError:
        return JSONResponse(
            status_code=503,
            content={"detail": "Service is temporarily unavailable."},
        )


_REQUEST_ID_ALLOWED = re.compile(r"[^A-Za-z0-9._:-]")


def _request_id(request: Request) -> str:
    """Echo the caller's correlation id (sanitised) or mint a fresh one."""
    raw = (request.headers.get("x-request-id") or "").strip()[:64]
    cleaned = _REQUEST_ID_ALLOWED.sub("", raw)
    return cleaned or uuid.uuid4().hex[:16]


@app.middleware("http")
async def perf_timing(request: Request, call_next):
    """Attach a request id and a Server-Timing breakdown to every response.

    Defined after ``require_session`` so it wraps it: the reported totals cover
    authentication, the handler, the database round trips and JSON rendering.
    """
    request_id = _request_id(request)
    request.state.request_id = request_id
    stats = db.start_perf()
    started = time.perf_counter()
    response = None
    try:
        response = await call_next(request)
        return response
    finally:
        total_ms = (time.perf_counter() - started) * 1000.0
        db_ms = stats.db_seconds * 1000.0
        json_ms = stats.json_seconds * 1000.0
        handler_ms = max(0.0, total_ms - db_ms - json_ms)
        if response is not None:
            response.headers["x-request-id"] = request_id
            response.headers["Server-Timing"] = (
                f"total;dur={total_ms:.1f}, handler;dur={handler_ms:.1f}, "
                f"db;dur={db_ms:.1f}, json;dur={json_ms:.1f}, "
                f'db-queries;desc="{stats.statement_count}"'
            )
        if logger.isEnabledFor(_PERF_LOG_LEVEL):
            message = (
                "perf rid=%s %s %s status=%s total=%.1fms handler=%.1fms "
                "db=%.1fms json=%.1fms queries=%d"
            )
            args: List[Any] = [
                request_id,
                request.method,
                request.url.path,
                getattr(response, "status_code", 0),
                total_ms,
                handler_ms,
                db_ms,
                json_ms,
                stats.statement_count,
            ]
            if _PERF_VERBOSE:
                message += " stmts=[%s]"
                args.append(
                    ", ".join(
                        f"{descriptor}:{seconds * 1000.0:.0f}ms"
                        for descriptor, seconds in stats.statements
                    )
                )
            logger.log(_PERF_LOG_LEVEL, message, *args)


@app.exception_handler(DatabaseConfigError)
async def database_config_error_handler(request: Request, exc: DatabaseConfigError):
    # No credentials, paths or SQL are ever exposed.
    return JSONResponse(
        status_code=503, content={"detail": "Service is temporarily unavailable."}
    )


async def database_unavailable_handler(request: Request, exc: Exception):
    # A reachable-but-failing database (e.g. Turso outage or timeout) is a
    # temporary outage, not an application bug: fail closed with 503 and log
    # only the exception type (no URLs, tokens or SQL).
    logger.error("Database unavailable (%s); returning 503.", type(exc).__name__)
    return JSONResponse(
        status_code=503, content={"detail": "Service is temporarily unavailable."}
    )


for _db_error in DATABASE_ERRORS:
    app.add_exception_handler(_db_error, database_unavailable_handler)


@app.exception_handler(Exception)
async def unhandled_error_handler(request: Request, exc: Exception):
    # Full detail goes to the server logs only (secrets redacted), never to
    # the client.
    logger.error("Unhandled error:\n%s", redact_secrets(traceback.format_exc()))
    return JSONResponse(
        status_code=500, content={"detail": "Internal server error"}
    )


class LoginSchema(BaseModel):
    username: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=1, max_length=512)


def _session_from_state(request: Request) -> Optional[dict]:
    return getattr(request.state, "session", None) or auth.session_from_request(
        request
    )


@app.get("/login")
def serve_login(request: Request):
    if auth.session_from_request(request) is not None:
        return RedirectResponse(url="/", status_code=302)
    path = os.path.join(STATIC_DIR, "login.html")
    if os.path.exists(path):
        return FileResponse(path)
    return JSONResponse(status_code=404, content={"detail": "Login page missing"})


@app.get("/health")
def health():
    """Operational health check: no credentials, no business data."""
    return {"status": "ok"}


@app.get("/api/auth/session")
def auth_session(request: Request):
    session = auth.session_from_request(request)
    if not session:
        return {"authenticated": False, "csrf_token": None, "username": None}
    return {
        "authenticated": True,
        "csrf_token": session["csrf_token"],
        "username": session["username"],
    }


@app.post("/api/auth/login")
def login(data: LoginSchema, request: Request):
    if not auth.credentials_configured():
        raise HTTPException(
            status_code=503,
            detail="Sign-in is not configured yet. Set the admin environment "
                   "variables (see README).",
        )
    if not auth.origin_accepted(request):
        raise HTTPException(status_code=403, detail="Invalid request origin.")

    rate_key = auth.rate_limit_key(data.username, auth.client_address(request))
    if auth.rate_limited(rate_key):
        raise HTTPException(
            status_code=429,
            detail="Too many failed attempts. Please try again later.",
        )

    username_ok = auth.admin_username().casefold() == data.username.strip().casefold()
    password_ok = username_ok and auth.verify_password(
        data.password, os.environ.get("ADMIN_PASSWORD_HASH", "")
    )
    if not password_ok:
        auth.record_failure(rate_key)
        # Identical message for wrong username and wrong password.
        raise HTTPException(status_code=401, detail="Invalid username or password.")

    auth.clear_failures(rate_key)
    # Session fixation defence: drop any session this browser still holds.
    auth.invalidate_existing_session(request.cookies.get(auth.SESSION_COOKIE, ""))
    cookie_value, csrf_token = auth.create_session(auth.admin_username())
    response = JSONResponse(
        content={"ok": True, "csrf_token": csrf_token, "username": auth.admin_username()}
    )
    auth.set_login_cookie(response, cookie_value)
    return response


@app.post("/api/auth/logout")
def logout(request: Request):
    session = _session_from_state(request)
    if session:
        auth.delete_session(session["token_hash"])
    response = JSONResponse(content={"ok": True})
    auth.clear_login_cookie(response)
    return response


# --- Pydantic Schemas ---

class SettingsSchema(BaseModel):
    business_name: str
    address: Optional[str] = ""
    phone: Optional[str] = ""
    mutton_biriyani_price: float = Field(default=0.0, ge=0)
    chicken_65_price: float = Field(default=0.0, ge=0)
    collection_date: Optional[str] = ""
    collection_time: Optional[str] = ""
    receipt_footer: Optional[str] = ""
    financial_start_date: Optional[str] = ""
    financial_end_date: Optional[str] = ""

    @field_validator("collection_date", "financial_start_date", "financial_end_date")
    @classmethod
    def validate_dates(cls, v: Optional[str], info) -> str:
        label = {
            "collection_date": "Collection date",
            "financial_start_date": "Financial period start date",
            "financial_end_date": "Financial period end date",
        }.get(info.field_name, "Date")
        parse_iso_date(v, label)
        return (v or "").strip()

    @field_validator("collection_time")
    @classmethod
    def validate_collection_time(cls, v: Optional[str]) -> str:
        return validate_time_value(v, "Collection time")

    @model_validator(mode="after")
    def validate_financial_period(self) -> "SettingsSchema":
        start = parse_iso_date(self.financial_start_date, "Financial period start date")
        end = parse_iso_date(self.financial_end_date, "Financial period end date")
        if (start is None) != (end is None):
            raise ValueError("Provide both the financial period start date and end date.")
        if start and end and end < start:
            raise ValueError("Financial period end date cannot be earlier than the start date.")
        return self


class BaseBookingSchema(BaseModel):
    customer_name: str
    phone: str
    village: Optional[str] = ""
    # The collection date is fixed by Settings.collection_date. It is accepted
    # here only so existing/historical records can still be created with a date
    # when Settings has no default configured.
    function_date: Optional[str] = ""
    pickup_time: Optional[str] = ""
    mutton_qty: float = Field(default=0.0, ge=0)
    chicken_qty: float = Field(default=0.0, ge=0)
    notes: Optional[str] = ""

    @field_validator("function_date")
    @classmethod
    def validate_function_date(cls, v: Optional[str]) -> str:
        if not (v or "").strip():
            return ""
        parsed = parse_iso_date(v, "Collection date")
        if parsed is None:
            raise ValueError("Collection date is required")
        return parsed.strftime("%Y-%m-%d")

    @field_validator("mutton_qty", "chicken_qty")
    @classmethod
    def validate_quarter_step(cls, v: float) -> float:
        if v < 0:
            raise ValueError("Quantity cannot be negative")
        if round(v * 1000) % 250 != 0:
            raise ValueError("Quantity must be in increments of 0.25 (e.g., 0.25, 0.50, 0.75, 1.00, 1.25)")
        return v

    @field_validator("phone")
    @classmethod
    def validate_phone(cls, v: str) -> str:
        # Only Indian 10-digit mobile numbers (6-9 + 9 digits) are allowed.
        return normalize_phone(v)

    @field_validator("pickup_time")
    @classmethod
    def validate_pickup_time(cls, v: Optional[str]) -> str:
        return validate_time_value(v, "Collection time")

    @field_validator("customer_name")
    @classmethod
    def validate_customer_name(cls, v: str) -> str:
        if not (v or "").strip():
            raise ValueError("Customer name is required")
        return v.strip()


class CreateBookingSchema(BaseBookingSchema):
    advance_paid: float = Field(default=0.0, ge=0)


class UpdateBookingSchema(BaseBookingSchema):
    pass


class CollectBookingSchema(BaseModel):
    amount_received: float = Field(default=0.0, ge=0)
    request_id: Optional[str] = None


class AddPaymentSchema(BaseModel):
    amount: float = Field(gt=0)
    notes: Optional[str] = ""
    request_id: Optional[str] = None


# --- Helper Functions ---

def row_to_dict(row: db.Row) -> Dict[str, Any]:
    return dict(row)


def get_booking_with_payments(conn: db.Connection, booking_id: int) -> Optional[Dict[str, Any]]:
    booking_rows, payment_rows = db.run_batch(conn, [
        ("SELECT * FROM bookings WHERE id = ?", (booking_id,)),
        ("SELECT * FROM payments WHERE booking_id = ? ORDER BY id ASC", (booking_id,)),
    ])
    if not booking_rows:
        return None
    booking = row_to_dict(booking_rows[0])
    booking["payments"] = [row_to_dict(p) for p in payment_rows]
    return booking


def generate_next_token(conn: db.Connection) -> str:
    cursor = conn.cursor()
    # Compute max numeric from clean SMM tokens in SQL to avoid transferring
    # every token row; fall back to a targeted scan only when needed.
    cursor.execute(
        """
        SELECT COALESCE(
            MAX(CAST(SUBSTR(UPPER(TRIM(token_number)), 4) AS INTEGER)),
            0
        )
        FROM bookings
        WHERE UPPER(TRIM(token_number)) LIKE 'SMM%'
          AND LENGTH(SUBSTR(UPPER(TRIM(token_number)), 4)) > 0
          AND SUBSTR(UPPER(TRIM(token_number)), 4) NOT GLOB '*[^0-9]*'
        """
    )
    row = cursor.fetchone()
    highest = int(row[0]) if row and row[0] is not None else 0

    # Find non-SMM tokens that might contain higher digit sequences (rare).
    cursor.execute(
        """
        SELECT token_number
        FROM bookings
        WHERE NOT (
            UPPER(TRIM(token_number)) LIKE 'SMM%'
            AND LENGTH(SUBSTR(UPPER(TRIM(token_number)), 4)) > 0
            AND SUBSTR(UPPER(TRIM(token_number)), 4) NOT GLOB '*[^0-9]*'
        )
        """
    )
    for r in cursor.fetchall():
        val = str(r[0]).strip()
        if val.upper().startswith("SMM"):
            nums = val[3:]
        else:
            nums = "".join(ch for ch in val if ch.isdigit())
        if nums and nums.isdigit():
            candidate = int(nums)
            if candidate > highest:
                highest = candidate
    next_num = highest + 1
    return f"SMM{next_num:04d}"


# --- API Endpoints ---

@app.get("/api/settings")
def get_settings():
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM settings WHERE id = 1")
        row = cursor.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Settings not found")
        return row_to_dict(row)


@app.put("/api/settings")
def update_settings(data: SettingsSchema):
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE settings SET
                business_name = ?,
                address = ?,
                phone = ?,
                mutton_biriyani_price = ?,
                chicken_65_price = ?,
                collection_date = ?,
                collection_time = ?,
                receipt_footer = ?,
                financial_start_date = ?,
                financial_end_date = ?
            WHERE id = 1
        """, (
            data.business_name,
            data.address or "",
            data.phone or "",
            data.mutton_biriyani_price,
            data.chicken_65_price,
            data.collection_date or "",
            data.collection_time or "",
            data.receipt_footer or "",
            data.financial_start_date or "",
            data.financial_end_date or ""
        ))
        conn.commit()
        cursor.execute("SELECT * FROM settings WHERE id = 1")
        return row_to_dict(cursor.fetchone())


@app.get("/api/bookings")
def list_bookings(
    search: Optional[str] = None,
    limit: Optional[int] = None,
    order_by: Optional[str] = None,
    status: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    balance_due: Optional[bool] = None,
):
    with get_db() as conn:
        cursor = conn.cursor()
        conditions: List[str] = []
        params: List[Any] = []

        if search:
            q = f"%{search.strip()}%"
            conditions.append(
                "(token_number LIKE ? OR customer_name LIKE ? OR phone LIKE ? OR village LIKE ?)"
            )
            params.extend([q, q, q, q])

        if status:
            conditions.append("status = ?")
            params.append(status)

        if balance_due:
            conditions.append("balance > 0.001")

        if start_date:
            conditions.append("function_date >= ?")
            params.append(start_date)

        if end_date:
            conditions.append("function_date <= ?")
            params.append(end_date)

        where_clause = ""
        if conditions:
            where_clause = "WHERE " + " AND ".join(conditions)

        # Ordering
        valid_orders = {
            "function_date ASC": "function_date ASC, token_number ASC",
            "function_date DESC": "function_date DESC, token_number ASC",
            "customer_name ASC": "customer_name ASC, token_number ASC",
            "customer_name DESC": "customer_name DESC, token_number ASC",
            "token_number ASC": "token_number ASC, id ASC",
            "token_number DESC": "token_number DESC, id DESC",
        }
        order_clause = "ORDER BY " + valid_orders.get(order_by or "", "token_number ASC, id ASC")

        limit_clause = ""
        if limit and limit > 0:
            limit_clause = "LIMIT ?"
            params.append(limit)

        sql = f"SELECT * FROM bookings {where_clause} {order_clause} {limit_clause}"
        cursor.execute(sql, params)
        bookings = [row_to_dict(r) for r in cursor.fetchall()]

        # Attach payments to each booking in a single query instead of one
        # round trip per booking (N+1). Ordering inside each booking stays
        # payment-id ascending, exactly as the per-booking query did.
        for b in bookings:
            b["payments"] = []
        if bookings:
            ids = [b["id"] for b in bookings]
            placeholders = ",".join("?" for _ in ids)
            cursor.execute(
                f"SELECT * FROM payments WHERE booking_id IN ({placeholders})"
                " ORDER BY booking_id ASC, id ASC",
                ids,
            )
            grouped: Dict[int, List[Dict[str, Any]]] = {b["id"]: b["payments"] for b in bookings}
            for p in cursor.fetchall():
                payment = row_to_dict(p)
                grouped.get(payment["booking_id"], []).append(payment)

        return bookings


@app.get("/api/bookings/{booking_id}")
def get_booking(booking_id: int):
    with get_db() as conn:
        booking = get_booking_with_payments(conn, booking_id)
        if not booking:
            raise HTTPException(status_code=404, detail="Booking not found")
        return booking


@app.get("/api/bookings/by-token/{token}")
def get_booking_by_token(token: str):
    with get_db() as conn:
        raw = (token or "").strip()
        # Manual keypad entry may be just the numeric identifier (e.g. "123").
        if raw.isdigit():
            raw = f"SMM{raw}"
        return resolve_scan_code(conn, raw)


@app.get("/api/scan")
def scan_booking(code: str = Query(..., description="Scanned QR/barcode payload")):
    """Resolve a scanned SMM QR/barcode to its booking without recording anything."""
    with get_db() as conn:
        return resolve_scan_code(conn, code)


@app.post("/api/bookings", status_code=status.HTTP_201_CREATED)
def create_booking(data: CreateBookingSchema):
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM settings WHERE id = 1")
        settings = cursor.fetchone()
        mutton_price = float(settings["mutton_biriyani_price"]) if settings else 0.0
        chicken_price = float(settings["chicken_65_price"]) if settings else 0.0
        # Collection date is fixed by Settings. It is only overridden when the
        # Settings default is not configured (e.g. historical/seed data imports).
        fixed_func_date = (settings["collection_date"] or "").strip() if settings else ""
        func_date = fixed_func_date or data.function_date
        if not func_date:
            raise HTTPException(
                status_code=400,
                detail="Set the default collection date in Settings before creating bookings.",
            )

        fixed_func_time = (settings["collection_time"] or "").strip() if settings else ""
        func_time = fixed_func_time or (data.pickup_time or "").strip()

        grand_total = round(data.mutton_qty * mutton_price + data.chicken_qty * chicken_price, 2)
        advance_paid = round(min(data.advance_paid, grand_total), 2)
        balance = round(max(0.0, grand_total - advance_paid), 2)
        booking_date = now_ist().strftime("%Y-%m-%d")

        # Serverless invocations can race for the same next token; the UNIQUE
        # index keeps data safe and we retry with the following number.
        insert_sql = """
            INSERT INTO bookings (
                token_number, customer_name, phone, village,
                booking_date, function_date, pickup_time,
                mutton_qty, mutton_price_per_kg,
                chicken_qty, chicken_price_per_kg,
                grand_total, advance_paid, balance,
                status, notes
            ) VALUES (
                ?, ?, ?, ?,
                ?, ?, ?,
                ?, ?,
                ?, ?,
                ?, ?, ?,
                'pending', ?
            )
        """
        for _attempt in range(5):
            token_number = generate_next_token(conn)
            try:
                cursor.execute(insert_sql, (
                    token_number,
                    data.customer_name.strip(),
                    data.phone.strip(),
                    data.village.strip() if data.village else "",
                    booking_date,
                    func_date,
                    func_time,
                    data.mutton_qty,
                    mutton_price,
                    data.chicken_qty,
                    chicken_price,
                    grand_total,
                    advance_paid,
                    balance,
                    data.notes.strip() if data.notes else ""
                ))
                break
            except db.INTEGRITY_ERRORS:
                clash = conn.execute(
                    "SELECT id FROM bookings WHERE token_number = ?", (token_number,)
                ).fetchone()
                if not clash:
                    raise
                conn.rollback()
        else:
            raise HTTPException(
                status_code=409,
                detail="Could not allocate a token number. Please try again.",
            )
        booking_id = cursor.lastrowid

        if advance_paid > 0:
            cursor.execute("""
                INSERT INTO payments (booking_id, amount, payment_date, notes)
                VALUES (?, ?, ?, 'Advance Payment')
            """, (booking_id, advance_paid, booking_date))

        conn.commit()
        return get_booking_with_payments(conn, booking_id)


@app.put("/api/bookings/{booking_id}")
def update_booking(booking_id: int, data: UpdateBookingSchema):
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM bookings WHERE id = ?", (booking_id,))
        existing = cursor.fetchone()
        if not existing:
            raise HTTPException(status_code=404, detail="Booking not found")

        mutton_price = float(existing["mutton_price_per_kg"])
        chicken_price = float(existing["chicken_price_per_kg"])
        advance_paid = float(existing["advance_paid"])

        grand_total = round(data.mutton_qty * mutton_price + data.chicken_qty * chicken_price, 2)
        balance = round(max(0.0, grand_total - advance_paid), 2)

        cursor.execute("""
            UPDATE bookings SET
                customer_name = ?,
                phone = ?,
                village = ?,
                mutton_qty = ?,
                chicken_qty = ?,
                grand_total = ?,
                balance = ?,
                notes = ?
            WHERE id = ?
        """, (
            data.customer_name.strip(),
            data.phone.strip(),
            data.village.strip() if data.village else "",
            data.mutton_qty,
            data.chicken_qty,
            grand_total,
            balance,
            data.notes.strip() if data.notes else "",
            booking_id
        ))
        conn.commit()
        return get_booking_with_payments(conn, booking_id)


@app.post("/api/bookings/{booking_id}/collect")
def collect_booking(booking_id: int, data: CollectBookingSchema):
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM bookings WHERE id = ?", (booking_id,))
        existing = cursor.fetchone()
        if not existing:
            raise HTTPException(status_code=404, detail="Booking not found")

        today = now_ist().strftime("%Y-%m-%d")
        grand_total = float(existing["grand_total"])
        old_advance = float(existing["advance_paid"])
        old_balance = float(existing["balance"])

        amount_to_receive = min(data.amount_received, old_balance)
        new_advance = round(old_advance + amount_to_receive, 2)
        new_balance = round(max(0.0, grand_total - new_advance), 2)

        if amount_to_receive > 0:
            try:
                cursor.execute("""
                    INSERT INTO payments (booking_id, amount, payment_date, notes, request_id)
                    VALUES (?, ?, ?, 'Collection Payment', ?)
                """, (booking_id, amount_to_receive, today, data.request_id))
            except db.INTEGRITY_ERRORS:
                # A repeated scan/click using the same request id must never
                # record a duplicate payment.
                conn.rollback()
                return get_booking_with_payments(conn, booking_id)

        cursor.execute("""
            UPDATE bookings SET
                status = 'collected',
                advance_paid = ?,
                balance = ?
            WHERE id = ?
        """, (new_advance, new_balance, booking_id))

        conn.commit()
        return get_booking_with_payments(conn, booking_id)


@app.post("/api/bookings/{booking_id}/payment")
def add_payment(booking_id: int, data: AddPaymentSchema):
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM bookings WHERE id = ?", (booking_id,))
        existing = cursor.fetchone()
        if not existing:
            raise HTTPException(status_code=404, detail="Booking not found")

        today = now_ist().strftime("%Y-%m-%d")
        grand_total = float(existing["grand_total"])
        old_advance = float(existing["advance_paid"])
        old_balance = float(existing["balance"])

        if data.amount > old_balance:
            raise HTTPException(
                status_code=400,
                detail=f"Amount exceeds outstanding balance of ₹{old_balance:.2f}"
            )

        new_advance = round(old_advance + data.amount, 2)
        new_balance = round(max(0.0, grand_total - new_advance), 2)

        try:
            cursor.execute("""
                INSERT INTO payments (booking_id, amount, payment_date, notes, request_id)
                VALUES (?, ?, ?, ?, ?)
            """, (booking_id, data.amount, today, data.notes or "Payment", data.request_id))
        except db.INTEGRITY_ERRORS:
            conn.rollback()
            return get_booking_with_payments(conn, booking_id)

        cursor.execute("""
            UPDATE bookings SET
                advance_paid = ?,
                balance = ?
            WHERE id = ?
        """, (new_advance, new_balance, booking_id))

        conn.commit()
        return get_booking_with_payments(conn, booking_id)


# --- Reports ---

def calculate_report_data(conn: db.Connection, start_date: str, end_date: str) -> Dict[str, Any]:
    cursor = conn.cursor()
    cursor.execute("""
        SELECT
            COUNT(*) AS total_bookings,
            COALESCE(SUM(grand_total), 0) AS total_revenue,
            COALESCE(SUM(advance_paid), 0) AS total_advance,
            COALESCE(SUM(balance), 0) AS pending_balance,
            COALESCE(SUM(mutton_qty), 0) AS total_mutton_qty,
            COALESCE(SUM(chicken_qty), 0) AS total_chicken_qty
        FROM bookings
        WHERE function_date >= ? AND function_date <= ?
    """, (start_date, end_date))
    row = cursor.fetchone()
    return {
        "total_bookings": int(row["total_bookings"]),
        "total_revenue": float(row["total_revenue"]),
        "total_advance": float(row["total_advance"]),
        "pending_balance": float(row["pending_balance"]),
        "total_mutton_qty": float(row["total_mutton_qty"]),
        "total_chicken_qty": float(row["total_chicken_qty"]),
    }


@app.get("/api/reports/daily")
def daily_report():
    today = now_ist().strftime("%Y-%m-%d")
    with get_db() as conn:
        return calculate_report_data(conn, today, today)


@app.get("/api/reports/weekly")
def weekly_report():
    today = now_ist().date()
    start_of_week = (today - timedelta(days=today.weekday())).strftime("%Y-%m-%d")
    end_of_week = (today + timedelta(days=6 - today.weekday())).strftime("%Y-%m-%d")
    with get_db() as conn:
        return calculate_report_data(conn, start_of_week, end_of_week)


@app.get("/api/reports/monthly")
def monthly_report(year: int = Query(...), month: int = Query(...)):
    _, last_day = calendar.monthrange(year, month)
    start_date = f"{year:04d}-{month:02d}-01"
    end_date = f"{year:04d}-{month:02d}-{last_day:02d}"
    with get_db() as conn:
        return calculate_report_data(conn, start_date, end_date)


@app.get("/api/reports/custom")
def custom_report(start_date: str = Query(...), end_date: str = Query(...)):
    with get_db() as conn:
        return calculate_report_data(conn, start_date, end_date)


REPORT_ORDERS = {
    "function_date ASC": "function_date ASC, token_number ASC",
    "function_date DESC": "function_date DESC, token_number ASC",
    "customer_name ASC": "customer_name ASC, token_number ASC",
    "customer_name DESC": "customer_name DESC, token_number ASC",
    "token_number ASC": "token_number ASC, id ASC",
    "token_number DESC": "token_number DESC, id DESC",
}


def _report_filters(start: str, end: str, search: Optional[str]):
    conditions = ["function_date >= ? AND function_date <= ?"]
    params: List[Any] = [start, end]
    if search and search.strip():
        q = f"%{search.strip()}%"
        conditions.append("(token_number LIKE ? OR customer_name LIKE ? OR phone LIKE ? OR village LIKE ?)")
        params.extend([q, q, q, q])
    return " AND ".join(conditions), params


def _report_bookings_spec(
    start: str,
    end: str,
    order_by: Optional[str],
    search: Optional[str],
) -> Tuple[str, List[Any]]:
    where_clause, params = _report_filters(start, end, search)
    order_clause = "ORDER BY " + REPORT_ORDERS.get(order_by or "", "token_number ASC, id ASC")
    return f"SELECT * FROM bookings WHERE {where_clause} {order_clause}", params


def query_report_bookings(
    conn: db.Connection,
    start: str,
    end: str,
    order_by: Optional[str],
    search: Optional[str],
) -> List[Dict[str, Any]]:
    sql, params = _report_bookings_spec(start, end, order_by, search)
    cursor = conn.cursor()
    cursor.execute(sql, params)
    return [row_to_dict(r) for r in cursor.fetchall()]


def _opening_balance_spec(start: str, search: Optional[str]) -> Tuple[str, List[Any]]:
    """Outstanding balance brought forward from records before the period."""
    conditions = ["function_date < ?"]
    params: List[Any] = [start]
    if search and search.strip():
        q = f"%{search.strip()}%"
        conditions.append("(token_number LIKE ? OR customer_name LIKE ? OR phone LIKE ? OR village LIKE ?)")
        params.extend([q, q, q, q])
    sql = f"SELECT COALESCE(SUM(balance), 0) AS bal FROM bookings WHERE {' AND '.join(conditions)}"
    return sql, params


def opening_balance(conn: db.Connection, start: str, search: Optional[str]) -> float:
    sql, params = _opening_balance_spec(start, search)
    cursor = conn.cursor()
    cursor.execute(sql, params)
    return round(float(cursor.fetchone()["bal"]), 2)


@app.get("/api/reports/pdf")
def report_pdf(
    start_date: str = Query(...),
    end_date: str = Query(...),
    order_by: Optional[str] = None,
    search: Optional[str] = None,
    label: Optional[str] = None,
):
    try:
        start = parse_iso_date(start_date, "Start date")
        end = parse_iso_date(end_date, "End date")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    if start is None or end is None:
        raise HTTPException(status_code=400, detail="start_date and end_date are required")
    if end < start:
        raise HTTPException(status_code=400, detail="End date cannot be earlier than the start date")

    start_s = start.strftime("%Y-%m-%d")
    end_s = end.strftime("%Y-%m-%d")

    bookings_sql, bookings_params = _report_bookings_spec(start_s, end_s, order_by, search)
    opening_sql, opening_params = _opening_balance_spec(start_s, search)

    # Three independent reads: one combined round trip instead of three.
    with get_db() as conn:
        settings_rows, booking_rows, opening_rows = db.run_batch(conn, [
            ("SELECT * FROM settings WHERE id = 1", None),
            (bookings_sql, bookings_params),
            (opening_sql, opening_params),
        ])

    settings = row_to_dict(settings_rows[0]) if settings_rows else {}
    bookings = [row_to_dict(r) for r in booking_rows]
    opening = round(float(opening_rows[0]["bal"]), 2)

    totals = {
        "count": len(bookings),
        "total": round(sum(float(b["grand_total"]) for b in bookings), 2),
        "paid": round(sum(float(b["advance_paid"]) for b in bookings), 2),
        "balance": round(sum(float(b["balance"]) for b in bookings), 2),
        "mutton": round(sum(float(b["mutton_qty"]) for b in bookings), 2),
        "chicken": round(sum(float(b["chicken_qty"]) for b in bookings), 2),
    }

    pdf_bytes = build_report_pdf(
        settings=settings,
        title=(label or "Collection Report").strip() or "Collection Report",
        start_date=start_s,
        end_date=end_s,
        bookings=bookings,
        opening_balance=opening,
        totals=totals,
        generated_at=now_ist().strftime("%d-%m-%Y %I:%M %p"),
        search=search,
    )
    filename = f"collection_report_{start_s}_to_{end_s}.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{filename}"'},
    )


# --- Static and Root Endpoints ---

if os.path.exists(STATIC_DIR):
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/")
def serve_index():
    index_path = os.path.join(STATIC_DIR, "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    return {"message": "SM MOIDEEN TRADERS API is running"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)
