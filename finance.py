"""Financial aggregation for Coffer's dashboard, with explicit definitions.

WHAT COFFER ACTUALLY STORES (see `db.py`)
-----------------------------------------
    income        (amount, date, reference)              money received, logged by hand
    expenses      (amount, date, reference, category)    money paid out, logged by hand
    invoices      (date, due_date, status)               status is 'unpaid' or 'paid'
    invoice_lines (amount, hours, rate)                  invoice value = SUM(amount)

WHAT COFFER DOES NOT STORE, AND THEREFORE IS NEVER INFERRED
-----------------------------------------------------------
    * Draft / sent / void / refunded invoice states. The only states in the
      schema are 'unpaid' and 'paid'. "Overdue" is not stored either — it is
      *derived* (unpaid AND due_date set AND due_date < today) and is a view of
      an unpaid invoice, never an extra invoice.
    * Payment dates. A paid invoice records when it was *issued*, not when the
      money arrived, so cash-basis revenue is approximated at the issue date.
    * Tax (VAT), discounts, credit notes and refunds. Line amounts are taken at
      face value; no tax is added or removed anywhere.
    * Cost of goods sold. `expenses` is a flat list of business outgoings, not
      cost of sales, so Coffer CANNOT compute gross profit or a true margin.
      The dashboard therefore reports "Net" (revenue minus recorded costs) and
      says so in the UI. See NET below.
    * Currency. Coffer is single-currency; the symbol is a display concern and
      is threaded through `CURRENCY_SYMBOL` so a per-user currency can be added
      later without touching the arithmetic.

METRIC DEFINITIONS
------------------
For a period [start, end) — start inclusive, end exclusive, both 'YYYY-MM-DD':

    INVOICED  = SUM(invoice_lines.amount)
                over invoices with issue date in the period, ALL statuses.
                Accrual view: what was billed. Each line counted exactly once.

    REVENUE   = SUM(income.amount) with date in the period
              + SUM(invoice_lines.amount) over invoices with status='paid'
                and issue date in the period.
                Approximate cash-in view. This matches what Coffer's Reports
                page and CSV export have always called income, so the dashboard
                does not contradict the rest of the app.

    COSTS     = SUM(expenses.amount) with date in the period.

    NET       = REVENUE - COSTS.
                NOT gross profit and NOT net profit in an accounting sense:
                there is no cost of sales, no tax and no depreciation in the
                data. It is money recorded in minus money recorded out.

    MARGIN    = NET / REVENUE, only when REVENUE > 0; otherwise undefined
                (rendered as an em dash, never as 0%).

    OUTSTANDING = SUM(invoice_lines.amount) over ALL invoices with
                status='unpaid', regardless of period. It is a balance as at
                today, not a flow through the period, so applying the period
                filter to it would be wrong.
    OVERDUE     = the subset of OUTSTANDING whose due_date is set and earlier
                than today. A subset, never added to OUTSTANDING.

    CHANGE vs PRECEDING PERIOD = the same metric recomputed over the period of
                identical length immediately before the selected one.

DOUBLE-COUNTING RULES
---------------------
    * Invoice values are always summed from a per-invoice aggregate subquery,
      never from a row-multiplying JOIN. (A naive
      `COUNT(*) ... FROM invoices JOIN invoice_lines` counts line items, not
      invoices — this module exists partly to stop that.)
    * INVOICED and REVENUE are separate series and are never added together;
      a paid invoice appears in both, because they answer different questions.
    * `income` rows and `invoices` are separate ledgers and Coffer has no way to
      link them. If a user records an invoice payment as an income entry *as
      well as* marking the invoice paid, it is counted twice. The dashboard
      states this in the UI rather than silently guessing.
"""

import re
from calendar import monthrange
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

_ONE_DAY = timedelta(days=1)

CURRENCY_SYMBOL = "£"
CURRENCY_CODE = "GBP"

# Per-invoice totals. Used everywhere an invoice value is needed so that no
# query ever multiplies invoice rows by their line count.
INVOICE_TOTALS = (
    "(SELECT invoice_id, SUM(amount) AS total FROM invoice_lines GROUP BY invoice_id)"
)

PERIODS = [
    {"value": "6m", "label": "6 months"},
    {"value": "12m", "label": "12 months"},
    {"value": "ytd", "label": "Year to date"},
    {"value": "custom", "label": "Custom range"},
]


# ---------------------------------------------------------------------------
# Period helpers
# ---------------------------------------------------------------------------

def month_key(d: date) -> str:
    return d.strftime("%Y-%m")


def add_months(d: date, n: int) -> date:
    """Shift a date by n months, clamping the day to the target month's length."""
    total = d.year * 12 + (d.month - 1) + n
    year, month = divmod(total, 12)
    month += 1
    return date(year, month, min(d.day, monthrange(year, month)[1]))


def month_start(d: date) -> date:
    return d.replace(day=1)


def month_range(start: date, end_exclusive: date) -> list[str]:
    """Every 'YYYY-MM' from start's month up to (not including) end's month.

    Months with no data still appear, so the chart shows a real gap rather than
    silently compressing the timeline.
    """
    keys: list[str] = []
    cur = month_start(start)
    last = month_start(end_exclusive - _ONE_DAY) if end_exclusive > start else cur
    while cur <= last:
        keys.append(month_key(cur))
        cur = add_months(cur, 1)
    return keys


# ---------------------------------------------------------------------------
# Money input
# ---------------------------------------------------------------------------
# Every amount typed into Coffer goes through parse_money before it is stored.
# Only the plain form an <input type="number"> sends is accepted: digits, an
# optional leading minus, and at most two decimal places ("1200", "1200.00",
# ".5"). Anything else is rejected with a message rather than guessed at —
# "1,200" might mean 1200 or 1.2, and SQLite would otherwise store it as text
# and SUM() it as 1. Parsing is Decimal; callers convert to the column's type.

PENNY = Decimal("0.01")
MAX_AMOUNT = Decimal("10000000")  # typo guard, not a business rule
_PLAIN_NUMBER = re.compile(r"-?(?:[0-9]+(?:\.[0-9]{1,2})?|\.[0-9]{1,2})")


class MoneyError(ValueError):
    """User-facing validation failure; the message is shown in the UI."""


def parse_money(value, label: str = "Amount", *, required: bool = True,
                allow_negative: bool = False) -> Decimal:
    """User input -> Decimal with at most 2 dp, or MoneyError.

    An empty value is an error when `required`, otherwise Decimal("0").
    """
    text = "" if value is None else str(value).strip()
    if not text:
        if required:
            raise MoneyError(f"{label} is required.")
        return Decimal("0")
    if "," in text:
        raise MoneyError(f"{label}: enter numbers without commas, e.g. 1200.00.")
    if not _PLAIN_NUMBER.fullmatch(text):
        if re.fullmatch(r"-?[0-9]*\.[0-9]{3,}", text):
            raise MoneyError(f"{label} cannot have more than two decimal places.")
        raise MoneyError(f"{label} must be a number, e.g. 1200.00.")
    amount = Decimal(text)
    if amount < 0 and not allow_negative:
        raise MoneyError(f"{label} cannot be negative.")
    if abs(amount) >= MAX_AMOUNT:
        raise MoneyError(f"{label} is too large.")
    return amount


def round_money(amount: Decimal) -> Decimal:
    """Half-up to the penny — how a person rounds, unlike float round()."""
    return amount.quantize(PENNY, rounding=ROUND_HALF_UP)


def parse_iso(value: str) -> date | None:
    try:
        return date.fromisoformat((value or "").strip())
    except (ValueError, TypeError):
        return None


def resolve_period(period: str, custom_from: str = "", custom_to: str = "",
                   today: date | None = None) -> dict:
    """Turn the UI's period choice into a concrete half-open month window.

    Returns start (inclusive) and end (exclusive) dates aligned to month
    boundaries, plus the equivalent preceding window used for comparison.
    Falls back to 12 months for anything unrecognised or unparseable, so a
    hand-edited query string can never 500 the dashboard.
    """
    today = today or date.today()
    this_month = month_start(today)
    next_month = add_months(this_month, 1)

    if period == "custom":
        start = parse_iso(custom_from)
        end = parse_iso(custom_to)
        if start and end and end >= start:
            start = month_start(start)
            end_exclusive = add_months(month_start(end), 1)
            label = "Custom range"
        else:
            period, start, end_exclusive = "12m", add_months(this_month, -11), next_month
            label = "Last 12 months"
    elif period == "6m":
        start, end_exclusive = add_months(this_month, -5), next_month
        label = "Last 6 months"
    elif period == "ytd":
        start, end_exclusive = date(today.year, 1, 1), next_month
        label = f"{today.year} year to date"
    else:
        period = "12m"
        start, end_exclusive = add_months(this_month, -11), next_month
        label = "Last 12 months"

    months = month_range(start, end_exclusive)
    prev_start = add_months(start, -len(months))
    return {
        "period": period,
        "label": label,
        "start": start.isoformat(),
        "end": end_exclusive.isoformat(),
        "months": months,
        "prev_start": prev_start.isoformat(),
        "prev_end": start.isoformat(),
        "month_count": len(months),
    }


# ---------------------------------------------------------------------------
# UK tax years
# ---------------------------------------------------------------------------
# A UK tax year runs 6 April to 5 April and is named by the calendar year it
# starts in: 6 Apr 2026 -> 5 Apr 2027 is tax year 2026 ("2026/2027"). This is
# the one implementation of that rule; the Reports page and pensions use it.

def tax_year_of(d: date) -> int:
    """Start year of the tax year containing d. 5 April belongs to the year
    that is ending, 6 April to the one that is starting."""
    return d.year if d >= date(d.year, 4, 6) else d.year - 1


def tax_year_bounds(ty: int) -> tuple[str, str]:
    """Half-open [start, end) ISO dates for tax year `ty`."""
    return f"{ty}-04-06", f"{ty + 1}-04-06"


# Earliest tax year Coffer accepts from a URL or form. Anything outside
# [MIN_TAX_YEAR, current + 1] is a typo or a hand-edited URL, not a real year.
MIN_TAX_YEAR = 2000


def parse_tax_year(value, today: date | None = None) -> int | None:
    """A tax year from user input ('2026'), or None if it is not a plain
    number in the accepted range. Callers decide what None means for them."""
    text = (value or "").strip()
    if not text.isdigit() or len(text) != 4:
        return None
    ty = int(text)
    latest = tax_year_of(today or date.today()) + 1
    return ty if MIN_TAX_YEAR <= ty <= latest else None


def tax_year_label(ty: int) -> str:
    """2026 -> '2026/2027', matching the Reports page's tax-year picker."""
    return f"{ty}/{ty + 1}"


def month_label(key: str) -> str:
    """'2026-03' -> 'Mar 2026'."""
    year, month = key.split("-")
    return date(int(year), int(month), 1).strftime("%b %Y")


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------

def monthly_series(conn, start: str, end: str, months: list[str]) -> list[dict]:
    """Per-month INVOICED / REVENUE / COSTS / NET across [start, end)."""
    invoices = conn.execute(
        f"""SELECT substr(i.date, 1, 7) AS m,
                   COALESCE(SUM(COALESCE(t.total, 0)), 0) AS invoiced,
                   COALESCE(SUM(CASE WHEN i.status = 'paid'
                                     THEN COALESCE(t.total, 0) ELSE 0 END), 0) AS paid
            FROM invoices i
            LEFT JOIN {INVOICE_TOTALS} t ON t.invoice_id = i.id
            WHERE i.date >= ? AND i.date < ?
            GROUP BY m""",
        (start, end),
    ).fetchall()
    income = conn.execute(
        """SELECT substr(date, 1, 7) AS m, COALESCE(SUM(amount), 0) AS total
           FROM income WHERE date >= ? AND date < ? GROUP BY m""",
        (start, end),
    ).fetchall()
    expenses = conn.execute(
        """SELECT substr(date, 1, 7) AS m, COALESCE(SUM(amount), 0) AS total
           FROM expenses WHERE date >= ? AND date < ? GROUP BY m""",
        (start, end),
    ).fetchall()

    inv = {r["m"]: (r["invoiced"], r["paid"]) for r in invoices}
    inc = {r["m"]: r["total"] for r in income}
    exp = {r["m"]: r["total"] for r in expenses}

    series = []
    for key in months:
        invoiced, paid = inv.get(key, (0.0, 0.0))
        revenue = inc.get(key, 0.0) + paid
        costs = exp.get(key, 0.0)
        series.append({
            "month": key,
            "label": month_label(key),
            "invoiced": round(invoiced, 2),
            "revenue": round(revenue, 2),
            "costs": round(costs, 2),
            "net": round(revenue - costs, 2),
        })
    return series


def period_totals(conn, start: str, end: str) -> dict[str, float]:
    """INVOICED / REVENUE / COSTS / NET / MARGIN for a single window."""
    row = conn.execute(
        f"""SELECT COALESCE(SUM(COALESCE(t.total, 0)), 0) AS invoiced,
                   COALESCE(SUM(CASE WHEN i.status = 'paid'
                                     THEN COALESCE(t.total, 0) ELSE 0 END), 0) AS paid,
                   COUNT(*) AS invoice_count
            FROM invoices i
            LEFT JOIN {INVOICE_TOTALS} t ON t.invoice_id = i.id
            WHERE i.date >= ? AND i.date < ?""",
        (start, end),
    ).fetchone()
    income = conn.execute(
        "SELECT COALESCE(SUM(amount), 0) AS t FROM income WHERE date >= ? AND date < ?",
        (start, end),
    ).fetchone()["t"]
    costs = conn.execute(
        "SELECT COALESCE(SUM(amount), 0) AS t FROM expenses WHERE date >= ? AND date < ?",
        (start, end),
    ).fetchone()["t"]

    revenue = income + row["paid"]
    net = revenue - costs
    return {
        "invoiced": round(row["invoiced"], 2),
        "invoice_count": row["invoice_count"],
        "revenue": round(revenue, 2),
        "income_entries": round(income, 2),
        "paid_invoices": round(row["paid"], 2),
        "costs": round(costs, 2),
        "net": round(net, 2),
        "margin": (net / revenue) if revenue > 0 else None,
    }


def outstanding(conn, today: date | None = None) -> dict[str, float]:
    """Unpaid invoice balance as at today, plus its overdue subset.

    Point-in-time, deliberately not period-filtered: money owed does not stop
    being owed because the chart is showing six months.
    """
    today = (today or date.today()).isoformat()
    row = conn.execute(
        f"""SELECT COUNT(*) AS count,
                   COALESCE(SUM(COALESCE(t.total, 0)), 0) AS total,
                   COALESCE(SUM(CASE WHEN i.due_date != '' AND i.due_date < ?
                                     THEN COALESCE(t.total, 0) ELSE 0 END), 0) AS overdue_total,
                   COALESCE(SUM(CASE WHEN i.due_date != '' AND i.due_date < ?
                                     THEN 1 ELSE 0 END), 0) AS overdue_count
            FROM invoices i
            LEFT JOIN {INVOICE_TOTALS} t ON t.invoice_id = i.id
            WHERE i.status = 'unpaid'""",
        (today, today),
    ).fetchone()
    return {
        "count": row["count"],
        "total": round(row["total"], 2),
        "overdue_count": row["overdue_count"],
        "overdue_total": round(row["overdue_total"], 2),
    }


def has_any_records(conn) -> bool:
    """True if the database holds a single invoice, income entry or expense.

    Cheap existence check (three EXISTS, no scans), not a count.
    """
    row = conn.execute(
        """SELECT EXISTS(SELECT 1 FROM invoices)
                + EXISTS(SELECT 1 FROM income)
                + EXISTS(SELECT 1 FROM expenses) AS n"""
    ).fetchone()
    return row["n"] > 0


def pct_change(current: float, previous: float) -> float | None:
    """Relative change, or None when it would be meaningless.

    A change from zero has no percentage — reporting "+100%" there would imply
    precision the data does not have — so it returns None and the UI shows the
    absolute movement instead.
    """
    if previous == 0:
        return None
    return (current - previous) / abs(previous)


def build_dashboard(conn, period: str = "12m", custom_from: str = "",
                    custom_to: str = "", today: date | None = None) -> dict:
    """Everything the dashboard chart and summary tiles need, in one payload."""
    today = today or date.today()
    window = resolve_period(period, custom_from, custom_to, today)

    series = monthly_series(conn, window["start"], window["end"], window["months"])
    totals = period_totals(conn, window["start"], window["end"])
    previous = period_totals(conn, window["prev_start"], window["prev_end"])
    owed = outstanding(conn, today)

    # Month-over-month uses the last two *complete-enough* points we have: the
    # final month in the window and the one before it. With a single month in
    # the window there is nothing to compare, so it stays None.
    trend = None
    if len(series) >= 2:
        last, prior = series[-1], series[-2]
        trend = {
            "month": last["label"],
            "previous_month": prior["label"],
            "revenue": pct_change(last["revenue"], prior["revenue"]),
            "costs": pct_change(last["costs"], prior["costs"]),
            "net": pct_change(last["net"], prior["net"]),
            "revenue_delta": round(last["revenue"] - prior["revenue"], 2),
            "costs_delta": round(last["costs"] - prior["costs"], 2),
            "net_delta": round(last["net"] - prior["net"], 2),
        }

    comparison = {
        key: {
            "current": totals[key],
            "previous": previous[key],
            "delta": round(totals[key] - previous[key], 2),
            "pct": pct_change(totals[key], previous[key]),
        }
        for key in ("invoiced", "revenue", "costs", "net")
    }
    comparison["margin"] = {
        "current": totals["margin"],
        "previous": previous["margin"],
        "delta": (
            round(totals["margin"] - previous["margin"], 4)
            if totals["margin"] is not None and previous["margin"] is not None
            else None
        ),
        "pct": None,
    }

    # Whether this install has ANY financial records, deliberately ignoring the
    # selected window: it is what lets the UI tell "you haven't added anything
    # yet" apart from "nothing landed in these months", and those need different
    # advice. A window-scoped flag cannot distinguish them.
    has_data = has_any_records(conn)

    return {
        "window": window,
        "series": series,
        "totals": totals,
        "previous": previous,
        "comparison": comparison,
        "outstanding": owed,
        "trend": trend,
        "has_data": has_data,
        "currency": {"symbol": CURRENCY_SYMBOL, "code": CURRENCY_CODE},
        "generated_at": today.isoformat(),
    }
