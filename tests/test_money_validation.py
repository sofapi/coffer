"""Server-side validation of every route that stores a money value, and the
read-only audit for values stored before that validation existed.

Rules (finance.parse_money): plain digits, optional leading minus, at most two
decimal places, no commas or symbols. Only expenses may be negative.
"""

import sqlite3
from decimal import Decimal

import pytest

import audit_money
import finance
from tests.test_finance import add_customer, add_invoice

VALID = [("1200", 1200.0), ("1200.00", 1200.0), ("0.01", 0.01), (" 45.5 ", 45.5)]

# (input, message fragment) — rejected everywhere.
MALFORMED = [
    ("abc", "must be a number"),
    ("12abc", "must be a number"),
    ("1,200", "without commas"),
    ("1,200.00", "without commas"),
    ("1.200,00", "without commas"),
    ("", "is required"),
    ("NaN", "must be a number"),
    ("nan", "must be a number"),
    ("Infinity", "must be a number"),
    ("-inf", "must be a number"),
    ("1e3", "must be a number"),
    ("£12", "must be a number"),
    ("1.005", "more than two decimal places"),
    ("0.001", "more than two decimal places"),
    ("10000000", "too large"),
]

NEGATIVE = ("-5", "cannot be negative")


def count(conn, table):
    return conn.execute(f"SELECT COUNT(*) c FROM {table}").fetchone()["c"]


def follow(client, res):
    """The page a validation redirect lands on, as HTML."""
    assert res.status_code == 302, res.status_code
    assert "error=" in res.headers["Location"]
    page = client.get(res.headers["Location"])
    assert page.status_code == 200
    return page.get_data(as_text=True)


# --------------------------------------------------------------------------
# parser
# --------------------------------------------------------------------------

@pytest.mark.parametrize("text, expected", [(t, Decimal(str(v))) for t, v in VALID])
def test_parse_money_accepts_plain_amounts(text, expected):
    assert finance.parse_money(text) == expected


@pytest.mark.parametrize("text, message", MALFORMED + [NEGATIVE])
def test_parse_money_rejects(text, message):
    with pytest.raises(finance.MoneyError, match=message):
        finance.parse_money(text)


def test_parse_money_never_reads_1_200_as_1():
    """The defect this exists for: SQLite SUM()s the text '1,200' as 1."""
    with pytest.raises(finance.MoneyError):
        finance.parse_money("1,200")


@pytest.mark.parametrize("text", ["٣", "１２", "+5", "1.", "-", ".", "1 000", True, [1]])
def test_parse_money_rejects_other_lookalikes(text):
    with pytest.raises(finance.MoneyError):
        finance.parse_money(text)


def test_parse_money_optional_empty_is_zero_and_negative_can_be_allowed():
    assert finance.parse_money("", required=False) == 0
    assert finance.parse_money(None, required=False) == 0
    assert finance.parse_money("-40", allow_negative=True) == Decimal("-40")


def test_round_money_rounds_half_up():
    assert finance.round_money(Decimal("1.5") * Decimal("33.33")) == Decimal("50.00")
    assert finance.round_money(Decimal("2.675")) == Decimal("2.68")  # float gives 2.67


# --------------------------------------------------------------------------
# web forms: income and expenses
# --------------------------------------------------------------------------

@pytest.mark.parametrize("route, table, page", [
    ("/income/add", "income", "/income"),
    ("/expenses/add", "expenses", "/expenses"),
])
@pytest.mark.parametrize("text, stored", VALID)
def test_form_accepts_valid_amount(client, conn, route, table, page, text, stored):
    res = client.post(route, data={"amount": text, "date": "2026-05-01"})
    assert res.status_code == 302 and "error=" not in res.headers["Location"]
    row = conn.execute(f"SELECT amount, typeof(amount) t FROM {table}").fetchone()
    assert row["amount"] == stored and row["t"] == "real"


@pytest.mark.parametrize("route, table", [("/income/add", "income"),
                                          ("/expenses/add", "expenses")])
@pytest.mark.parametrize("text, message", MALFORMED)
def test_form_rejects_malformed_amount(client, conn, route, table, text, message):
    html = follow(client, client.post(route, data={"amount": text, "date": "2026-05-01"}))
    assert "alert-danger" in html and message in html
    assert count(conn, table) == 0


def test_form_rejects_missing_amount_field(client, conn):
    html = follow(client, client.post("/income/add", data={"date": "2026-05-01"}))
    assert "Amount is required" in html
    assert count(conn, "income") == 0


def test_income_cannot_be_negative(client, conn):
    html = follow(client, client.post("/income/add", data={"amount": "-5", "date": "2026-05-01"}))
    assert "cannot be negative" in html
    assert count(conn, "income") == 0


def test_expense_may_still_be_negative(client, conn):
    """Existing behaviour: a negative expense is how a refund is recorded."""
    res = client.post("/expenses/add", data={"amount": "-40.00", "date": "2026-05-01"})
    assert "error=" not in res.headers["Location"]
    assert conn.execute("SELECT amount FROM expenses").fetchone()["amount"] == -40.0


# --------------------------------------------------------------------------
# web form: invoice lines
# --------------------------------------------------------------------------

@pytest.fixture()
def invoice_id(conn):
    return add_invoice(conn, add_customer(conn), "2026-05-01", [])


def add_line(client, invoice_id, **fields):
    data = {"description": "Work", "hours": "", "rate": "", "amount": ""}
    data.update(fields)
    return client.post(f"/invoices/{invoice_id}/add-line", data=data)


@pytest.mark.parametrize("text, stored", VALID)
def test_line_accepts_valid_amount(client, conn, invoice_id, text, stored):
    res = add_line(client, invoice_id, amount=text)
    assert "error=" not in res.headers["Location"]
    assert conn.execute("SELECT amount FROM invoice_lines").fetchone()["amount"] == stored


def test_line_amount_is_calculated_from_hours_and_rate_to_the_penny(client, conn, invoice_id):
    add_line(client, invoice_id, hours="1.5", rate="33.33")
    row = conn.execute("SELECT hours, rate, amount FROM invoice_lines").fetchone()
    assert (row["hours"], row["rate"], row["amount"]) == (1.5, 33.33, 50.0)  # not 49.995


def test_line_with_no_amount_hours_or_rate_is_still_allowed(client, conn, invoice_id):
    """Unchanged behaviour: a description-only (zero) line can be added."""
    res = add_line(client, invoice_id)
    assert "error=" not in res.headers["Location"]
    assert conn.execute("SELECT amount FROM invoice_lines").fetchone()["amount"] == 0.0


@pytest.mark.parametrize("field, label", [("amount", "Line amount"), ("rate", "Rate"),
                                          ("hours", "Hours")])
@pytest.mark.parametrize("text, message", [m for m in MALFORMED if m[0]] + [NEGATIVE])
def test_line_rejects_malformed_values(client, conn, invoice_id, field, label, text, message):
    html = follow(client, add_line(client, invoice_id, **{field: text}))
    assert "alert-danger" in html and f"{label}" in html and message in html
    assert count(conn, "invoice_lines") == 0


# --------------------------------------------------------------------------
# JSON API
# --------------------------------------------------------------------------

@pytest.mark.parametrize("route, table", [("/api/income", "income"),
                                          ("/api/expenses", "expenses")])
@pytest.mark.parametrize("value, stored", VALID + [(1200, 1200.0), (12.5, 12.5)])
def test_api_accepts_valid_amount(client, conn, route, table, value, stored):
    res = client.post(route, json={"amount": value, "date": "2026-05-01"})
    assert res.status_code == 201
    assert res.get_json()["amount"] == stored


@pytest.mark.parametrize("route, table", [("/api/income", "income"),
                                          ("/api/expenses", "expenses")])
@pytest.mark.parametrize("value, message", MALFORMED + [
    (None, "is required"), (True, "must be a number"), (1e20, "must be a number"),
    (0.001, "more than two decimal places"),
])
def test_api_rejects_malformed_amount(client, conn, route, table, value, message):
    res = client.post(route, json={"amount": value, "date": "2026-05-01"})
    assert res.status_code == 400
    assert message in res.get_json()["error"]
    assert count(conn, table) == 0


def test_api_rejects_nan_and_infinity_json_literals(client, conn):
    for literal in ("NaN", "Infinity", "-Infinity"):
        res = client.post("/api/income", data=f'{{"amount": {literal}, "date": "2026-05-01"}}',
                          content_type="application/json")
        assert res.status_code == 400, literal
    assert count(conn, "income") == 0


def test_api_rejects_missing_amount_and_non_object_bodies(client, conn):
    assert client.post("/api/income", json={"date": "2026-05-01"}).status_code == 400
    assert client.post("/api/income", json=[1, 2]).status_code == 400
    assert client.post("/api/expenses", data="not json",
                       content_type="application/json").status_code == 400
    assert count(conn, "income") == 0 and count(conn, "expenses") == 0


def test_api_income_cannot_be_negative_but_expense_can(client, conn):
    assert client.post("/api/income", json={"amount": "-5", "date": "2026-05-01"}).status_code == 400
    assert client.post("/api/expenses", json={"amount": -5, "date": "2026-05-01"}).status_code == 201


def test_api_invoice_with_valid_lines(client, conn):
    cid = add_customer(conn)
    res = client.post("/api/invoices", json={"customer_id": cid, "date": "2026-05-01", "lines": [
        {"description": "A", "amount": "1200.00"},
        {"description": "B", "hours": 1.5, "rate": "33.33"},
    ]})
    assert res.status_code == 201
    amounts = [r["amount"] for r in conn.execute("SELECT amount FROM invoice_lines ORDER BY id")]
    assert amounts == [1200.0, 50.0]


@pytest.mark.parametrize("line", [
    {"description": "A", "amount": "abc"},
    {"description": "A", "amount": "1,200"},
    {"description": "A", "amount": "NaN"},
    {"description": "A", "amount": "1.005"},
    {"description": "A", "amount": -5},
    {"description": "A", "rate": "Infinity", "hours": 1},
    {"description": "A", "hours": "-1", "rate": 10},
])
def test_api_invoice_with_a_bad_line_writes_nothing(client, conn, line):
    cid = add_customer(conn)
    res = client.post("/api/invoices", json={"customer_id": cid, "date": "2026-05-01", "lines": [
        {"description": "good", "amount": "10.00"}, line,
    ]})
    assert res.status_code == 400 and res.get_json()["error"]
    assert count(conn, "invoices") == 0 and count(conn, "invoice_lines") == 0


@pytest.mark.parametrize("lines", ["oops", [1, 2], {"description": "A"}])
def test_api_invoice_rejects_malformed_lines(client, conn, lines):
    cid = add_customer(conn)
    res = client.post("/api/invoices", json={"customer_id": cid, "date": "2026-05-01",
                                             "lines": lines})
    assert res.status_code == 400
    assert count(conn, "invoices") == 0


# --------------------------------------------------------------------------
# read-only audit of existing data
# --------------------------------------------------------------------------

@pytest.fixture()
def legacy_db(conn, db_path):
    """A database holding values the old, unvalidated routes could store."""
    for value in ("abc", "1,200", 12.5, -5.0, 49.995, float("inf")):
        conn.execute("INSERT INTO income (amount, date) VALUES (?, '2026-01-01')", (value,))
    conn.execute("INSERT INTO expenses (amount, date) VALUES (-40, '2026-01-01')")
    inv = add_invoice(conn, add_customer(conn), "2026-01-01", [])
    conn.execute("INSERT INTO invoice_lines (invoice_id, description, hours, rate, amount) "
                 "VALUES (?, 'x', 1.5, 33.33, 49.995)", (inv,))
    conn.commit()
    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    return db_path


def test_audit_reports_each_bad_value(legacy_db, capsys):
    assert audit_money.main(["audit_money.py", legacy_db]) == 1
    out = capsys.readouterr().out
    assert "6 problem(s) found" in out
    assert "'abc'" in out and "stored as TEXT (counted as 0.0)" in out
    assert "'1,200'" in out and "stored as TEXT (counted as 1.0)" in out
    assert "negative (now rejected on entry)" in out
    assert "not a finite number" in out
    assert out.count("more than two decimal places") == 2
    assert "12.5 " not in out          # a valid value is not reported
    assert "-40" not in out            # a negative expense is allowed


def test_audit_returns_table_id_and_value(legacy_db):
    conn = sqlite3.connect(legacy_db)
    _, findings = audit_money.audit(conn)
    conn.close()
    assert ("income", 2, "amount", "1,200", "stored as TEXT (counted as 1.0)") in findings
    assert any(f[0] == "invoice_lines" and f[3] == 49.995 for f in findings)


def test_audit_reports_zero_findings_clearly(client, conn, db_path, capsys):
    client.post("/income/add", data={"amount": "1200.00", "date": "2026-05-01"})
    client.post("/expenses/add", data={"amount": "-40", "date": "2026-05-01"})
    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    assert audit_money.main(["audit_money.py", db_path]) == 0
    out = capsys.readouterr().out
    assert "Checked 2 stored values" in out and "No problems found" in out


def test_audit_changes_nothing(legacy_db, tmp_path):
    """Run on a closed copy, as documented: the file is byte-identical after,
    and no -wal / -shm files are created next to it."""
    copy = tmp_path / "backup.db"
    src = sqlite3.connect(legacy_db)
    src.execute("VACUUM INTO ?", (str(copy),))
    src.close()
    before = copy.read_bytes()
    audit_money.main(["audit_money.py", str(copy)])
    assert copy.read_bytes() == before
    assert sorted(p.name for p in tmp_path.iterdir()) == ["backup.db"]


def test_audit_rejects_missing_or_non_database_files(tmp_path):
    assert audit_money.main(["audit_money.py", str(tmp_path / "missing.db")]) == 2
    junk = tmp_path / "junk.db"
    junk.write_text("not a database")
    assert audit_money.main(["audit_money.py", str(junk)]) == 2
    assert audit_money.main(["audit_money.py"]) == 2
