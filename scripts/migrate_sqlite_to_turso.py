"""Migrate the local SQLite database to Turso (or a rehearsal SQLite file).

What it does:
  1. Opens the source database read-only and records its fingerprint
     (row counts + money totals + SHA-256 of the file).
  2. Connects the target (Turso via env vars, or --target-sqlite for a
     local rehearsal) and creates/normalises the schema.
  3. Aborts before writing anything if target rows conflict with the source
     (same token / request_id owned by different data).
  4. Copies settings, bookings and payments (ids preserved, chunked,
     INSERT OR IGNORE so a re-run is idempotent).
  5. Verifies counts and money totals on both sides and writes a
     PII-free report (no customer names or phone numbers).

Modes:
  --target-sqlite PATH   rehearse against a local file (no Turso needed)
  --dry-run              full rehearsal on the real target, then ROLLBACK
  --verify-only          compare an already migrated target, copy nothing

Exit codes: 0 = PASS, 1 = FAIL, 2 = configuration/usage error.

Usage:
  python scripts/migrate_sqlite_to_turso.py --target-sqlite /tmp/turso_rehearsal.db
  TURSO_DATABASE_URL=... TURSO_AUTH_TOKEN=... python scripts/migrate_sqlite_to_turso.py
"""

import argparse
import hashlib
import os
import sqlite3
import sys
import time
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import db as dbmod  # noqa: E402

TABLES = ("settings", "bookings", "payments")
CHUNK = 200


def sha256_file(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def open_source(path: str) -> sqlite3.Connection:
    if not os.path.exists(path):
        raise SystemExit(f"source database not found: {path}")
    # Read-only: the live database can never be modified by this tool.
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def table_columns(conn, table: str) -> list:
    return [row[1] for row in conn.execute(f"PRAGMA table_info({table})")]


def row_counts(conn, tables=TABLES) -> dict:
    counts = {}
    for table in tables:
        counts[table] = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    return counts


def money_totals(conn) -> dict:
    booking = conn.execute(
        "SELECT COALESCE(SUM(grand_total),0) g, COALESCE(SUM(advance_paid),0) a,"
        " COALESCE(SUM(balance),0) b, COALESCE(MAX(id),0) m FROM bookings"
    ).fetchone()
    payment = conn.execute(
        "SELECT COALESCE(SUM(amount),0) s, COALESCE(MAX(id),0) m FROM payments"
    ).fetchone()
    return {
        "grand_total": round(booking["g"] if isinstance(booking, sqlite3.Row) else booking[0], 2),
        "advance_paid": round(booking[1], 2),
        "balance": round(booking[2], 2),
        "max_booking_id": int(booking[3]),
        "payment_sum": round(payment[0], 2),
        "max_payment_id": int(payment[1]),
    }


def connect_target(args) -> dbmod.Connection:
    if args.target_sqlite:
        conn = dbmod.connect_sqlite(args.target_sqlite)
        target_label = os.path.abspath(args.target_sqlite)
        return conn, target_label
    url = os.environ.get("TURSO_DATABASE_URL", "").strip()
    token = os.environ.get("TURSO_AUTH_TOKEN", "").strip()
    if not url or not token:
        print(
            "ERROR: TURSO_DATABASE_URL and TURSO_AUTH_TOKEN are required "
            "(or use --target-sqlite PATH for a rehearsal).",
            file=sys.stderr,
        )
        raise SystemExit(2)
    conn = dbmod.connect_turso()
    host = url.split("//", 1)[-1].split("/", 1)[0]
    return conn, f"turso:{host}"


def fetch_all(conn, sql: str, params=()):
    cursor = conn.cursor()
    cursor.execute(sql, params)
    rows = cursor.fetchall()
    # Normalise both sqlite3.Row and db.Row into plain dicts.
    if rows and not isinstance(rows[0], dict):
        keys = [d[0] for d in cursor.description]
        rows = [dict(zip(keys, tuple(row))) for row in rows]
    return rows


def precheck_conflicts(source: sqlite3.Connection, target) -> list:
    """Return a list of hard conflicts (empty means safe to copy)."""
    conflicts = []

    # Bookings: a token or id may only belong to the same booking on both sides.
    src_by_token = {
        r["token_number"]: r["id"]
        for r in fetch_all(source, "SELECT id, token_number FROM bookings")
    }
    src_id_to_token = {sid: tok for tok, sid in src_by_token.items()}
    for row in fetch_all(target, "SELECT id, token_number FROM bookings"):
        token, row_id = row["token_number"], row["id"]
        if token in src_by_token and src_by_token[token] != row_id:
            conflicts.append(
                f"bookings.token_number={token} exists in target with a different id"
            )
        if row_id in src_id_to_token and src_id_to_token[row_id] != token:
            conflicts.append(
                f"bookings.id={row_id} exists in target with token {token} "
                f"instead of {src_id_to_token[row_id]}"
            )

    # Payments: ids (and request_ids when present) must map to the same data.
    src_pay = {
        r["id"]: (r["amount"], r["booking_id"], r["request_id"])
        for r in fetch_all(
            source, "SELECT id, amount, booking_id, request_id FROM payments"
        )
    }
    for row in fetch_all(
        target, "SELECT id, amount, booking_id, request_id FROM payments"
    ):
        row_id = row["id"]
        if row_id not in src_pay:
            continue
        src_amount, src_booking, _src_rid = src_pay[row_id]
        if (
            round(float(src_amount), 2) != round(float(row["amount"]), 2)
            or src_booking != row["booking_id"]
        ):
            conflicts.append(
                f"payments.id={row_id} exists in target with different amount/booking"
            )
        rid = row["request_id"]
        if rid is not None and rid != _src_rid:
            conflicts.append(
                f"payments.id={row_id} request_id mismatch ({rid} vs {_src_rid})"
            )
    return conflicts


def copy_rows(source: sqlite3.Connection, target) -> dict:
    copied = {}

    # settings: single row, source always wins (upsert by id).
    src_settings = fetch_all(source, "SELECT * FROM settings")
    tgt_cols = set(table_columns(target, "settings"))
    if src_settings:
        cols = [c for c in src_settings[0] if c in tgt_cols]
        if cols:
            values = [src_settings[0][c] for c in cols]
            placeholders = ", ".join("?" for _ in cols)
            updates = ", ".join(
                f"{c}=excluded.{c}" for c in cols if c != "id"
            )
            sql = (
                f"INSERT INTO settings ({', '.join(cols)}) VALUES ({placeholders}) "
                f"ON CONFLICT(id) DO UPDATE SET {updates}"
            )
            target.execute(sql, values)
            copied["settings"] = 1

    for table in ("bookings", "payments"):
        rows = fetch_all(source, f"SELECT * FROM {table} ORDER BY id")
        tgt_cols = set(table_columns(target, table))
        cols = [c for c in (rows[0].keys() if rows else []) if c in tgt_cols]
        if not cols:
            copied[table] = 0
            continue
        placeholders = ", ".join("?" for _ in cols)
        sql = (
            f"INSERT OR IGNORE INTO {table} ({', '.join(cols)}) "
            f"VALUES ({placeholders})"
        )
        count = 0
        for start in range(0, len(rows), CHUNK):
            batch = rows[start:start + CHUNK]
            cursor = target.executemany(sql, [tuple(r[c] for c in cols) for r in batch])
            # rowcount = rows actually inserted (0 for already-migrated rows).
            rowcount = getattr(cursor, "rowcount", -1)
            count += rowcount if (rowcount is not None and rowcount >= 0) else len(batch)
        copied[table] = count
    return copied


def verify(source: sqlite3.Connection, target) -> tuple:
    problems = []
    src_counts = row_counts(source)
    tgt_counts = row_counts(target)
    for table in TABLES:
        if src_counts[table] != tgt_counts.get(table):
            problems.append(
                f"{table}: source has {src_counts[table]} rows, "
                f"target has {tgt_counts.get(table)}"
            )

    src_money = money_totals(source)
    tgt_money = money_totals(target)
    for key in ("grand_total", "advance_paid", "balance", "payment_sum"):
        if abs(float(src_money[key]) - float(tgt_money[key])) > 0.01:
            problems.append(
                f"{key}: source {src_money[key]} != target {tgt_money[key]}"
            )
    return problems, src_counts, tgt_counts, src_money, tgt_money


def write_report(path: str, lines: list) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sqlite", default="smm_traders.db", help="source SQLite file")
    parser.add_argument("--target-sqlite", default=None,
                        help="rehearsal target: local SQLite path (no Turso)")
    parser.add_argument("--dry-run", action="store_true",
                        help="copy then ROLLBACK (nothing persisted)")
    parser.add_argument("--verify-only", action="store_true",
                        help="compare source and target without copying")
    parser.add_argument("--report", default="migration_report.txt",
                        help="output path of the PII-free report")
    args = parser.parse_args()

    started = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    source = open_source(args.sqlite)
    src_sha = sha256_file(args.sqlite)
    src_counts = row_counts(source)
    src_money = money_totals(source)

    target, target_label = connect_target(args)
    print(f"source : {os.path.abspath(args.sqlite)}")
    print(f"target : {target_label}")
    print(f"sha256 : {src_sha}")
    print(f"rows   : {src_counts}")

    exit_code = 1
    problems = []
    phase = "verify-only"
    try:
        dbmod.ensure_schema(target)

        if not args.verify_only:
            conflicts = precheck_conflicts(source, target)
            if conflicts:
                print("\nCONFLICTS - nothing was copied:", file=sys.stderr)
                for line in conflicts:
                    print(f"  - {line}", file=sys.stderr)
                write_report(args.report, [
                    "SMMTRADERS migration report",
                    f"started: {started}",
                    f"source sha256: {src_sha}",
                    "result: ABORTED (conflicts)",
                    "conflicts:",
                    *[f"  - {c}" for c in conflicts],
                ])
                return 1

            phase = "dry-run" if args.dry_run else "copy"
            copied = copy_rows(source, target)
            print(f"copied: {copied}")
            if not args.dry_run:
                target.commit()

        # Verify BEFORE any dry-run rollback so the comparison stays valid.
        problems, _, tgt_counts, _, tgt_money = verify(source, target)
        exit_code = 0 if not problems else 1

        if not args.verify_only and args.dry_run:
            target.rollback()
            print("dry-run: target transaction rolled back")
    finally:
        source.close()
        try:
            target.close()
        except Exception:
            pass

    status_word = "PASS" if exit_code == 0 else "FAIL"
    lines = [
        "SMMTRADERS migration report",
        f"started : {started}",
        f"phase   : {phase}",
        f"source  : {os.path.abspath(args.sqlite)}",
        f"sha256  : {src_sha}",
        f"target  : {target_label}",
        f"result  : {status_word}",
        "",
        "row counts (source):",
        *[f"  {t}: {src_counts[t]}" for t in TABLES],
        "row counts (target):",
        *[f"  {t}: {tgt_counts.get(t)}" for t in TABLES],
        "",
        "money totals (source):",
        f"  grand_total : {src_money['grand_total']}",
        f"  advance_paid: {src_money['advance_paid']}",
        f"  balance     : {src_money['balance']}",
        f"  payments    : {src_money['payment_sum']}",
        "money totals (target):",
        f"  grand_total : {tgt_money['grand_total']}",
        f"  advance_paid: {tgt_money['advance_paid']}",
        f"  balance     : {tgt_money['balance']}",
        f"  payments    : {tgt_money['payment_sum']}",
    ]
    if problems:
        lines += ["", "problems:", *[f"  - {p}" for p in problems]]
    lines += ["", "note: contains no customer names or phone numbers."]
    write_report(args.report, lines)

    print(f"\n{status_word} - report written to {args.report}")
    if problems:
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
