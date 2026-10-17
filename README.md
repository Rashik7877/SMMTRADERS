# SM MOIDEEN TRADERS

Catering-booking management application: a single-page web UI served by a
FastAPI backend, backed by SQLite locally and Turso (cloud SQLite) in
production, with a secure server-side SuperAdmin sign-in in front of every
API endpoint.

---

## Contents

1. [Architecture](#architecture)
2. [Local setup](#local-setup)
3. [Running the tests](#running-the-tests)
4. [Creating the Turso database](#creating-the-turso-database)
5. [Migrating existing data](#migrating-existing-data)
6. [Deploying to Vercel](#deploying-to-vercel)
7. [Environment variables](#environment-variables)
8. [Security model](#security-model)
9. [Troubleshooting](#troubleshooting)
10. [Known limitations](#known-limitations)
11. [Verification log](#verification-log)

---

## Architecture

| Piece | Local | Vercel |
|---|---|---|
| Web framework | FastAPI (`main.py`, exports `app`) | same — `framework: "fastapi"` |
| Database | SQLite `smm_traders.db` | Turso (libSQL) via `turso_serverless` |
| UI | `static/` (index.html + app.js + style.css) | served from the same function |
| Auth | `auth.py` (sessions in the database) | same |
| Timezone | IST (`now_ist()`) | IST (`now_ist()`) — dates stay identical |

`db.py` is the single database entry point. It picks the backend
automatically:

* `TURSO_DATABASE_URL` set → Turso over HTTPS
* otherwise, locally → SQLite file
* otherwise, on Vercel → **fail closed** with HTTP 503 (no silent fallback)

Schema (`settings`, `bookings`, `payments`, plus `sessions` and
`login_attempts`) is created/normalised idempotently by
`db.ensure_schema()` on start-up.

## Local setup

```powershell
# 1. Install dependencies
pip install -r requirements.txt

# 2. Create your local environment file
copy .env.example .env

# 3. Generate the admin password hash (prompts, never echoes)
python scripts/hash_password.py
#    paste the printed ADMIN_PASSWORD_HASH into .env
#    set SESSION_SECRET to any long random string:
python -c "import secrets; print(secrets.token_urlsafe(48))"

# 4. Start the server
start.bat
#    (equivalent to: python -m uvicorn main:app --host 127.0.0.1 --port 8000 --reload)
```

Open <http://127.0.0.1:8000> and sign in with the username
(`SMMTRADERS` by default) and the password you hashed.

The app loads `.env` automatically at start-up (Vercel injects real
environment variables instead; the test suite disables `.env` loading).

## Running the tests

```powershell
python -m pytest -q
```

120 tests cover the business API (scan/booking/payment/PDF) **and** the
security layer (login, sessions, CSRF, rate limiting, fail-closed
behaviour, cookie hardening, migration rehearsal). Every test uses a
throwaway database in a temporary directory; the production
`smm_traders.db` is never opened.

## Creating the Turso database

Install the [Turso CLI](https://docs.turso.tech/cli/installation), then:

```powershell
turso auth login

# Create a database on the Turso engine (matches the turso_serverless driver).
turso db create --tursodb smm-traders

# Copy these two values into your environment (Vercel + local .env):
turso db show smm-traders --url          # -> TURSO_DATABASE_URL
turso db tokens create smm-traders       # -> TURSO_AUTH_TOKEN
```

> Use `--tursodb` so the database runs on Turso's own engine, which is what
> the `turso_serverless` Python driver speaks.

## Migrating existing data

`scripts/migrate_sqlite_to_turso.py` copies `settings`, `bookings` and
`payments` (IDs preserved) and verifies the result. It opens the source
**read-only**, aborts on conflicts before writing anything, and writes a
PII-free report (no customer names or phone numbers).

```powershell
# 0. Back up the live file first (the tool also records its SHA-256)
copy smm_traders.db smm_traders.backup.db

# 1. Rehearse against a local file — no Turso needed
python scripts/migrate_sqlite_to_turso.py --target-sqlite "$env:TEMP\rehearsal.db"

# 2. Dry run against the real Turso database (copies, verifies, ROLLS BACK)
$env:TURSO_DATABASE_URL="..."; $env:TURSO_AUTH_TOKEN="..."
python scripts/migrate_sqlite_to_turso.py --dry-run

# 3. Real migration
python scripts/migrate_sqlite_to_turso.py

# 4. Later, verify a target without copying anything
python scripts/migrate_sqlite_to_turso.py --verify-only
```

Exit codes: `0` = PASS, `1` = FAIL (or conflicts), `2` = configuration
error. Safe to re-run — already-migrated rows are ignored, and conflicts
(same token/ID belonging to different data) abort with a clear message.

## Deploying to Vercel

1. Push this repository to GitHub (Vercel builds from the remote).
2. Import the project in Vercel. `vercel.json` pins `framework: "fastapi"`,
   so the Python preset loads `main.py` (which exports `app`) as a catch-all
   function — no build command needed.
3. Add the environment variables listed below (Production).
4. Deploy, then visit the site and sign in.

`.vercelignore` keeps tests, scripts, local databases and secrets out of the
uploaded bundle. No custom function timeout is configured, so the platform
default (300s with Fluid compute) applies.

> A root-level catch-all app cannot be targeted by the `vercel.json`
> `functions` key (it only matches per-file functions under `api/`); the
> `framework` preset is the supported way to serve it.

## Environment variables

| Variable | Required | Purpose |
|---|---|---|
| `ADMIN_USERNAME` | recommended | Sign-in name (defaults to `SMMTRADERS`) |
| `ADMIN_PASSWORD_HASH` | **yes** | scrypt hash from `scripts/hash_password.py` |
| `SESSION_SECRET` | **yes** | HMAC key for session cookies (long and random) |
| `TURSO_DATABASE_URL` | **yes on Vercel** | Turso database URL |
| `TURSO_AUTH_TOKEN` | **yes on Vercel** | Turso auth token |
| `CORS_ALLOW_ORIGINS` | no | Comma-separated extra origins (default: same-origin only) |
| `COOKIE_SECURE` | no | Force `Secure` cookies outside Vercel |

Missing `ADMIN_PASSWORD_HASH`/`SESSION_SECRET` → sign-in returns 503 (never
a bypass). Missing Turso config on Vercel → every data endpoint returns 503.

## Security model

* **Server-side sessions.** The database stores only the SHA-256 of the
  session token, so a database leak cannot be replayed. The cookie
  (`smm_session`) is `HttpOnly`, `SameSite=Lax`, `Secure` on Vercel, 7-day
  lifetime, and signed with `SESSION_SECRET`.
* **Default deny.** Every path is protected unless explicitly public:
  `/`, `/login`, `/health`, `/favicon.ico`, `/api/auth/login`,
  `/api/auth/session`, `/static/*`. New endpoints are therefore protected
  automatically.
* **CSRF.** State-changing requests require the per-session
  `X-CSRF-Token` header. The token rotates on login and the previous
  session is invalidated (session-fixation defence).
* **Rate limiting.** 5 failed logins per username + client address per
  15 minutes → HTTP 429.
* **Uniform errors.** Wrong username and wrong password return the same
  message; internal errors never leak configuration or stack traces.
* **Password hashing.** scrypt (n=2¹⁴, r=8, p=1) with a random salt;
  see `auth.hash_password` / `auth.verify_password`.
* **FastAPI docs disabled to anonymous users** — `/docs` and
  `/openapi.json` require a session.

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| Login returns **503** | `ADMIN_PASSWORD_HASH` or `SESSION_SECRET` unset, or on Vercel `TURSO_DATABASE_URL`/`TURSO_AUTH_TOKEN` unset |
| Login returns **429** | Rate limit hit; wait 15 minutes or clear `login_attempts` |
| Redirected to `/login` in a loop | Cookies blocked, or `SESSION_SECRET` changed after sign-in (old cookies become invalid) |
| **401** on API calls | Session expired (7 days) — sign in again |
| PDF shows a missing glyph for ₹ | Server font lacks the rupee sign — see limitations |
| `DatabaseConfigError` in logs | Turso package missing locally (`pip install -r requirements.txt`) |

## Known limitations

* **The Turso leg was not executed against a live Turso database** in this
  environment (no Turso credentials available). All Turso code paths are
  exercised through the `--target-sqlite` rehearsal mode, which uses the
  same `db` module and SQL. Run the dry run in *Migrating existing data*
  once credentials exist to confirm end to end.
* **PDF rupee symbol.** On Vercel's Linux image the bundled Helvetica font
  may not render `₹`. If the glyph shows as a box, add a DejaVu font
  fallback in `pdf_reports.py`.
* **Single admin account.** There is one SuperAdmin identity; there is no
  user management UI. Changing the password means re-hashing and updating
  `ADMIN_PASSWORD_HASH`.
* **Sessions are not revocable per-device** beyond expiry, logout and the
  login-time rotation.

## Verification log

Performed in this repository (Windows, Python 3.14):

* `python -m pytest -q` → **120 passed** (business + security suites).
* Migration rehearsal: fresh copy PASS → re-run PASS (idempotent) →
  planted conflict ABORT (exit 1, nothing copied) → `--verify-only`
  PASS/FAIL as expected → `--dry-run` PASS with rollback confirmed.
* Auth smoke test: login 200 + hardened cookie, CSRF enforced (403),
  authorised write 201, logout invalidates session (401), `/` and `/login`
  redirect correctly.
* Source database restored to its original contents after the smoke test.
