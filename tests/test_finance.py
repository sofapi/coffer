"""Metric arithmetic, period windows and the double-counting guards.

The definitions these assert against are written out in finance.py's module
docstring; if a number here changes, that docstring must change with it.
"""

from datetime import date

import pytest

import finance

# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------

def add_customer(conn, name="Test Customer"):
    cur = conn.execute("INSERT INTO customers (name) VALUES (?)", (name,))
    conn.commit()
    return cur.lastrowid


def add_invoice(conn, customer_id, issue_date, lines, status="unpaid", due_date=""):
    """Create an invoice with N line items. Multiple lines is the default case
    on purpose — it is what a row-multiplying JOIN gets wrong."""
    number = f"INV-{conn.execute('SELECT COUNT(*) c FROM invoices').fetchone()['c'] + 1:04d}"
    cur = conn.execute(
        "INSERT INTO invoices (invoice_number, customer_id, date, due_date, status) "
        "VALUES (?,?,?,?,?)",
        (number, customer_id, issue_date, due_date, status),
    )
    inv_id = cur.lastrowid
    for amount in lines:
        conn.execute(
            "INSERT INTO invoice_lines (invoice_id, description, amount) VALUES (?,?,?)",
            (inv_id, "line", amount),
        )
    conn.commit()
    return inv_id


def add_income(conn, amount, when):
    conn.execute("INSERT INTO income (amount, date) VALUES (?,?)", (amount, when))
    conn.commit()


def add_expense(conn, amount, when, category=""):
    conn.execute(
        "INSERT INTO expenses (amount, date, category) VALUES (?,?,?)",
        (amount, when, category),
    )
    conn.commit()


# --------------------------------------------------------------------------
# period resolution
# --------------------------------------------------------------------------

def test_six_month_window_includes_current_month():
    w = finance.resolve_period("6m", today=date(2026, 8, 16))
    assert w["months"] == ["2026-03", "2026-04", "2026-05", "2026-06", "2026-07", "2026-08"]
    assert w["start"] == "2026-03-01"
    assert w["end"] == "2026-09-01"


def test_twelve_month_window_spans_a_year():
    w = finance.resolve_period("12m", today=date(2026, 8, 16))
    assert len(w["months"]) == 12
    assert w["months"][0] == "2025-09"
    assert w["months"][-1] == "2026-08"


def test_ytd_window_starts_in_january():
    w = finance.resolve_period("ytd", today=date(2026, 3, 9))
    assert w["months"] == ["2026-01", "2026-02", "2026-03"]
    assert w["label"] == "2026 year to date"


def test_custom_window_snaps_to_whole_months():
    w = finance.resolve_period("custom", "2026-02-14", "2026-04-03", today=date(2026, 8, 16))
    assert w["months"] == ["2026-02", "2026-03", "2026-04"]
    assert w["start"] == "2026-02-01"
    assert w["end"] == "2026-05-01"


@pytest.mark.parametrize("bad", [
    ("custom", "not-a-date", "2026-04-03"),
    ("custom", "2026-04-03", "2026-02-01"),   # end before start
    ("custom", "", ""),
    ("nonsense", "", ""),
])
def test_unparseable_periods_fall_back_to_twelve_months(bad):
    w = finance.resolve_period(*bad, today=date(2026, 8, 16))
    assert w["period"] == "12m"
    assert len(w["months"]) == 12


def test_preceding_window_is_the_same_length_and_immediately_before():
    w = finance.resolve_period("6m", today=date(2026, 8, 16))
    assert w["prev_end"] == w["start"]
    assert w["prev_start"] == "2025-09-01"
    assert len(finance.month_range(date(2025, 9, 1), date(2026, 3, 1))) == 6


def test_add_months_clamps_to_shorter_months():
    assert finance.add_months(date(2026, 1, 31), 1) == date(2026, 2, 28)
    assert finance.add_months(date(2026, 3, 31), -1) == date(2026, 2, 28)
    assert finance.add_months(date(2026, 1, 15), -1) == date(2025, 12, 15)


# --------------------------------------------------------------------------
# totals
# --------------------------------------------------------------------------

def test_invoiced_counts_every_status_once(conn):
    cid = add_customer(conn)
    add_invoice(conn, cid, "2026-05-04", [100.0, 50.0], status="unpaid")
    add_invoice(conn, cid, "2026-05-19", [200.0], status="paid")
    totals = finance.period_totals(conn, "2026-05-01", "2026-06-01")
    assert totals["invoiced"] == 350.0
    assert totals["invoice_count"] == 2


def test_multi_line_invoice_is_not_multiplied(conn):
    """A naive JOIN would report three invoices and treble nothing useful."""
    cid = add_customer(conn)
    add_invoice(conn, cid, "2026-05-04", [10.0, 20.0, 30.0], status="unpaid")
    totals = finance.period_totals(conn, "2026-05-01", "2026-06-01")
    assert totals["invoiced"] == 60.0
    assert totals["invoice_count"] == 1
    owed = finance.outstanding(conn, today=date(2026, 6, 1))
    assert owed["count"] == 1
    assert owed["total"] == 60.0


def test_invoice_with_no_lines_contributes_zero(conn):
    cid = add_customer(conn)
    add_invoice(conn, cid, "2026-05-04", [], status="unpaid")
    totals = finance.period_totals(conn, "2026-05-01", "2026-06-01")
    assert totals["invoiced"] == 0.0
    assert totals["invoice_count"] == 1
    assert finance.outstanding(conn, today=date(2026, 6, 1))["count"] == 1


def test_revenue_is_income_entries_plus_paid_invoices(conn):
    cid = add_customer(conn)
    add_invoice(conn, cid, "2026-05-04", [400.0], status="paid")
    add_invoice(conn, cid, "2026-05-06", [900.0], status="unpaid")
    add_income(conn, 100.0, "2026-05-10")
    totals = finance.period_totals(conn, "2026-05-01", "2026-06-01")
    assert totals["revenue"] == 500.0
    assert totals["paid_invoices"] == 400.0
    assert totals["income_entries"] == 100.0
    # Unpaid value shows up in INVOICED, never in REVENUE.
    assert totals["invoiced"] == 1300.0


def test_net_is_revenue_minus_costs_and_margin_follows(conn):
    cid = add_customer(conn)
    add_invoice(conn, cid, "2026-05-04", [1000.0], status="paid")
    add_expense(conn, 250.0, "2026-05-08")
    totals = finance.period_totals(conn, "2026-05-01", "2026-06-01")
    assert totals["costs"] == 250.0
    assert totals["net"] == 750.0
    assert totals["margin"] == pytest.approx(0.75)


def test_margin_is_undefined_without_revenue(conn):
    add_expense(conn, 250.0, "2026-05-08")
    totals = finance.period_totals(conn, "2026-05-01", "2026-06-01")
    assert totals["revenue"] == 0.0
    assert totals["net"] == -250.0
    assert totals["margin"] is None, "a costs-only month has no margin, not a 0% one"


def test_period_boundaries_are_half_open(conn):
    cid = add_customer(conn)
    add_invoice(conn, cid, "2026-04-30", [10.0], status="paid")
    add_invoice(conn, cid, "2026-05-01", [20.0], status="paid")
    add_invoice(conn, cid, "2026-06-01", [40.0], status="paid")
    totals = finance.period_totals(conn, "2026-05-01", "2026-06-01")
    assert totals["revenue"] == 20.0


# --------------------------------------------------------------------------
# outstanding / overdue
# --------------------------------------------------------------------------

def test_overdue_is_a_subset_of_outstanding(conn):
    cid = add_customer(conn)
    add_invoice(conn, cid, "2026-01-05", [300.0], status="unpaid", due_date="2026-02-04")
    add_invoice(conn, cid, "2026-07-05", [200.0], status="unpaid", due_date="2026-09-04")
    owed = finance.outstanding(conn, today=date(2026, 8, 16))
    assert owed["total"] == 500.0
    assert owed["count"] == 2
    assert owed["overdue_total"] == 300.0
    assert owed["overdue_count"] == 1
    assert owed["overdue_total"] <= owed["total"]


def test_invoice_without_a_due_date_is_never_overdue(conn):
    cid = add_customer(conn)
    add_invoice(conn, cid, "2020-01-05", [300.0], status="unpaid", due_date="")
    owed = finance.outstanding(conn, today=date(2026, 8, 16))
    assert owed["total"] == 300.0
    assert owed["overdue_total"] == 0.0


def test_paid_invoices_are_not_outstanding(conn):
    cid = add_customer(conn)
    add_invoice(conn, cid, "2026-01-05", [300.0], status="paid", due_date="2026-02-04")
    assert finance.outstanding(conn, today=date(2026, 8, 16))["total"] == 0.0


def test_outstanding_ignores_the_selected_period(conn):
    """Money owed does not stop being owed because the chart shows six months."""
    cid = add_customer(conn)
    add_invoice(conn, cid, "2019-01-05", [300.0], status="unpaid")
    data = finance.build_dashboard(conn, "6m", today=date(2026, 8, 16))
    assert data["totals"]["invoiced"] == 0.0
    assert data["outstanding"]["total"] == 300.0


# --------------------------------------------------------------------------
# monthly series
# --------------------------------------------------------------------------

def test_series_has_one_point_per_month_including_empty_ones(conn):
    cid = add_customer(conn)
    add_invoice(conn, cid, "2026-06-10", [600.0], status="paid")
    data = finance.build_dashboard(conn, "6m", today=date(2026, 8, 16))
    assert [p["month"] for p in data["series"]] == \
        ["2026-03", "2026-04", "2026-05", "2026-06", "2026-07", "2026-08"]
    june = next(p for p in data["series"] if p["month"] == "2026-06")
    assert june["revenue"] == 600.0
    assert all(p["revenue"] == 0 for p in data["series"] if p["month"] != "2026-06")


def test_series_net_matches_revenue_minus_costs_per_month(conn):
    cid = add_customer(conn)
    add_invoice(conn, cid, "2026-07-02", [800.0], status="paid")
    add_expense(conn, 300.0, "2026-07-20")
    data = finance.build_dashboard(conn, "6m", today=date(2026, 8, 16))
    july = next(p for p in data["series"] if p["month"] == "2026-07")
    assert july["revenue"] == 800.0
    assert july["costs"] == 300.0
    assert july["net"] == 500.0


def test_series_totals_reconcile_with_period_totals(conn):
    cid = add_customer(conn)
    add_invoice(conn, cid, "2026-06-10", [600.0], status="paid")
    add_invoice(conn, cid, "2026-07-10", [150.0], status="unpaid")
    add_income(conn, 40.0, "2026-05-01")
    add_expense(conn, 90.0, "2026-08-01")
    data = finance.build_dashboard(conn, "6m", today=date(2026, 8, 16))
    for key in ("invoiced", "revenue", "costs", "net"):
        assert sum(p[key] for p in data["series"]) == pytest.approx(data["totals"][key]), key


def test_month_label_formatting():
    assert finance.month_label("2026-03") == "Mar 2026"
    assert finance.month_label("2025-12") == "Dec 2025"


# --------------------------------------------------------------------------
# comparison vs preceding period
# --------------------------------------------------------------------------

def test_comparison_uses_the_immediately_preceding_window(conn):
    cid = add_customer(conn)
    add_invoice(conn, cid, "2026-07-10", [1200.0], status="paid")   # in period
    add_invoice(conn, cid, "2026-01-10", [600.0], status="paid")    # in prior period
    data = finance.build_dashboard(conn, "6m", today=date(2026, 8, 16))
    rev = data["comparison"]["revenue"]
    assert rev["current"] == 1200.0
    assert rev["previous"] == 600.0
    assert rev["delta"] == 600.0
    assert rev["pct"] == pytest.approx(1.0)


def test_percentage_change_from_zero_is_undefined_not_infinite():
    assert finance.pct_change(500.0, 0.0) is None
    assert finance.pct_change(0.0, 0.0) is None
    assert finance.pct_change(0.0, 500.0) == pytest.approx(-1.0)


def test_percentage_change_against_a_negative_baseline_uses_magnitude():
    # -100 -> +50 is an improvement of 150 on a base of 100.
    assert finance.pct_change(50.0, -100.0) == pytest.approx(1.5)


def test_margin_comparison_is_absent_when_either_side_has_no_revenue(conn):
    cid = add_customer(conn)
    add_invoice(conn, cid, "2026-07-10", [1000.0], status="paid")
    data = finance.build_dashboard(conn, "6m", today=date(2026, 8, 16))
    assert data["comparison"]["margin"]["current"] is not None
    assert data["comparison"]["margin"]["previous"] is None
    assert data["comparison"]["margin"]["delta"] is None


def test_month_over_month_trend_compares_the_last_two_points(conn):
    cid = add_customer(conn)
    add_invoice(conn, cid, "2026-07-10", [1000.0], status="paid")
    add_invoice(conn, cid, "2026-08-10", [1500.0], status="paid")
    data = finance.build_dashboard(conn, "6m", today=date(2026, 8, 16))
    assert data["trend"]["month"] == "Aug 2026"
    assert data["trend"]["previous_month"] == "Jul 2026"
    assert data["trend"]["revenue_delta"] == 500.0
    assert data["trend"]["revenue"] == pytest.approx(0.5)


# --------------------------------------------------------------------------
# edge cases
# --------------------------------------------------------------------------

def test_empty_database_produces_a_usable_payload(conn):
    data = finance.build_dashboard(conn, "12m", today=date(2026, 8, 16))
    assert data["has_data"] is False
    assert len(data["series"]) == 12
    assert data["totals"]["net"] == 0.0
    assert data["totals"]["margin"] is None
    assert data["outstanding"]["total"] == 0.0


def test_negative_expense_does_not_crash_margin(conn):
    """Refunds are not modelled, but a user can key a negative expense."""
    cid = add_customer(conn)
    add_invoice(conn, cid, "2026-07-10", [100.0], status="paid")
    add_expense(conn, -40.0, "2026-07-11")
    totals = finance.period_totals(conn, "2026-07-01", "2026-08-01")
    assert totals["costs"] == -40.0
    assert totals["net"] == 140.0
    assert totals["margin"] == pytest.approx(1.4)


def test_rows_with_blank_dates_are_excluded_rather_than_crashing(conn):
    conn.execute("INSERT INTO income (amount, date) VALUES (?,?)", (99.0, ""))
    conn.commit()
    data = finance.build_dashboard(conn, "12m", today=date(2026, 8, 16))
    assert data["totals"]["revenue"] == 0.0


def test_single_month_custom_range_has_no_month_over_month_trend(conn):
    data = finance.build_dashboard(conn, "custom", "2026-05-01", "2026-05-31",
                                   today=date(2026, 8, 16))
    assert len(data["series"]) == 1
    assert data["trend"] is None


def test_has_data_is_true_when_only_an_old_unpaid_invoice_exists(conn):
    cid = add_customer(conn)
    add_invoice(conn, cid, "2019-01-05", [300.0], status="unpaid")
    data = finance.build_dashboard(conn, "6m", today=date(2026, 8, 16))
    assert data["has_data"] is True


# --------------------------------------------------------------------------
# tax-year parsing
# --------------------------------------------------------------------------

@pytest.mark.parametrize("value, expected", [
    ("2026", 2026), (" 2026 ", 2026), ("2000", 2000), ("2027", 2027),
    ("", None), (None, None), ("abc", None), ("-1", None), ("2026.0", None),
    ("1999", None), ("2028", None), ("99999999", None), ("０２０２６", None),
])
def test_parse_tax_year(value, expected):
    assert finance.parse_tax_year(value, today=date(2026, 10, 23)) == expected
