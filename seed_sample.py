"""Seed Coffer with DUMMY sample data for local development.

This is for development only. It inserts obviously-fake customers, income,
expenses and an invoice so you can explore the UI without entering real data.
It contains NO personal information and must never be run against a production
database.

Usage:
    python seed_sample.py            # seed only if the database is empty
    python seed_sample.py --force    # seed even if data already exists
"""

import sys

from db import get_db, init_db, next_invoice_number

SAMPLE_CUSTOMERS = [
    ("Acme Widgets Ltd", "accounts@acme.example", "01234 567890", "1 Example Way, Sampleton", "Net 30 terms"),
    ("Globex Services", "hello@globex.example", "01234 111222", "2 Demo Street, Testville", ""),
    ("Initech LLP", "billing@initech.example", "", "", "Prefers email invoices"),
]

SAMPLE_INCOME = [
    (450.00, "2026-01-15", "Sample job — January"),
    (1200.00, "2026-02-03", "Sample retainer — February"),
    (300.00, "2026-02-20", "Sample callout"),
]

SAMPLE_EXPENSES = [
    (60.00, "2026-01-10", "Fuel", "Travel"),
    (120.00, "2026-01-22", "Materials order", "Supplies"),
    (15.00, "2026-02-05", "Parking", "Travel"),
]


def already_seeded(conn) -> bool:
    n = conn.execute("SELECT COUNT(*) AS c FROM customers").fetchone()["c"]
    return n > 0


def seed():
    init_db()
    conn = get_db()
    force = "--force" in sys.argv

    if already_seeded(conn) and not force:
        print("Database already has data — skipping. Use --force to seed anyway.")
        conn.close()
        return

    cust_ids = []
    for name, email, phone, address, notes in SAMPLE_CUSTOMERS:
        cur = conn.execute(
            "INSERT INTO customers (name, email, phone, address, notes) VALUES (?,?,?,?,?)",
            (name, email, phone, address, notes),
        )
        cust_ids.append(cur.lastrowid)

    for amount, d, ref in SAMPLE_INCOME:
        conn.execute(
            "INSERT INTO income (amount, date, reference) VALUES (?,?,?)",
            (amount, d, ref),
        )

    for amount, d, ref, cat in SAMPLE_EXPENSES:
        conn.execute(
            "INSERT INTO expenses (amount, date, reference, category) VALUES (?,?,?,?)",
            (amount, d, ref, cat),
        )

    inv_no = next_invoice_number(conn)
    cur = conn.execute(
        "INSERT INTO invoices (invoice_number, customer_id, date, due_date, status, notes) "
        "VALUES (?,?,?,?,?,?)",
        (inv_no, cust_ids[0], "2026-02-01", "2026-03-03", "unpaid", "Sample invoice"),
    )
    inv_id = cur.lastrowid
    conn.execute(
        "INSERT INTO invoice_lines (invoice_id, description, date_attended, hours, rate, amount) "
        "VALUES (?,?,?,?,?,?)",
        (inv_id, "Sample service line", "2026-01-28", 5, 30, 150.00),
    )

    conn.commit()
    conn.close()
    print(f"Seeded sample data: {len(SAMPLE_CUSTOMERS)} customers, "
          f"{len(SAMPLE_INCOME)} income, {len(SAMPLE_EXPENSES)} expenses, 1 invoice ({inv_no}).")


if __name__ == "__main__":
    seed()
