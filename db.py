"""Centralised database access for SMMTRADERS.

Local development uses the SQLite file. Production (Vercel) connects to a
remote Turso database through the official ``turso_serverless`` HTTP driver.
Every query in the application goes through :func:`get_db`, which returns a
DB-API style connection wrapper that behaves identically for both backends:

* rows support ``row["column"]``, ``row[0]`` and ``dict(row)`` access,
* ``with get_db() as conn:`` commits on success and rolls back on error,
* :data:`INTEGRITY_ERRORS` catches unique-constraint violations from either
  backend with a single ``except`` clause.

Turso credentials are only ever read from server-side environment variables.
"""

import contextvars
import os
import sqlite3
import time
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SQLITE_PATH = os.environ.get(
    "SMM_TRADERS_DB", os.path.join(BASE_DIR, "smm_traders.db")
)

try:
    import turso_serverless as _turso
except ImportError:  # pragma: no cover - optional until Turso is configured
    _turso = None


class DatabaseConfigError(RuntimeError):
    """Raised when the database is missing or misconfigured (fail closed)."""


def turso_url() -> Optional[str]:
    return os.environ.get("TURSO_DATABASE_URL") or None


def turso_token() -> Optional[str]:
    return os.environ.get("TURSO_AUTH_TOKEN") or None


def on_vercel() -> bool:
    return os.environ.get("VERCEL") == "1"


def turso_ready() -> bool:
    return bool(turso_url() and turso_token())


def _integrity_errors() -> tuple:
    errs = (sqlite3.IntegrityError,)
    if _turso is not None:
        errs = errs + (_turso.IntegrityError,)
    return errs


INTEGRITY_ERRORS = _integrity_errors()


def _database_error_types() -> tuple:
    """Errors that mean "the database is unreachable/unavailable" (503).

    ``OperationalError``/``InterfaceError`` cover connection and protocol
    failures for both backends. ``IntegrityError`` is deliberately excluded so
    unique-constraint handling keeps its own 409 semantics.
    """
    errs = (sqlite3.OperationalError, sqlite3.InterfaceError)
    if _turso is not None:
        errs = errs + (_turso.OperationalError, _turso.InterfaceError)
    return errs


DATABASE_ERRORS = _database_error_types()


# --- Request-scoped performance accounting ----------------------------------
#
# Each HTTP request may start a PerfStats collector. Statement timings are
# recorded here so the API can expose (and optionally log) where the time goes.
# Only a SQL descriptor - the leading keyword and the first table name - is
# ever stored; parameters, values and customer data are never captured.

class PerfStats:
    """Per-request counters: statement count, database and JSON render time."""

    __slots__ = ("statements", "db_seconds", "json_seconds")

    def __init__(self) -> None:
        self.statements: List[Tuple[str, float]] = []
        self.db_seconds = 0.0
        self.json_seconds = 0.0

    @property
    def statement_count(self) -> int:
        return len(self.statements)

    def record(self, descriptor: str, seconds: float) -> None:
        self.statements.append((descriptor, seconds))
        self.db_seconds += seconds


_perf_stats: "contextvars.ContextVar[Optional[PerfStats]]" = contextvars.ContextVar(
    "smm_perf_stats", default=None
)

_SQL_KEYWORDS = ("FROM", "INTO", "UPDATE", "TABLE", "JOIN")
_SQL_SKIP_WORDS = {"IF", "NOT", "EXISTS", "OR", "REPLACE", "TEMPORARY"}


def describe_sql(sql: Any) -> str:
    """Return "<keyword> <first table>" for a statement, never its values."""
    words = str(sql).split()
    if not words:
        return "?"
    keyword = words[0].upper()
    target = ""
    for index, word in enumerate(words):
        if word.upper() in _SQL_KEYWORDS:
            nxt = index + 1
            while nxt < len(words) and words[nxt].upper() in _SQL_SKIP_WORDS:
                nxt += 1
            if nxt < len(words):
                target = words[nxt].strip("();,")
            break
    return f"{keyword} {target}".strip()


def start_perf() -> PerfStats:
    """Begin collecting statement timings for the current request context."""
    stats = PerfStats()
    _perf_stats.set(stats)
    return stats


def current_perf() -> Optional[PerfStats]:
    """The active collector for the current request context, if any."""
    return _perf_stats.get()


def _record(descriptor: str, seconds: float) -> None:
    stats = _perf_stats.get()
    if stats is not None:
        stats.record(descriptor, seconds)


# --- Batched read-only statements -------------------------------------------
#
# Turso speaks SQL over HTTP: one round trip per statement by default. Several
# independent reads can share a single `/v3/pipeline` request, which cuts
# latency roughly in proportion to the statement count. Batching is only ever
# attempted for read-only statements, and any failure falls back to the normal
# (already proven) per-statement path, so results never change.

_READ_ONLY_PREFIXES = ("SELECT", "PRAGMA", "WITH", "EXPLAIN", "VALUES")


def _is_read_only(sql: Any) -> bool:
    words = str(sql).split(maxsplit=1)
    return bool(words) and words[0].upper() in _READ_ONLY_PREFIXES


def _turso_batch(conn: "Connection", statements: List[Tuple[str, Any]]) -> List[List["Row"]]:
    """Run read-only statements through one Turso pipeline request."""
    from turso_serverless.protocol import build_batch_step, decode_value

    session = getattr(conn._inner, "_session", None)
    if session is None or not hasattr(session, "execute_pipeline"):
        raise RuntimeError("Turso session does not support pipelines")

    requests = []
    for sql, params in statements:
        args = list(params) if params else None
        step = build_batch_step(sql, args=args, want_rows=True)
        requests.append({"type": "execute", "stmt": step["stmt"]})

    results = session.execute_pipeline(requests)
    if len(results) != len(statements):
        raise RuntimeError("pipeline returned an unexpected result count")

    batched: List[List["Row"]] = []
    for result in results:
        response = result.get("response") or {}
        if result.get("type") != "ok" or response.get("type") != "execute":
            # Fall back to per-statement execution so a server-side error
            # surfaces through the normal driver error mapping.
            raise RuntimeError("pipeline statement failed")
        payload = response.get("result") or {}
        keys = [column.get("name") or "" for column in payload.get("cols") or []]
        rows = [
            Row(keys, [decode_value(value) for value in row])
            for row in payload.get("rows") or []
        ]
        batched.append(rows)
    return batched


def run_batch(conn: "Connection", statements: List[Tuple[str, Any]]) -> List[List["Row"]]:
    """Execute read-only ``(sql, params)`` pairs and return one row list each.

    On Turso the statements travel in a single HTTP round trip; on SQLite (or
    if anything about the batched path is unsupported) they run sequentially.
    Batched execution is attempted only when every statement is read-only, so
    callers can never observe a different result or a different side effect.
    """
    if len(statements) > 1 and all(_is_read_only(sql) for sql, _ in statements):
        t0 = time.perf_counter()
        try:
            rows = _turso_batch(conn, statements) if conn.backend == "turso" else None
            if rows is not None:
                elapsed = time.perf_counter() - t0
                _record(
                    "BATCH[{0}] {1}".format(
                        len(statements),
                        ",".join(describe_sql(sql).split()[0] for sql, _ in statements),
                    ),
                    elapsed,
                )
                return rows
        except Exception:
            # Proven per-statement path below; batching must never break a read.
            pass
    return [conn.execute(sql, params).fetchall() for sql, params in statements]


class Row:
    """Minimal sqlite3.Row-compatible row (key and index access)."""

    __slots__ = ("_keys", "_values")

    def __init__(self, keys: Sequence[str], values: Sequence[Any]):
        self._keys = list(keys)
        self._values = list(values)

    def __getitem__(self, key):
        if isinstance(key, int):
            return self._values[key]
        try:
            return self._values[self._keys.index(key)]
        except ValueError:
            raise IndexError(key) from None

    def __iter__(self):
        return iter(self._values)

    def __len__(self):
        return len(self._values)

    def __contains__(self, key):
        return key in self._keys if isinstance(key, str) else key in range(
            -len(self._values), len(self._values)
        )

    def keys(self) -> List[str]:
        return list(self._keys)

    def __repr__(self):
        return f"<Row {dict(zip(self._keys, self._values))!r}>"


def _to_values(row: Any, keys: List[str]) -> List[Any]:
    if isinstance(row, (tuple, list)):
        return list(row)
    try:
        return [row[k] for k in keys]
    except Exception:
        return list(tuple(row))


class _Cursor:
    def __init__(self, cursor: Any, backend: str):
        self._cur = cursor
        self._backend = backend
        self._keys: List[str] = []

    @property
    def description(self):
        return self._cur.description

    @property
    def lastrowid(self):
        return self._cur.lastrowid

    @property
    def rowcount(self):
        return self._cur.rowcount

    def _refresh_keys(self):
        desc = getattr(self._cur, "description", None)
        self._keys = [d[0] for d in desc] if desc else []

    def _wrap(self, row):
        if row is None:
            return None
        return Row(self._keys, _to_values(row, self._keys))

    def execute(self, sql: str, params: Any = None):
        started = time.perf_counter()
        try:
            if params is None:
                self._cur.execute(sql)
            else:
                self._cur.execute(sql, params)
        finally:
            _record(describe_sql(sql), time.perf_counter() - started)
        self._refresh_keys()
        return self

    def executemany(self, sql: str, seq_of_params: Iterable):
        started = time.perf_counter()
        try:
            self._cur.executemany(sql, seq_of_params)
        finally:
            _record(describe_sql(sql) + " [many]", time.perf_counter() - started)
        self._refresh_keys()
        return self

    def fetchone(self):
        return self._wrap(self._cur.fetchone())

    def fetchall(self):
        return [self._wrap(r) for r in self._cur.fetchall()]

    def fetchmany(self, size: int):
        return [self._wrap(r) for r in self._cur.fetchmany(size)]

    def close(self):
        self._cur.close()

    def __iter__(self):
        return iter(self.fetchall())


class Connection:
    """Thin DB-API connection wrapper shared by SQLite and Turso."""

    def __init__(self, inner: Any, backend: str):
        self._inner = inner
        self.backend = backend  # "sqlite" or "turso"

    def cursor(self) -> _Cursor:
        return _Cursor(self._inner.cursor(), self.backend)

    def execute(self, sql: str, params: Any = None) -> _Cursor:
        return self.cursor().execute(sql, params)

    def executemany(self, sql: str, seq_of_params: Iterable) -> _Cursor:
        return self.cursor().executemany(sql, seq_of_params)

    def commit(self):
        self._inner.commit()

    def rollback(self):
        self._inner.rollback()

    def close(self):
        self._inner.close()

    def __enter__(self) -> "Connection":
        return self

    def __exit__(self, exc_type, exc, tb):
        if exc_type is None:
            self.commit()
        else:
            self.rollback()
        return False

    def ensure_column(self, table: str, column: str, ddl: str) -> None:
        """Add a column when missing; tolerant of engines without PRAGMA."""
        columns = None
        try:
            rows = self.execute(f"PRAGMA table_info({table})").fetchall()
            columns = {row[1] for row in rows}
        except Exception:
            columns = None
        if columns is not None:
            if column in columns:
                return
            self.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")
            return
        # PRAGMA unavailable: attempt the ALTER and ignore "duplicate column".
        try:
            self.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")
        except Exception as exc:
            if "duplicate" not in str(exc).lower():
                raise


def connect_sqlite(path: Optional[str] = None) -> Connection:
    target = path if path is not None else SQLITE_PATH
    raw = sqlite3.connect(target)
    raw.execute("PRAGMA foreign_keys = ON")
    return Connection(raw, "sqlite")


def connect_turso(url: Optional[str] = None, token: Optional[str] = None) -> Connection:
    resolved_url = url if url is not None else turso_url()
    resolved_token = token if token is not None else turso_token()
    if not resolved_url or not resolved_token:
        raise DatabaseConfigError(
            "TURSO_DATABASE_URL and TURSO_AUTH_TOKEN must both be set."
        )
    if _turso is None:
        raise DatabaseConfigError(
            "The turso_serverless package is not installed (requirements.txt)."
        )
    raw = _turso.connect(resolved_url, auth_token=resolved_token)
    return Connection(raw, "turso")


def get_db() -> Connection:
    """Open a connection using Turso in production, SQLite locally."""
    url = turso_url()
    if url:
        return connect_turso()
    if on_vercel():
        raise DatabaseConfigError(
            "TURSO_DATABASE_URL is not configured; refusing to expose data."
        )
    return connect_sqlite()


# --- Schema -----------------------------------------------------------------

SCHEMA_STATEMENTS: List[tuple] = [
    (
        "CREATE TABLE IF NOT EXISTS settings ("
        " id INTEGER PRIMARY KEY CHECK (id = 1),"
        " business_name TEXT NOT NULL,"
        " address TEXT,"
        " phone TEXT,"
        " mutton_biriyani_price REAL NOT NULL DEFAULT 2500.0,"
        " chicken_65_price REAL NOT NULL DEFAULT 350.0,"
        " collection_date TEXT,"
        " collection_time TEXT,"
        " receipt_footer TEXT,"
        " financial_start_date TEXT,"
        " financial_end_date TEXT)"
    ),
    (
        "CREATE TABLE IF NOT EXISTS bookings ("
        " id INTEGER PRIMARY KEY AUTOINCREMENT,"
        " token_number TEXT UNIQUE NOT NULL,"
        " customer_name TEXT NOT NULL,"
        " phone TEXT NOT NULL,"
        " village TEXT,"
        " booking_date TEXT NOT NULL,"
        " function_date TEXT NOT NULL,"
        " pickup_time TEXT,"
        " mutton_qty REAL NOT NULL DEFAULT 0.0,"
        " mutton_price_per_kg REAL NOT NULL DEFAULT 0.0,"
        " chicken_qty REAL NOT NULL DEFAULT 0.0,"
        " chicken_price_per_kg REAL NOT NULL DEFAULT 0.0,"
        " grand_total REAL NOT NULL DEFAULT 0.0,"
        " advance_paid REAL NOT NULL DEFAULT 0.0,"
        " balance REAL NOT NULL DEFAULT 0.0,"
        " status TEXT NOT NULL DEFAULT 'pending',"
        " notes TEXT,"
        " created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"
    ),
    (
        "CREATE TABLE IF NOT EXISTS payments ("
        " id INTEGER PRIMARY KEY AUTOINCREMENT,"
        " booking_id INTEGER NOT NULL REFERENCES bookings(id) ON DELETE CASCADE,"
        " amount REAL NOT NULL,"
        " payment_date TEXT NOT NULL,"
        " notes TEXT,"
        " created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,"
        " request_id TEXT)"
    ),
    (
        "CREATE TABLE IF NOT EXISTS sessions ("
        " token_hash TEXT PRIMARY KEY,"
        " csrf_token TEXT NOT NULL,"
        " username TEXT NOT NULL,"
        " created_at TEXT NOT NULL,"
        " expires_at TEXT NOT NULL)"
    ),
    (
        "CREATE TABLE IF NOT EXISTS login_attempts ("
        " id INTEGER PRIMARY KEY AUTOINCREMENT,"
        " attempt_key TEXT NOT NULL,"
        " attempted_at TEXT NOT NULL)"
    ),
    (
        "CREATE INDEX IF NOT EXISTS idx_login_attempts_key "
        "ON login_attempts(attempt_key, attempted_at)"
    ),
    (
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_payments_request_id "
        "ON payments(request_id) WHERE request_id IS NOT NULL"
    ),
    (
        "CREATE INDEX IF NOT EXISTS idx_payments_booking_id "
        "ON payments(booking_id)"
    ),
    (
        "CREATE INDEX IF NOT EXISTS idx_bookings_function_date "
        "ON bookings(function_date)"
    ),
    (
        "CREATE INDEX IF NOT EXISTS idx_bookings_balance "
        "ON bookings(balance)"
    ),
]

# Columns added by older app versions; kept idempotent for fresh databases.
COLUMN_MIGRATIONS: List[tuple] = [
    ("settings", "financial_start_date", "TEXT"),
    ("settings", "financial_end_date", "TEXT"),
    ("payments", "request_id", "TEXT"),
]


def run_script(conn: Connection, statements: Sequence[str]) -> None:
    """Run idempotent DDL statements in as few round trips as possible.

    On Turso the whole script travels in one ``sequence`` pipeline request; on
    SQLite (or if the script endpoint is unavailable) the statements run one
    by one. Statements are always ``IF NOT EXISTS`` DDL, so retrying them is
    harmless and a fallback can never corrupt the schema.
    """
    if conn.backend == "turso" and len(statements) > 1:
        session = getattr(conn._inner, "_session", None)
        if session is not None and hasattr(session, "execute_pipeline"):
            try:
                results = session.execute_pipeline(
                    [{"type": "sequence", "sql": ";\n".join(statements)}]
                )
                for result in results:
                    if result.get("type") == "error":
                        # Fall back so the failure surfaces with the normal
                        # driver error type (startup logging depends on it).
                        raise RuntimeError("schema script failed")
                return
            except Exception:
                pass
    for statement in statements:
        conn.execute(statement)


def ensure_schema(conn: Connection) -> None:
    """Create tables, indexes and missing columns. Never drops data."""
    run_script(conn, [statement for statement in SCHEMA_STATEMENTS])
    for table, column, ddl in COLUMN_MIGRATIONS:
        conn.ensure_column(table, column, ddl)
    conn.commit()
