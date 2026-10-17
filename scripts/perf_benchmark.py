"""Read-only performance benchmark for SMMTRADERS.

Measures representative, side-effect-free actions against either the remote
Turso database (production, READ-ONLY -- no INSERT/UPDATE/DELETE is ever
issued) or a throwaway copy of the local SQLite file.

Prints only timings, statement counts and statement descriptors (keyword +
table). No customer data, phone numbers, amounts, SQL values, tokens or
database URLs are ever printed.

Usage:
    python scripts/perf_benchmark.py --backend turso --runs 7
    python scripts/perf_benchmark.py --backend sqlite --runs 15
"""
import argparse
import os
import shutil
import statistics
import sys
import tempfile
import time

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

# Must be set before importing main/db.
os.environ.setdefault("SMM_SKIP_DOTENV", "0")


def _describe(sql: str) -> str:
    """Keyword + first table name only; never parameters or literals."""
    words = sql.split()
    kw = words[0].upper() if words else "?"
    target = ""
    for i, w in enumerate(words):
        if w.upper() in ("FROM", "INTO", "UPDATE"):
            if i + 1 < len(words):
                target = words[i + 1].strip("(),")
            break
    return f"{kw} {target}".strip()


class _Stats:
    def __init__(self):
        self.calls = []  # (descriptor, ms)
        self.db_ms = 0.0

    @property
    def count(self):
        return len(self.calls)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--backend", choices=["turso", "sqlite"], default="turso")
    ap.add_argument("--runs", type=int, default=7)
    args = ap.parse_args()

    if args.backend == "turso":
        from dotenv import load_dotenv
        load_dotenv(os.path.join(BASE, ".env"), override=False)
        if not os.environ.get("TURSO_DATABASE_URL"):
            print("TURSO_DATABASE_URL missing; cannot benchmark turso")
            return 2
    else:
        os.environ.pop("TURSO_DATABASE_URL", None)
        os.environ.pop("TURSO_AUTH_TOKEN", None)
        tmp = tempfile.mkdtemp(prefix="smm_bench_")
        dst = os.path.join(tmp, "bench.db")
        shutil.copyfile(os.path.join(BASE, "smm_traders.db"), dst)
        os.environ["SMM_TRADERS_DB"] = dst

    # A session-secret is required by auth helpers; it is never used to log in.
    os.environ.setdefault("SESSION_SECRET", "benchmark-never-production")
    os.environ.setdefault("ADMIN_PASSWORD_HASH", "benchmark")

    import db  # noqa: E402
    import main as app  # noqa: E402

    if args.backend == "sqlite":
        # main.py loads .env at import time; drop Turso again so get_db()
        # falls back to SQLite (env is read at call time).
        os.environ.pop("TURSO_DATABASE_URL", None)
        os.environ.pop("TURSO_AUTH_TOKEN", None)

    stats = _Stats()
    orig_execute = db._Cursor.execute
    orig_executemany = db._Cursor.executemany

    def timed_execute(self, sql, params=None):
        t0 = time.perf_counter()
        try:
            return orig_execute(self, sql, params)
        finally:
            ms = (time.perf_counter() - t0) * 1000.0
            stats.db_ms += ms
            stats.calls.append((_describe(sql), ms))

    def timed_executemany(self, sql, seq_of_params):
        t0 = time.perf_counter()
        try:
            return orig_executemany(self, sql, seq_of_params)
        finally:
            ms = (time.perf_counter() - t0) * 1000.0
            stats.db_ms += ms
            stats.calls.append((_describe(sql) + " [many]", ms))

    db._Cursor.execute = timed_execute
    db._Cursor.executemany = timed_executemany

    # Warm the connection path once (first statement pays TLS setup).
    with db.get_db() as c:
        c.execute("SELECT 1").fetchone()

    # A token that cannot exist: measures the session-lookup statement only
    # (read-only; returns no rows, so no session side effects).
    fake_hash = "0" * 64

    def session_check():
        t0 = time.perf_counter()
        with db.get_db() as conn:
            conn.execute(
                "SELECT token_hash, csrf_token, username, expires_at"
                " FROM sessions WHERE token_hash = ?",
                (fake_hash,),
            ).fetchone()
        return (time.perf_counter() - t0) * 1000.0

    def pick_booking_id():
        with db.get_db() as conn:
            row = conn.execute("SELECT id FROM bookings ORDER BY id LIMIT 1").fetchone()
        return row[0] if row else None

    booking_id = pick_booking_id()

    season_start, season_end = "2026-04-01", "2027-03-31"
    today = time.strftime("%Y-%m-%d")

    def action_dashboard_load():
        session_check()
        app.get_settings()

    def action_customer_search():
        session_check()
        app.list_bookings(search="a", limit=30)

    def action_booking_lookup():
        if booking_id is None:
            return
        session_check()
        app.get_booking(booking_id)

    def action_pending_payment_search():
        session_check()
        app.list_bookings(
            balance_due=True, start_date=season_start, end_date=season_end,
            order_by="token_number ASC",
        )

    def action_scan_lookup():
        if booking_id is None:
            return
        session_check()
        with db.get_db() as conn:
            app.resolve_scan_code(conn, "SMM1")

    def action_scan_table():
        session_check()
        app.list_bookings(order_by="function_date ASC")

    def action_report():
        # Mirrors the UI: /api/reports/custom and /api/bookings are two
        # separate HTTP calls, each with its own session lookup.
        session_check()
        with db.get_db() as conn:
            app.calculate_report_data(conn, season_start, season_end)
        session_check()
        app.list_bookings(
            start_date=season_start, end_date=season_end,
            order_by="token_number ASC", limit=5000,
        )

    actions = {
        "dashboard load": action_dashboard_load,
        "customer search": action_customer_search,
        "booking lookup": action_booking_lookup,
        "pending-payment search": action_pending_payment_search,
        "scan lookup": action_scan_lookup,
        "scan collection table": action_scan_table,
        "report generation": action_report,
    }

    print(f"backend={args.backend} runs={args.runs}")
    print(f"{'action':26} {'stmts':>5} {'db_ms(med)':>10} {'db_ms(p95)':>10} {'total(med)':>10} {'total(p95)':>10}")
    for name, fn in actions.items():
        totals, dbm, counts = [], [], []
        detail_last = None
        for _ in range(args.runs):
            stats.calls.clear()
            stats.db_ms = 0.0
            t0 = time.perf_counter()
            fn()
            totals.append((time.perf_counter() - t0) * 1000.0)
            dbm.append(stats.db_ms)
            counts.append(stats.count)
            detail_last = list(stats.calls)

        def med(xs):
            return statistics.median(xs)

        def p95(xs):
            xs = sorted(xs)
            idx = min(len(xs) - 1, max(0, int(round(0.95 * (len(xs) - 1)))))
            return xs[idx]

        print(f"{name:26} {counts[0]:5d} {med(dbm):10.1f} {p95(dbm):10.1f} {med(totals):10.1f} {p95(totals):10.1f}")
        if detail_last:
            seen = {}
            for d, ms in detail_last:
                seen.setdefault(d, [0, 0.0])
                seen[d][0] += 1
                seen[d][1] += ms
            breakdown = "; ".join(
                f"{d} x{n} ({ms:.0f}ms)" for d, (n, ms) in sorted(seen.items())
            )
            print(f"{'':26} last run: {breakdown}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
