"""Pension contributions: relief arithmetic, UK tax-year allocation, CRUD,
separation from business expenses, Reports / Self Assessment output, exports
and upgrading a database that predates the feature.

The rules these assert against are written out in pensions.py's docstring.
"""

import csv
import io
from datetime import date
from decimal import Decimal

import pytest

import finance
import pensions
from tests.test_finance import add_customer, add_expense, add_income, add_invoice


def add_pension(client, amount, when, **extra):
    form = {"date": when, "amount_paid": amount, "provider": "Example SIPP",
            "relief_method": "relief_at_source", "contribution_type": "regular"}
    form.update(extra)
    return client.post("/pensions/add", data=form)


def all_rows(conn):
    return pensions.list_contributions(conn)


# --------------------------------------------------------------------------
# relief-at-source arithmetic
# --------------------------------------------------------------------------

@pytest.mark.parametrize("net, relief, gross", [
    (8000, 2000, 10000),      # £80 -> £20 relief -> £100
    (80000, 20000, 100000),   # £800 -> £200 -> £1,000
    (40000, 10000, 50000),    # £400 -> £100 -> £500
    (3333, 833, 4166),        # £33.33 / 0.8 = 41.6625 -> £41.66
    (1, 0, 1),                # 1p / 0.8 = 1.25p -> 1p
    (2, 1, 3),                # 2p / 0.8 = 2.5p -> half-up to 3p
])
def test_relief_at_source_split(net, relief, gross):
    assert pensions.split_contribution(net, "0.20", pensions.RELIEF_AT_SOURCE) == {
        "net": net, "relief": relief, "gross": gross,
    }


def test_no_relief_at_source_is_paid_gross():
    split = pensions.split_contribution(80000, "0.20", pensions.NO_RELIEF_AT_SOURCE)
    assert split == {"net": 80000, "relief": 0, "gross": 80000}


def test_relief_rate_is_not_hard_coded():
    assert pensions.split_contribution(
        7500, "0.25", pensions.RELIEF_AT_SOURCE)["gross"] == 10000


@pytest.mark.parametrize("text, pence", [
    ("800", 80000), ("800.5", 80050), ("1200.00", 120000), ("0.01", 1),
])
def test_amounts_parse_to_exact_pence(text, pence):
    assert pensions.parse_amount_to_pence(text) == pence


@pytest.mark.parametrize("text", ["", "abc", "0", "-5", "1.005", "NaN", "Infinity", "1e30",
                                  "1,200.00", "£0.01"])
def test_bad_amounts_are_rejected(text):
    with pytest.raises(pensions.PensionError):
        pensions.parse_amount_to_pence(text)


def test_amounts_are_decimal_not_float(client, conn):
    add_pension(client, "0.10", "2026-05-01")
    add_pension(client, "0.20", "2026-05-02")
    t = pensions.totals(all_rows(conn))
    assert isinstance(t["net"], Decimal)
    assert t["net"] == Decimal("0.30")  # 0.1 + 0.2 in float is 0.30000000000000004


# --------------------------------------------------------------------------
# UK tax years
# --------------------------------------------------------------------------

@pytest.mark.parametrize("d, ty", [
    (date(2027, 4, 5), 2026),   # 5 April belongs to the year that is ending
    (date(2027, 4, 6), 2027),   # 6 April starts the new one
    (date(2026, 4, 6), 2026),
    (date(2027, 1, 1), 2026),
    (date(2026, 12, 31), 2026),
])
def test_tax_year_of(d, ty):
    assert finance.tax_year_of(d) == ty


def test_tax_year_bounds_and_label():
    assert finance.tax_year_bounds(2026) == ("2026-04-06", "2027-04-06")
    assert finance.tax_year_label(2026) == "2026/2027"


def test_5_april_contribution_is_in_the_ending_tax_year(client, conn):
    add_pension(client, "100", "2027-04-05")
    (row,) = all_rows(conn)
    assert row["tax_year"] == 2026
    start, end = finance.tax_year_bounds(2026)
    assert len(pensions.list_contributions(conn, start, end)) == 1
    start, end = finance.tax_year_bounds(2027)
    assert pensions.list_contributions(conn, start, end) == []


def test_6_april_contribution_is_in_the_new_tax_year(client, conn):
    add_pension(client, "100", "2027-04-06")
    (row,) = all_rows(conn)
    assert row["tax_year"] == 2027
    start, end = finance.tax_year_bounds(2026)
    assert pensions.list_contributions(conn, start, end) == []


def test_pensions_page_filters_by_tax_year(client):
    add_pension(client, "111.00", "2027-04-05")
    add_pension(client, "222.00", "2027-04-06")
    html_2026 = client.get("/pensions?ty=2026").get_data(as_text=True)
    html_2027 = client.get("/pensions?ty=2027").get_data(as_text=True)
    html_all = client.get("/pensions?ty=").get_data(as_text=True)
    assert "£111.00" in html_2026 and "£222.00" not in html_2026
    assert "£222.00" in html_2027 and "£111.00" not in html_2027
    assert "£111.00" in html_all and "£222.00" in html_all


# --------------------------------------------------------------------------
# create / edit / delete
# --------------------------------------------------------------------------

def test_create_a_contribution(client, conn):
    res = add_pension(client, "800", "2026-06-01", notes="June payment")
    assert res.status_code == 302
    assert "ty=2026" in res.headers["Location"]
    (row,) = all_rows(conn)
    assert row["net_pence"] == 80000
    assert row["relief_rate"] == "0.20"
    assert row["provider"] == "Example SIPP"
    assert row["notes"] == "June payment"
    assert (row["net"], row["relief"], row["gross"]) == (
        Decimal("800.00"), Decimal("200.00"), Decimal("1000.00"))
    assert row["created_at"] and row["updated_at"]

    html = client.get("/pensions?ty=2026").get_data(as_text=True)
    assert "£800.00" in html and "£200.00" in html and "£1,000.00" in html


def test_invalid_contribution_is_rejected_with_a_message(client, conn):
    res = add_pension(client, "-5", "2026-06-01")
    assert res.status_code == 302 and "error=" in res.headers["Location"]
    res = add_pension(client, "5", "not-a-date")
    assert "error=" in res.headers["Location"]
    res = add_pension(client, "5", "2026-06-01", relief_method="made_up")
    assert "error=" in res.headers["Location"]
    assert all_rows(conn) == []
    html = client.get(res.headers["Location"]).get_data(as_text=True)
    assert "alert-danger" in html


def test_edit_a_contribution(client, conn):
    add_pension(client, "400", "2026-06-01")
    (row,) = all_rows(conn)
    assert client.get(f"/pensions/{row['id']}/edit").status_code == 200

    res = client.post(f"/pensions/{row['id']}/edit", data={
        "date": "2027-04-06", "amount_paid": "80", "provider": "Other Scheme",
        "relief_method": "relief_at_source", "contribution_type": "single", "notes": "moved",
    })
    assert res.status_code == 302
    (row,) = all_rows(conn)
    assert row["date"] == "2027-04-06" and row["tax_year"] == 2027
    assert (row["net"], row["relief"], row["gross"]) == (
        Decimal("80.00"), Decimal("20.00"), Decimal("100.00"))
    assert row["provider"] == "Other Scheme" and row["contribution_type"] == "single"


def test_edit_keeps_the_rate_the_row_was_recorded_with(client, conn):
    import db as db_module
    add_pension(client, "80", "2026-06-01")
    db_module.save_setting(conn, pensions.RELIEF_RATE_SETTING_KEY, "0.25")
    (row,) = all_rows(conn)
    client.post(f"/pensions/{row['id']}/edit", data={
        "date": row["date"], "amount_paid": "80", "relief_method": "relief_at_source",
        "contribution_type": "regular",
    })
    (row,) = all_rows(conn)
    assert row["relief_rate"] == "0.20" and row["gross"] == Decimal("100.00")

    # A new payment uses the newly configured rate.
    add_pension(client, "75", "2026-07-01")
    new = all_rows(conn)[-1]
    assert new["relief_rate"] == "0.25" and new["gross"] == Decimal("100.00")


def test_invalid_edit_changes_nothing(client, conn):
    add_pension(client, "400", "2026-06-01")
    (row,) = all_rows(conn)
    res = client.post(f"/pensions/{row['id']}/edit", data={
        "date": "2026-06-01", "amount_paid": "abc", "relief_method": "relief_at_source",
    })
    assert "error=" in res.headers["Location"]
    assert all_rows(conn)[0]["net"] == Decimal("400.00")


def test_delete_a_contribution(client, conn):
    add_pension(client, "400", "2026-06-01")
    add_pension(client, "100", "2026-07-01")
    first = all_rows(conn)[0]
    res = client.post(f"/pensions/{first['id']}/delete", data={"ty": "2026"})
    assert res.status_code == 302
    remaining = all_rows(conn)
    assert [r["net"] for r in remaining] == [Decimal("100.00")]


def test_missing_contribution_redirects(client):
    assert client.get("/pensions/999/edit").status_code == 302


# --------------------------------------------------------------------------
# totals and separation from business figures
# --------------------------------------------------------------------------

def test_annual_totals(client, conn):
    add_pension(client, "800", "2026-04-06")
    add_pension(client, "400", "2027-04-05")
    add_pension(client, "250", "2026-09-01", relief_method="no_relief_at_source")
    add_pension(client, "999", "2027-04-06")  # next tax year
    start, end = finance.tax_year_bounds(2026)
    t = pensions.totals(pensions.list_contributions(conn, start, end))
    assert t["count"] == 3
    assert t["net"] == Decimal("1450.00")
    assert t["relief"] == Decimal("300.00")
    assert t["gross"] == Decimal("1750.00")
    assert t["ras_net"] == Decimal("1200.00")
    assert t["ras_relief"] == Decimal("300.00")
    assert t["ras_gross"] == Decimal("1500.00")
    assert t["other_gross"] == Decimal("250.00")


def test_pensions_are_not_business_expenses(client, conn):
    add_income(conn, 5000, "2026-06-01")
    add_expense(conn, 1000, "2026-06-02")
    add_pension(client, "800", "2026-06-03")

    assert conn.execute("SELECT COUNT(*) c FROM expenses").fetchone()["c"] == 1
    totals = finance.period_totals(conn, "2026-06-01", "2026-07-01")
    assert totals["costs"] == 1000 and totals["net"] == 4000

    html = client.get("/reports?ty=2026").get_data(as_text=True)
    assert "£1,000.00" in html      # expenses unchanged
    assert "£4,000.00" in html      # profit unchanged by the pension
    assert "£800.00" not in client.get("/expenses").get_data(as_text=True)


# --------------------------------------------------------------------------
# Reports / Self Assessment
# --------------------------------------------------------------------------

def test_reports_show_self_assessment_pension_section(client, conn):
    add_income(conn, 30000, "2026-05-01")
    add_expense(conn, 4000, "2026-05-02")
    add_pension(client, "800", "2026-05-03")
    add_pension(client, "400", "2027-04-05")

    html = client.get("/reports?ty=2026").get_data(as_text=True)
    assert "Self Assessment summary — 2026/2027" in html
    assert "Pension Contributions" in html
    assert "Net personal contributions paid" in html and "£1,200.00" in html
    assert "Basic-rate relief added by provider" in html and "£300.00" in html
    assert "Gross relief-at-source contributions" in html and "£1,500.00" in html
    assert "£30,000.00" in html and "£4,000.00" in html and "£26,000.00" in html


def test_reports_month_view_has_pension_cards_but_no_annual_summary(client):
    add_pension(client, "800", "2026-05-10")
    html = client.get("/reports?ty=2026&month=2026-05").get_data(as_text=True)
    assert "Gross contributions" in html and "£1,000.00" in html
    assert "Self Assessment summary" not in html


def test_tax_year_with_only_pensions_is_selectable(client):
    add_pension(client, "100", "2020-05-01")
    html = client.get("/reports").get_data(as_text=True)
    assert 'value="2020"' in html


# --------------------------------------------------------------------------
# exports
# --------------------------------------------------------------------------

def _csv(res):
    return list(csv.reader(io.StringIO(res.get_data(as_text=True))))


def test_tax_year_csv(client, conn):
    add_income(conn, 30000, "2026-05-01")
    cid = add_customer(conn)
    add_invoice(conn, cid, "2026-06-01", [500, 500], status="paid")
    add_expense(conn, 4000, "2026-05-02")
    add_pension(client, "800", "2026-05-03", notes="May")
    add_pension(client, "50", "2027-04-06")  # next year, excluded

    res = client.get("/export/tax-year.csv?ty=2026")
    assert res.status_code == 200
    assert "tax-year_2026-2027.csv" in res.headers["Content-Disposition"]
    rows = _csv(res)
    lookup = {r[0]: r[1] for r in rows if len(r) == 2}
    assert lookup["Tax Year"] == "2026/2027"
    assert lookup["Period"] == "2026-04-06 to 2027-04-05"
    assert lookup["Income / turnover"] == "31000.00"
    assert lookup["Expenses"] == "4000.00"
    assert lookup["Profit"] == "27000.00"
    assert lookup["Net personal contributions paid"] == "800.00"
    assert lookup["Basic-rate relief added by provider"] == "200.00"
    assert lookup["Gross relief-at-source contributions (Self Assessment)"] == "1000.00"

    schedule = rows[rows.index(["Pension contribution schedule"]) + 2:]
    assert len(schedule) == 1
    assert schedule[0][0] == "2026-05-03" and schedule[0][6:9] == ["800.00", "200.00", "1000.00"]


def test_pensions_csv_date_range_is_inclusive(client):
    add_pension(client, "100", "2026-05-01")
    add_pension(client, "200", "2026-05-31")
    add_pension(client, "300", "2026-06-01")
    rows = _csv(client.get("/export/pensions.csv?from=2026-05-01&to=2026-05-31"))
    assert rows[0][0] == "Date"
    assert [r[0] for r in rows[1:]] == ["2026-05-01", "2026-05-31"]


# --------------------------------------------------------------------------
# upgrading an existing database
# --------------------------------------------------------------------------

def _make_pre_pension_db(conn):
    conn.execute("DROP TABLE pension_contributions")
    conn.execute("DELETE FROM settings WHERE key = ?", (pensions.RELIEF_RATE_SETTING_KEY,))
    conn.commit()


def test_upgrade_adds_pensions_without_touching_existing_records(db_path, conn):
    import db as db_module
    _make_pre_pension_db(conn)
    add_income(conn, 1234.56, "2025-05-01")
    add_expense(conn, 78.9, "2025-05-02", category="Travel")
    cid = add_customer(conn)
    add_invoice(conn, cid, "2025-06-01", [100, 50], status="paid")
    db_module.save_setting(conn, "business_name", "Example Trading")
    before = {t: [tuple(r) for r in conn.execute(f"SELECT * FROM {t} ORDER BY 1")]
              for t in ("income", "expenses", "customers", "invoices", "invoice_lines", "settings")}

    db_module.init_db()
    db_module.init_db()  # boot twice: must be idempotent

    after = {t: [tuple(r) for r in conn.execute(f"SELECT * FROM {t} ORDER BY 1")]
             for t in before}
    assert after["settings"] == sorted(
        before["settings"] + [(pensions.RELIEF_RATE_SETTING_KEY, "0.20")])
    for table in ("income", "expenses", "customers", "invoices", "invoice_lines"):
        assert after[table] == before[table], table
    assert conn.execute("SELECT COUNT(*) c FROM pension_contributions").fetchone()["c"] == 0


def test_existing_pages_work_after_upgrade(db_path, conn, client):
    import db as db_module
    _make_pre_pension_db(conn)
    add_income(conn, 500, "2026-05-01")
    add_expense(conn, 100, "2026-05-02")
    db_module.init_db()
    for path in ("/", "/income", "/expenses", "/reports?ty=2026", "/pensions", "/export"):
        assert client.get(path).status_code == 200, path
    assert "£400.00" in client.get("/reports?ty=2026").get_data(as_text=True)


def test_restoring_a_pre_pension_backup_recreates_the_table(client, conn, tmp_path):
    import sqlite3
    old = tmp_path / "old.db"
    conn.execute("VACUUM INTO ?", (str(old),))
    legacy = sqlite3.connect(old)
    legacy.execute("DROP TABLE pension_contributions")
    legacy.commit()
    legacy.close()

    with open(old, "rb") as f:
        res = client.post("/backup/restore", data={"backup": (f, "old.db")},
                          content_type="multipart/form-data")
    assert "message=" in res.headers["Location"]
    assert client.get("/pensions").status_code == 200
    assert client.get("/reports").status_code == 200


# --------------------------------------------------------------------------
# tax-year input validation (pensions page, tax-year export)
# --------------------------------------------------------------------------

@pytest.mark.parametrize("ty", ["abc", "1999", "99999999"])
def test_pensions_page_rejects_a_bad_tax_year(client, ty):
    res = client.get(f"/pensions?ty={ty}")
    assert res.status_code == 302 and "error=" in res.headers["Location"]
    assert "is not a valid tax year" in client.get(res.headers["Location"]).get_data(as_text=True)


@pytest.mark.parametrize("ty", ["abc", "1999", "99999999"])
def test_tax_year_csv_rejects_a_bad_tax_year(client, ty):
    res = client.get(f"/export/tax-year.csv?ty={ty}")
    assert res.status_code == 302 and "/export?" in res.headers["Location"]
    page = client.get(res.headers["Location"])
    assert page.status_code == 200 and "is not a valid tax year" in page.get_data(as_text=True)


def test_tax_year_csv_defaults_to_the_current_year_when_empty(client):
    current = finance.tax_year_of(date.today())
    res = client.get("/export/tax-year.csv?ty=")
    assert res.status_code == 200
    assert f"tax-year_{current}-{current + 1}.csv" in res.headers["Content-Disposition"]


# --------------------------------------------------------------------------
# help text shows the configured rate, formatted as a percentage
# --------------------------------------------------------------------------

@pytest.mark.parametrize("value, shown", [
    ("0.20", "20%"), ("0.2", "20%"), ("0.25", "25%"), ("0.205", "20.5%"), ("0", "0%"),
    (Decimal("0.20"), "20%"), ("garbage", "garbage"),
])
def test_rate_pct_filter(value, shown):
    import app as app_module
    assert app_module.rate_pct_filter(value) == shown


def test_help_text_shows_the_configured_rate(client, conn):
    html = client.get("/pensions").get_data(as_text=True)
    assert "configured relief-at-source" in html and "(currently 20%)" in html
    assert "20.00%" not in html

    import db as db_module
    db_module.save_setting(conn, pensions.RELIEF_RATE_SETTING_KEY, "0.25")
    html = client.get("/pensions").get_data(as_text=True)
    assert "(currently 25%)" in html and "20%" not in html


def test_edit_page_shows_the_rows_own_rate_as_a_percentage(client, conn):
    import db as db_module
    add_pension(client, "80", "2026-06-01")
    db_module.save_setting(conn, pensions.RELIEF_RATE_SETTING_KEY, "0.25")
    (row,) = all_rows(conn)
    text = " ".join(client.get(f"/pensions/{row['id']}/edit").get_data(as_text=True).split())
    assert "at a 20% relief rate (kept from when it was recorded)" in text
    assert "0.20 relief rate" not in text
