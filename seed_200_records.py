import os
import random
import sqlite3
from datetime import datetime, timedelta

DB_PATH = "smm_traders.db"

FIRST_NAMES = [
    "Mohamed", "Hameed", "Ibrahim", "Meeran", "Syed", "Abdul", "Rahman", "Jafar",
    "Musthafa", "Sultan", "Bilal", "Usman", "Tariq", "Salim", "Anwar", "Farook",
    "Murugan", "Selvam", "Kumar", "Rajesh", "Vijay", "Karthik", "Senthil", "Ravi",
    "Manikandan", "Suresh", "Ganesh", "Praveen", "Dinesh", "Saravanan", "Muthu", "Ramesh",
    "Ashok", "Vignesh", "Sundar", "Pandian", "Bala", "Shankar", "Vasanth", "Gopal"
]

LAST_NAMES = [
    "Rowther", "Marikkar", "Labbai", "Sha", "Ali", "Khan", "Basha", "Hussain",
    "Chettiar", "Pillai", "Nadar", "Thevar", "Gounder", "Naicker", "Reddy", "Iyer"
]

VILLAGES = [
    "Tenkasi Town", "Kadayanallur", "Shenkottai", "Courtallam", "Surandai",
    "Puliyangudi", "Alangulam", "Sankarankovil", "Ambasamudram", "Tirunelveli Town",
    "Pavoorchatram", "Ilanji", "Sambavar Vadagarai", "Achanpudur", "Vadakarai",
    "Sundarapandiapuram", "Chockampatti", "Vickramasingapuram", "Cheranmahadevi"
]

TIMES = ["11:30", "12:00", "12:30", "13:00", "13:30", "14:00", "18:30", "19:00", "19:30", "20:00"]

def seed_database():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    cursor = conn.cursor()

    # Get settings for item prices
    cursor.execute("SELECT mutton_biriyani_price, chicken_65_price FROM settings WHERE id = 1")
    setting = cursor.fetchone()
    mutton_price = float(setting[0]) if setting else 2500.0
    chicken_price = float(setting[1]) if setting else 350.0

    # Clear existing test data
    cursor.execute("DELETE FROM payments")
    cursor.execute("DELETE FROM bookings")

    random.seed(42)  # For reproducible realistic data

    today = datetime(2026, 10, 13)
    bookings_to_insert = []
    payments_to_insert = []

    mutton_options = [round(x * 0.25, 2) for x in range(4, 33)]  # 1.00 Padi up to 8.00 Padi
    chicken_options = [round(x * 0.25, 2) for x in range(1, 21)]  # 0.25 Kg up to 5.00 Kg

    for i in range(1, 201):
        token_number = f"SMM{i:04d}"
        cust_name = f"{random.choice(FIRST_NAMES)} {random.choice(LAST_NAMES)}"
        phone = f"9{random.randint(100000000, 999999999)}"
        village = random.choice(VILLAGES)
        
        # Booking date between 1 and 20 days ago
        b_offset = random.randint(1, 20)
        b_date = (today - timedelta(days=b_offset)).strftime("%Y-%m-%d")
        
        # Function date between 5 days ago and 25 days in future
        f_offset = random.randint(-5, 25)
        f_date = (today + timedelta(days=f_offset)).strftime("%Y-%m-%d")
        pickup_time = random.choice(TIMES)
        
        m_qty = random.choice(mutton_options)
        c_qty = random.choice(chicken_options)
        
        grand_total = round(m_qty * mutton_price + c_qty * chicken_price, 2)
        
        # Determine status and payments
        # If function date was in the past, high chance it's collected
        if f_offset < 0:
            status = random.choice(["collected", "collected", "pending"])
        else:
            status = "collected" if random.random() < 0.25 else "pending"
        
        if status == "collected":
            # Collected: mostly fully paid, occasionally with tiny balance
            if random.random() < 0.85:
                advance_paid = grand_total
                balance = 0.0
            else:
                advance_paid = round(grand_total * 0.8, 2)
                balance = round(grand_total - advance_paid, 2)
        else:
            # Pending: advance paid between 10% and 60% rounded to nearest 100 or 500
            pct = random.choice([0.15, 0.25, 0.35, 0.5, 0.6])
            adv_raw = grand_total * pct
            advance_paid = round(adv_raw / 100) * 100.0
            advance_paid = min(advance_paid, grand_total)
            balance = round(grand_total - advance_paid, 2)
        
        notes = random.choice(["", "", "", "Extra spicy", "Less oil", "Wedding order", "Birthday party", "Deliver packing hot", "Family gathering"])
        
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
                ?, ?
            )
        """, (
            token_number, cust_name, phone, village,
            b_date, f_date, pickup_time,
            m_qty, mutton_price,
            c_qty, chicken_price,
            grand_total, advance_paid, balance,
            status, notes
        ))
        booking_id = cursor.lastrowid
        
        # Insert initial advance payment if any
        if advance_paid > 0:
            cursor.execute("""
                INSERT INTO payments (booking_id, amount, payment_date, notes)
                VALUES (?, ?, ?, 'Advance Payment')
            """, (booking_id, advance_paid, b_date))
            
            # If collected and had a second payment on collection day
            if status == "collected" and balance == 0.0 and advance_paid > 0 and random.random() < 0.4:
                # Split into advance and collection payment
                pass

    conn.commit()
    cursor.execute("SELECT COUNT(*), SUM(grand_total), SUM(advance_paid), SUM(balance), SUM(mutton_qty), SUM(chicken_qty) FROM bookings")
    summary = cursor.fetchone()
    print("Successfully seeded 200 bookings!")
    print(f"Total Bookings: {summary[0]}")
    print(f"Total Revenue:  Rs. {summary[1]:,.2f}")
    print(f"Total Advance:  Rs. {summary[2]:,.2f}")
    print(f"Total Balance:  Rs. {summary[3]:,.2f}")
    print(f"Total Mutton:   {summary[4]:,.2f} Padi")
    print(f"Total Chicken:  {summary[5]:,.2f} Kg")
    conn.close()

if __name__ == "__main__":
    seed_database()
