import calendar
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
import os
import sqlite3
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException, Query, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "smm_traders.db")
STATIC_DIR = os.path.join(BASE_DIR, "static")


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                business_name TEXT NOT NULL,
                address TEXT,
                phone TEXT,
                mutton_biriyani_price REAL NOT NULL DEFAULT 2500.0,
                chicken_65_price REAL NOT NULL DEFAULT 350.0,
                collection_date TEXT,
                collection_time TEXT,
                receipt_footer TEXT
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS bookings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                token_number TEXT UNIQUE NOT NULL,
                customer_name TEXT NOT NULL,
                phone TEXT NOT NULL,
                village TEXT,
                booking_date TEXT NOT NULL,
                function_date TEXT NOT NULL,
                pickup_time TEXT,
                mutton_qty REAL NOT NULL DEFAULT 0.0,
                mutton_price_per_kg REAL NOT NULL DEFAULT 0.0,
                chicken_qty REAL NOT NULL DEFAULT 0.0,
                chicken_price_per_kg REAL NOT NULL DEFAULT 0.0,
                grand_total REAL NOT NULL DEFAULT 0.0,
                advance_paid REAL NOT NULL DEFAULT 0.0,
                balance REAL NOT NULL DEFAULT 0.0,
                status TEXT NOT NULL DEFAULT 'pending',
                notes TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS payments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                booking_id INTEGER NOT NULL REFERENCES bookings(id) ON DELETE CASCADE,
                amount REAL NOT NULL,
                payment_date TEXT NOT NULL,
                notes TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        cursor.execute("SELECT COUNT(*) FROM settings WHERE id = 1")
        if cursor.fetchone()[0] == 0:
            cursor.execute("""
                INSERT INTO settings (
                    id, business_name, address, phone,
                    mutton_biriyani_price, chicken_65_price,
                    collection_date, collection_time, receipt_footer
                ) VALUES (
                    1, 'SM MOIDEEN TRADERS', 'Tenkasi, Tamil Nadu', '9876543210',
                    2500.0, 350.0, '', '12:00',
                    'Thank you for your order! Please bring your token/receipt during collection.'
                )
            """)
        conn.commit()


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(title="SM MOIDEEN TRADERS API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


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


class CreateBookingSchema(BaseModel):
    customer_name: str
    phone: str
    village: Optional[str] = ""
    function_date: str
    pickup_time: Optional[str] = ""
    mutton_qty: float = Field(default=0.0, ge=0)
    chicken_qty: float = Field(default=0.0, ge=0)
    advance_paid: float = Field(default=0.0, ge=0)
    notes: Optional[str] = ""

    @field_validator("mutton_qty", "chicken_qty")
    @classmethod
    def validate_quarter_step(cls, v: float) -> float:
        if v < 0:
            raise ValueError("Quantity cannot be negative")
        if round(v * 1000) % 250 != 0:
            raise ValueError("Quantity must be in increments of 0.25 (e.g., 0.25, 0.50, 0.75, 1.00, 1.25)")
        return v


class UpdateBookingSchema(BaseModel):
    customer_name: str
    phone: str
    village: Optional[str] = ""
    function_date: str
    pickup_time: Optional[str] = ""
    mutton_qty: float = Field(default=0.0, ge=0)
    chicken_qty: float = Field(default=0.0, ge=0)
    notes: Optional[str] = ""

    @field_validator("mutton_qty", "chicken_qty")
    @classmethod
    def validate_quarter_step(cls, v: float) -> float:
        if v < 0:
            raise ValueError("Quantity cannot be negative")
        if round(v * 1000) % 250 != 0:
            raise ValueError("Quantity must be in increments of 0.25 (e.g., 0.25, 0.50, 0.75, 1.00, 1.25)")
        return v


class CollectBookingSchema(BaseModel):
    amount_received: float = Field(default=0.0, ge=0)


class AddPaymentSchema(BaseModel):
    amount: float = Field(gt=0)
    notes: Optional[str] = ""


# --- Helper Functions ---

def row_to_dict(row: sqlite3.Row) -> Dict[str, Any]:
    return dict(row)


def get_booking_with_payments(conn: sqlite3.Connection, booking_id: int) -> Optional[Dict[str, Any]]:
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM bookings WHERE id = ?", (booking_id,))
    row = cursor.fetchone()
    if not row:
        return None
    booking = row_to_dict(row)

    cursor.execute("SELECT * FROM payments WHERE booking_id = ? ORDER BY id ASC", (booking_id,))
    booking["payments"] = [row_to_dict(p) for p in cursor.fetchall()]
    return booking


def generate_next_token(conn: sqlite3.Connection) -> str:
    cursor = conn.cursor()
    cursor.execute("SELECT token_number FROM bookings")
    rows = cursor.fetchall()
    highest = 0  # Base number 0, so the first generated token starts at SMM0001
    for r in rows:
        val = str(r[0]).strip()
        if val.upper().startswith("SMM"):
            nums = val[3:]
        else:
            nums = "".join(ch for ch in val if ch.isdigit())
        if nums and nums.isdigit():
            highest = max(highest, int(nums))
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
                receipt_footer = ?
            WHERE id = 1
        """, (
            data.business_name,
            data.address or "",
            data.phone or "",
            data.mutton_biriyani_price,
            data.chicken_65_price,
            data.collection_date or "",
            data.collection_time or "",
            data.receipt_footer or ""
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

        # Attach payments to each booking
        for b in bookings:
            cursor.execute("SELECT * FROM payments WHERE booking_id = ? ORDER BY id ASC", (b["id"],))
            b["payments"] = [row_to_dict(p) for p in cursor.fetchall()]

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
    clean_token = token.strip()
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM bookings WHERE LOWER(token_number) = LOWER(?)", (clean_token,))
        row = cursor.fetchone()
        if not row:
            digits = "".join(ch for ch in clean_token if ch.isdigit())
            if digits:
                formatted_token = f"SMM{int(digits):04d}"
                cursor.execute("SELECT id FROM bookings WHERE LOWER(token_number) = LOWER(?)", (formatted_token,))
                row = cursor.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Booking with token not found")
        return get_booking_with_payments(conn, row["id"])


@app.post("/api/bookings", status_code=status.HTTP_201_CREATED)
def create_booking(data: CreateBookingSchema):
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM settings WHERE id = 1")
        settings = cursor.fetchone()
        mutton_price = float(settings["mutton_biriyani_price"]) if settings else 0.0
        chicken_price = float(settings["chicken_65_price"]) if settings else 0.0

        grand_total = round(data.mutton_qty * mutton_price + data.chicken_qty * chicken_price, 2)
        advance_paid = round(min(data.advance_paid, grand_total), 2)
        balance = round(max(0.0, grand_total - advance_paid), 2)
        booking_date = datetime.now().strftime("%Y-%m-%d")
        token_number = generate_next_token(conn)

        cursor.execute("""
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
        """, (
            token_number,
            data.customer_name.strip(),
            data.phone.strip(),
            data.village.strip() if data.village else "",
            booking_date,
            data.function_date.strip(),
            data.pickup_time.strip() if data.pickup_time else "",
            data.mutton_qty,
            mutton_price,
            data.chicken_qty,
            chicken_price,
            grand_total,
            advance_paid,
            balance,
            data.notes.strip() if data.notes else ""
        ))
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
                function_date = ?,
                pickup_time = ?,
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
            data.function_date.strip(),
            data.pickup_time.strip() if data.pickup_time else "",
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

        today = datetime.now().strftime("%Y-%m-%d")
        grand_total = float(existing["grand_total"])
        old_advance = float(existing["advance_paid"])
        old_balance = float(existing["balance"])

        amount_to_receive = min(data.amount_received, old_balance)
        new_advance = round(old_advance + amount_to_receive, 2)
        new_balance = round(max(0.0, grand_total - new_advance), 2)

        if amount_to_receive > 0:
            cursor.execute("""
                INSERT INTO payments (booking_id, amount, payment_date, notes)
                VALUES (?, ?, ?, 'Collection Payment')
            """, (booking_id, amount_to_receive, today))

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

        today = datetime.now().strftime("%Y-%m-%d")
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

        cursor.execute("""
            INSERT INTO payments (booking_id, amount, payment_date, notes)
            VALUES (?, ?, ?, ?)
        """, (booking_id, data.amount, today, data.notes or "Payment"))

        cursor.execute("""
            UPDATE bookings SET
                advance_paid = ?,
                balance = ?
            WHERE id = ?
        """, (new_advance, new_balance, booking_id))

        conn.commit()
        return get_booking_with_payments(conn, booking_id)


# --- Reports ---

def calculate_report_data(conn: sqlite3.Connection, start_date: str, end_date: str) -> Dict[str, Any]:
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
    today = datetime.now().strftime("%Y-%m-%d")
    with get_db() as conn:
        return calculate_report_data(conn, today, today)


@app.get("/api/reports/weekly")
def weekly_report():
    today = datetime.now().date()
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
