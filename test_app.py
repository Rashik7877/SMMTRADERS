"""Automated tests for the SMMTRADERS API.

These tests run against a throwaway SQLite database; the production
``smm_traders.db`` is never touched. Run with::

    python -m pytest test_app.py -v
"""

import os
import re
import sqlite3
import tempfile

import pytest

# Point the application at a scratch database *before* importing it so that no
# code path can ever fall back to the real production database during import.
os.environ.setdefault("SMM_TRADERS_DB", os.path.join(tempfile.mkdtemp(), "import_guard.db"))

import main  # noqa: E402  (import after env is set)
from fastapi.testclient import TestClient  # noqa: E402


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #

@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "DB_PATH", str(tmp_path / "test.db"))
    with TestClient(main.app) as c:
        yield c


def create_booking(client, name="Alice", phone="9876543210", date="2025-06-01",
                   mutton=1.0, chicken=0.0, advance=0.0):
    resp = client.post("/api/bookings", json={
        "customer_name": name,
        "phone": phone,
        "function_date": date,
        "mutton_qty": mutton,
        "chicken_qty": chicken,
        "advance_paid": advance,
    })
    assert resp.status_code == 201, resp.text
    return resp.json()


def put_settings(client, **overrides):
    current = client.get("/api/settings").json()
    payload = {
        "business_name": current["business_name"],
        "address": current.get("address") or "",
        "phone": current.get("phone") or "",
        "mutton_biriyani_price": current["mutton_biriyani_price"],
        "chicken_65_price": current["chicken_65_price"],
        "collection_date": current.get("collection_date") or "",
        "collection_time": current.get("collection_time") or "",
        "receipt_footer": current.get("receipt_footer") or "",
        "financial_start_date": current.get("financial_start_date") or "",
        "financial_end_date": current.get("financial_end_date") or "",
    }
    payload.update(overrides)
    return client.put("/api/settings", json=payload)


# --------------------------------------------------------------------------- #
# Pure helper units
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("raw,expected", [
    ("9876543210", "9876543210"),
    ("+919876543210", "9876543210"),
    ("919876543210", "9876543210"),
    ("09876543210", "9876543210"),
    ("98765 43210", "9876543210"),
    ("98765-43210", "9876543210"),
])
def test_normalize_phone_valid(raw, expected):
    assert main.normalize_phone(raw) == expected


@pytest.mark.parametrize("raw", [
    "", "   ", None, "1234567890", "abc", "abcdefghij",
    "98765", "98765432101", "5", "phone-number",
    "+14155552671", "91234567890",
])
def test_normalize_phone_invalid(raw):
    with pytest.raises(ValueError):
        main.normalize_phone(raw)


@pytest.mark.parametrize("raw,expected", [
    ("SMM0001", ("SMM0001", 1)),
    ("s m m 0001", ("SMM0001", 1)),
    ("  SMM1  ", ("SMM1", 1)),
    ("SMM\n0042", ("SMM0042", 42)),
    ("SMM\t7", ("SMM7", 7)),
])
def test_parse_scan_payload_valid(raw, expected):
    assert main.parse_scan_payload(raw) == expected


@pytest.mark.parametrize("raw", ["", "HELLO", "SM0001", "SMM", "SMMabc", None, "123"])
def test_parse_scan_payload_invalid(raw):
    assert main.parse_scan_payload(raw) == (None, None)


# --------------------------------------------------------------------------- #
# Scan / QR resolution
# --------------------------------------------------------------------------- #

def test_scan_various_formats_resolve_same_booking(client):
    booking = create_booking(client)
    assert booking["token_number"] == "SMM0001"
    for code in ["SMM0001", "smm0001", "S M M 0001", "S M M 1", "SMM1", "\nSMM0001\n", "s m m 1"]:
        resp = client.get("/api/scan", params={"code": code})
        assert resp.status_code == 200, (code, resp.text)
        assert resp.json()["token_number"] == "SMM0001", code


def test_scan_never_returns_the_wrong_customer(client):
    create_booking(client, name="First")
    create_booking(client, name="Second")
    for _ in range(10):
        create_booking(client, name="Filler")

    assert client.get("/api/scan", params={"code": "SMM1"}).json()["customer_name"] == "First"
    assert client.get("/api/scan", params={"code": "SMM2"}).json()["customer_name"] == "Second"
    assert client.get("/api/scan", params={"code": "SMM0010"}).json()["token_number"] == "SMM0010"
    assert client.get("/api/scan", params={"code": "SMM10"}).json()["token_number"] == "SMM0010"


def test_scan_malformed_and_missing(client):
    create_booking(client)
    for code in ["HELLO", "SMMabc", "SM0001", "SMM"]:
        assert client.get("/api/scan", params={"code": code}).status_code == 400
    assert client.get("/api/scan", params={"code": ""}).status_code == 400
    assert client.get("/api/scan").status_code == 422  # code is required
    assert client.get("/api/scan", params={"code": "SMM9999"}).status_code == 404


def test_by_token_accepts_bare_digits(client):
    create_booking(client)
    resp = client.get("/api/bookings/by-token/1")
    assert resp.status_code == 200
    assert resp.json()["token_number"] == "SMM0001"
    assert client.get("/api/bookings/by-token/HELLO").status_code == 400


# --------------------------------------------------------------------------- #
# Phone validation through the API
# --------------------------------------------------------------------------- #

def test_create_booking_stores_bare_indian_number(client):
    b = create_booking(client, phone="+91 98765-43210")
    assert b["phone"] == "9876543210"


def test_create_booking_rejects_international_number(client):
    resp = client.post("/api/bookings", json={
        "customer_name": "Intl",
        "phone": "+14155552671",
        "function_date": "2025-06-01",
        "mutton_qty": 1.0,
    })
    assert resp.status_code == 422


def test_booking_phone_is_limited_to_ten_digits(client):
    b = create_booking(client, phone="9876543210")
    assert b["phone"] == "9876543210"
    assert len(b["phone"]) == 10


@pytest.mark.parametrize("bad", ["1234567890", "abcdefghij", "98765", "", "98765a4321"])
def test_create_booking_rejects_bad_phone(client, bad):
    resp = client.post("/api/bookings", json={
        "customer_name": "Bad Phone",
        "phone": bad,
        "function_date": "2025-06-01",
        "mutton_qty": 1.0,
    })
    assert resp.status_code == 422


def test_update_booking_rejects_bad_phone(client):
    b = create_booking(client)
    resp = client.put(f"/api/bookings/{b['id']}", json={
        "customer_name": b["customer_name"],
        "phone": "not-a-phone",
        "function_date": b["function_date"],
        "mutton_qty": 1.0,
        "chicken_qty": 0.0,
    })
    assert resp.status_code == 422


# --------------------------------------------------------------------------- #
# Booking field validation
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("qty,expected", [(1.25, 201), (0.0, 201), (2.5, 201), (1.1, 422), (0.3, 422)])
def test_quantity_must_be_quarter_steps(client, qty, expected):
    resp = client.post("/api/bookings", json={
        "customer_name": "Qty Test",
        "phone": "9876543210",
        "function_date": "2025-06-01",
        "mutton_qty": qty,
    })
    assert resp.status_code == expected, resp.text


def test_booking_requires_valid_function_date(client):
    resp = client.post("/api/bookings", json={
        "customer_name": "Date Test",
        "phone": "9876543210",
        "function_date": "2025-13-99",
        "mutton_qty": 1.0,
    })
    assert resp.status_code == 422


def test_new_booking_collection_date_is_fixed_by_settings(client):
    put_settings(client, collection_date="2030-12-31")
    # Even an explicit date is ignored: Settings owns the collection date.
    b = create_booking(client, date="2025-06-01")
    assert b["function_date"] == "2030-12-31"


def test_new_booking_requires_collection_date_in_settings(client):
    resp = client.post("/api/bookings", json={
        "customer_name": "No Date",
        "phone": "9876543210",
        "mutton_qty": 1.0,
    })
    assert resp.status_code == 400


# --------------------------------------------------------------------------- #
# Settings: collection defaults and financial period
# --------------------------------------------------------------------------- #

def test_creating_booking_does_not_change_collection_settings(client):
    put_settings(client, collection_date="2030-12-31", collection_time="18:30")
    create_booking(client, date="2025-06-01")
    create_booking(client, date="2025-07-01")

    settings = client.get("/api/settings").json()
    assert settings["collection_date"] == "2030-12-31"
    assert settings["collection_time"] == "18:30"


def test_financial_period_round_trip(client):
    resp = put_settings(client, financial_start_date="2025-04-01", financial_end_date="2026-03-31")
    assert resp.status_code == 200, resp.text
    settings = client.get("/api/settings").json()
    assert settings["financial_start_date"] == "2025-04-01"
    assert settings["financial_end_date"] == "2026-03-31"


@pytest.mark.parametrize("start,end", [
    ("2025-04-01", ""),
    ("", "2026-03-31"),
    ("2026-03-31", "2025-04-01"),
    ("2025-13-01", "2026-03-31"),
    ("2025-04-01", "not-a-date"),
])
def test_financial_period_rejects_invalid(client, start, end):
    resp = put_settings(client, financial_start_date=start, financial_end_date=end)
    assert resp.status_code == 422, resp.text


# --------------------------------------------------------------------------- #
# Search
# --------------------------------------------------------------------------- #

def test_pending_payments_search_and_filter(client):
    create_booking(client, name="Alice Kumar", phone="9876543210", advance=0.0)
    create_booking(client, name="Bob Raj", phone="9812345678", advance=0.0)
    create_booking(client, name="Carol Das", phone="9800000000", advance=2500.0)  # fully paid

    pending = client.get("/api/bookings", params={"balance_due": True}).json()
    names = {b["customer_name"] for b in pending}
    assert names == {"Alice Kumar", "Bob Raj"}

    by_name = client.get("/api/bookings", params={"balance_due": True, "search": "Alice"}).json()
    assert [b["customer_name"] for b in by_name] == ["Alice Kumar"]

    by_phone = client.get("/api/bookings", params={"balance_due": True, "search": "9812"}).json()
    assert [b["customer_name"] for b in by_phone] == ["Bob Raj"]

    by_token = client.get("/api/bookings", params={"balance_due": True, "search": "SMM0002"}).json()
    assert [b["customer_name"] for b in by_token] == ["Bob Raj"]

    assert client.get("/api/bookings", params={"balance_due": True, "search": "Nobody"}).json() == []


def test_upcoming_search_by_name_phone_token(client):
    create_booking(client, name="Alice Kumar", phone="9876543210")
    create_booking(client, name="Bob Raj", phone="9812345678")

    assert len(client.get("/api/bookings", params={"search": "Alice"}).json()) == 1
    assert len(client.get("/api/bookings", params={"search": "9812345678"}).json()) == 1
    assert len(client.get("/api/bookings", params={"search": "SMM0002"}).json()) == 1
    assert client.get("/api/bookings", params={"search": "ZZZ"}).json() == []


# --------------------------------------------------------------------------- #
# Idempotency (duplicate request_id)
# --------------------------------------------------------------------------- #

def test_collect_is_idempotent_for_same_request_id(client):
    b = create_booking(client, advance=0.0)
    assert b["payments"] == []

    first = client.post(f"/api/bookings/{b['id']}/collect",
                        json={"amount_received": 500.0, "request_id": "scan-1"}).json()
    assert len(first["payments"]) == 1
    assert first["balance"] == 2000.0

    second = client.post(f"/api/bookings/{b['id']}/collect",
                         json={"amount_received": 500.0, "request_id": "scan-1"}).json()
    assert len(second["payments"]) == 1
    assert second["balance"] == 2000.0

    third = client.post(f"/api/bookings/{b['id']}/collect",
                        json={"amount_received": 500.0, "request_id": "scan-2"}).json()
    assert len(third["payments"]) == 2
    assert third["balance"] == 1500.0


def test_add_payment_is_idempotent_for_same_request_id(client):
    b = create_booking(client, advance=100.0)
    assert len(b["payments"]) == 1

    first = client.post(f"/api/bookings/{b['id']}/payment",
                        json={"amount": 100.0, "request_id": "pay-1"}).json()
    assert len(first["payments"]) == 2
    assert first["balance"] == 2300.0

    second = client.post(f"/api/bookings/{b['id']}/payment",
                         json={"amount": 100.0, "request_id": "pay-1"}).json()
    assert len(second["payments"]) == 2
    assert second["balance"] == 2300.0


def test_payment_over_balance_is_rejected(client):
    b = create_booking(client, advance=0.0)
    resp = client.post(f"/api/bookings/{b['id']}/payment", json={"amount": 999999.0})
    assert resp.status_code == 400


# --------------------------------------------------------------------------- #
# PDF reports
# --------------------------------------------------------------------------- #

def _pdf(client, **params):
    query = {"start_date": "2020-01-01", "end_date": "2030-12-31"}
    query.update(params)
    resp = client.get("/api/reports/pdf", params=query)
    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"] == "application/pdf"
    return resp.content


def _page_numbers(data):
    return [int(a) for a, _ in re.findall(rb"\(Page (\d+) of (\d+)\)", data)]


def _amounts(data, label):
    found = re.findall(rb"\(" + label + rb"[^)]*\)", data)
    return [re.search(rb"([0-9][0-9,]*\.[0-9]{2})", item).group(1) for item in found]


def test_pdf_single_page_header_footer_and_no_thank_you(client):
    put_settings(client, receipt_footer="VANAKKAM", collection_date="2030-12-31")
    create_booking(client)

    data = _pdf(client, label="Daily Report")
    assert data.startswith(b"%PDF")
    assert b"/MediaBox [ 0 0 595.2756 841.8898 ]" in data  # A4 portrait
    assert re.findall(rb"\(Page (\d+) of (\d+)\)", data) == [(b"1", b"1")]
    assert data.count(b"VANAKKAM") == 1
    assert b"Thank you for your order" not in data
    assert b"SM MOIDEEN TRADERS" in data
    assert b"Daily Report" in data


def test_pdf_multi_page_sequential_and_balance_continuity(client):
    put_settings(client, receipt_footer="VANAKKAM")
    for i in range(80):
        create_booking(client, name=f"Customer {i}", advance=100.0)

    data = _pdf(client, label="Big Report")
    markers = re.findall(rb"\(Page (\d+) of (\d+)\)", data)
    total = int(markers[-1][1])
    assert total >= 2
    assert [int(a) for a, _ in markers] == list(range(1, total + 1))

    closings = _amounts(data, b"Page closing balance")
    openings = _amounts(data, b"Opening balance brought forward")
    assert len(closings) == total - 1
    assert closings == openings  # every carried-forward amount is brought forward
    assert data.count(b"Final closing balance") == 1

    # 80 x 2400 outstanding = 1,92,000 final closing balance.
    assert b"1,92,000.00" in data


def test_pdf_opening_balance_brought_forward_from_before_period(client):
    create_booking(client, name="Old", date="2024-01-01", advance=0.0)   # balance 2500
    create_booking(client, name="New", date="2025-06-01", advance=0.0)   # balance 2500

    data = _pdf(client, start_date="2025-04-01", end_date="2025-12-31")
    assert b"1,000.00" not in data  # sanity: not a stray value
    openings = _amounts(data, b"Opening balance brought forward")
    # First page is the only page and it has no opening row; the B/F shows in the
    # summary table instead.
    assert openings == []
    assert b"Opening Balance B/F" in data
    assert b"2,500.00" in data  # opening brought forward
    assert b"5,000.00" in data  # final closing = 2500 B/F + 2500 period balance


def test_pdf_rejects_invalid_range(client):
    assert client.get("/api/reports/pdf", params={
        "start_date": "2026-03-31", "end_date": "2025-04-01"}).status_code == 400
    assert client.get("/api/reports/pdf", params={
        "start_date": "bad", "end_date": "2025-04-01"}).status_code == 400


def test_pdf_search_filter_narrows_rows(client):
    create_booking(client, name="Alice Kumar", advance=0.0)
    create_booking(client, name="Bob Raj", advance=0.0)

    data = _pdf(client, search="Alice")
    assert b"Alice Kumar" in data
    assert b"Bob Raj" not in data
