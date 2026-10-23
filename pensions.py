"""Personal pension contributions, kept entirely apart from business expenses.

WHAT IS STORED (table `pension_contributions`, see `db.py`)
-----------------------------------------------------------
    date            'YYYY-MM-DD' the payment left the user's bank account
    net_pence       amount actually paid, in whole pence (never a float)
    relief_rate     decimal string, e.g. '0.20' — the basic-rate relief rate
                    the provider applied when this payment was recorded
    provider        pension provider / scheme name
    contribution_type   'regular' or 'single'
    relief_method   'relief_at_source' or 'no_relief_at_source'
    notes, created_at, updated_at

Only the source facts are stored. Relief and gross are *derived* from
(net_pence, relief_rate, relief_method) every time they are needed, so any
figure Coffer shows can be reproduced by hand from the row. The rate is stored
per row rather than read from settings at report time, so changing the setting
later never rewrites history. The tax year is derived from the date with
`finance.tax_year_of`, the same rule the Reports page uses.

CALCULATION
-----------
    RELIEF AT SOURCE (the normal personal pension / SIPP arrangement):
        GROSS  = NET / (1 - RATE), rounded half-up to the penny
        RELIEF = GROSS - NET
        e.g. at 20%: paid £800 -> gross £1,000, relief £200.
    The provider claims RELIEF from HMRC and adds it to the pension pot. It is
    not money refunded to the user.

    NO RELIEF AT SOURCE (e.g. a retirement annuity contract, or an employer
    scheme payment not taken from pay before tax): the amount paid IS the
    gross contribution and no relief is added. Any relief is claimed through
    the Self Assessment return, under a different box from relief at source.

Rounding is per payment, as providers credit relief per payment, and annual
totals are sums of the per-payment figures — so the totals always reconcile
with the rows beneath them.

NOT DONE HERE
-------------
Higher- and additional-rate relief, the annual allowance, tapering and carry
forward all depend on information Coffer does not hold (total taxable income,
other schemes, employer contributions). Coffer records and totals; it does not
compute a tax position.
"""

from datetime import date
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

import finance

RELIEF_AT_SOURCE = "relief_at_source"
NO_RELIEF_AT_SOURCE = "no_relief_at_source"

RELIEF_METHODS = {
    RELIEF_AT_SOURCE: "Relief at source (provider adds basic-rate relief)",
    NO_RELIEF_AT_SOURCE: "No relief at source (paid gross)",
}

CONTRIBUTION_TYPES = {
    "regular": "Regular",
    "single": "Single / lump sum",
}

# Settings key for the relief-at-source rate applied to NEW contributions.
# Existing rows keep the rate they were recorded with.
RELIEF_RATE_SETTING_KEY = "pension_relief_at_source_rate"
DEFAULT_RELIEF_RATE = "0.20"

_PENNY = finance.PENNY


class PensionError(ValueError):
    """User-facing validation failure; the message is shown in the UI."""


# ---------------------------------------------------------------------------
# Arithmetic (Decimal / integer pence only)
# ---------------------------------------------------------------------------

def parse_rate(value) -> Decimal:
    """A relief rate as a Decimal in [0, 1). Raises PensionError otherwise."""
    try:
        rate = Decimal(str(value).strip())
    except (InvalidOperation, ValueError) as exc:
        raise PensionError("Relief rate is not a number.") from exc
    if not rate.is_finite() or rate < 0 or rate >= 1:
        raise PensionError("Relief rate must be at least 0 and less than 1.")
    return rate


def configured_rate(settings: dict) -> Decimal:
    """The rate for new relief-at-source payments, from settings.

    A corrupt setting degrades to the standard rate rather than breaking the
    page, the same way an unknown palette falls back to the default.
    """
    try:
        return parse_rate(settings.get(RELIEF_RATE_SETTING_KEY, DEFAULT_RELIEF_RATE))
    except PensionError:
        return Decimal(DEFAULT_RELIEF_RATE)


def parse_amount_to_pence(value) -> int:
    """'800', '800.50' -> pence. Must be positive; formatting rules (no commas,
    at most 2 dp) are finance.parse_money's, shared with every other amount."""
    try:
        amount = finance.parse_money(value, "The amount paid")
    except finance.MoneyError as exc:
        raise PensionError(str(exc)) from exc
    if amount <= 0:
        raise PensionError("The amount paid must be more than zero.")
    return int(amount * 100)


def split_contribution(net_pence: int, relief_rate, relief_method: str) -> dict:
    """Net / relief / gross for one payment, all in pence."""
    if relief_method != RELIEF_AT_SOURCE:
        return {"net": net_pence, "relief": 0, "gross": net_pence}
    rate = parse_rate(relief_rate)
    gross = (Decimal(net_pence) / (1 - rate)).quantize(Decimal(1), rounding=ROUND_HALF_UP)
    gross = int(gross)
    return {"net": net_pence, "relief": gross - net_pence, "gross": gross}


def pence_to_decimal(pence: int) -> Decimal:
    return (Decimal(pence) / 100).quantize(_PENNY)


# ---------------------------------------------------------------------------
# Rows
# ---------------------------------------------------------------------------

def validate_form(form, settings: dict, existing=None) -> dict:
    """Clean a submitted add/edit form into column values.

    On edit, a relief-at-source row keeps the rate it was recorded with; a row
    switched *to* relief at source takes the currently configured rate.
    """
    when = finance.parse_iso(form.get("date", ""))
    if not when:
        raise PensionError("Enter the payment date.")
    method = form.get("relief_method", RELIEF_AT_SOURCE)
    if method not in RELIEF_METHODS:
        raise PensionError("Choose a tax relief method.")
    ctype = form.get("contribution_type", "regular")
    if ctype not in CONTRIBUTION_TYPES:
        raise PensionError("Choose a contribution type.")

    if method != RELIEF_AT_SOURCE:
        rate = "0"
    elif existing is not None and existing["relief_method"] == RELIEF_AT_SOURCE:
        rate = existing["relief_rate"]
    else:
        rate = str(configured_rate(settings))

    return {
        "date": when.isoformat(),
        "net_pence": parse_amount_to_pence(form.get("amount_paid")),
        "relief_rate": rate,
        "provider": (form.get("provider") or "").strip(),
        "contribution_type": ctype,
        "relief_method": method,
        "notes": (form.get("notes") or "").strip(),
    }


def insert(conn, values: dict) -> int:
    cur = conn.execute(
        """INSERT INTO pension_contributions
           (date, net_pence, relief_rate, provider, contribution_type, relief_method, notes)
           VALUES (:date, :net_pence, :relief_rate, :provider, :contribution_type,
                   :relief_method, :notes)""",
        values,
    )
    conn.commit()
    return cur.lastrowid


def update(conn, pension_id: int, values: dict) -> None:
    conn.execute(
        """UPDATE pension_contributions
           SET date = :date, net_pence = :net_pence, relief_rate = :relief_rate,
               provider = :provider, contribution_type = :contribution_type,
               relief_method = :relief_method, notes = :notes,
               updated_at = CURRENT_TIMESTAMP
           WHERE id = :id""",
        {**values, "id": pension_id},
    )
    conn.commit()


def delete(conn, pension_id: int) -> None:
    conn.execute("DELETE FROM pension_contributions WHERE id = ?", (pension_id,))
    conn.commit()


def get(conn, pension_id: int):
    return conn.execute(
        "SELECT * FROM pension_contributions WHERE id = ?", (pension_id,)
    ).fetchone()


def enrich(row) -> dict:
    """A stored row plus its derived figures (pence and Decimal pounds)."""
    item = dict(row)
    split = split_contribution(row["net_pence"], row["relief_rate"], row["relief_method"])
    item.update({
        "tax_year": finance.tax_year_of(date.fromisoformat(row["date"])),
        "net_pence": split["net"],
        "relief_pence": split["relief"],
        "gross_pence": split["gross"],
        "net": pence_to_decimal(split["net"]),
        "relief": pence_to_decimal(split["relief"]),
        "gross": pence_to_decimal(split["gross"]),
    })
    return item


def list_contributions(conn, start: str = "", end: str = "") -> list[dict]:
    """Contributions dated in [start, end) (either bound optional), oldest first."""
    q = "SELECT * FROM pension_contributions"
    clauses, params = [], []
    if start:
        clauses.append("date >= ?")
        params.append(start)
    if end:
        clauses.append("date < ?")
        params.append(end)
    if clauses:
        q += " WHERE " + " AND ".join(clauses)
    q += " ORDER BY date, id"
    return [enrich(r) for r in conn.execute(q, params).fetchall()]


def totals(items: list[dict]) -> dict:
    """Totals over enriched rows, split by relief method.

    `ras_gross` is the figure for the Self Assessment box for payments where
    basic-rate relief is claimed by the provider. `other_gross` is reported
    separately because it goes in a different box.
    """
    ras = [i for i in items if i["relief_method"] == RELIEF_AT_SOURCE]
    other = [i for i in items if i["relief_method"] != RELIEF_AT_SOURCE]
    pence = {
        "net": sum(i["net_pence"] for i in items),
        "relief": sum(i["relief_pence"] for i in items),
        "gross": sum(i["gross_pence"] for i in items),
        "ras_net": sum(i["net_pence"] for i in ras),
        "ras_relief": sum(i["relief_pence"] for i in ras),
        "ras_gross": sum(i["gross_pence"] for i in ras),
        "other_gross": sum(i["gross_pence"] for i in other),
    }
    result = {k: pence_to_decimal(v) for k, v in pence.items()}
    result["count"] = len(items)
    result["ras_count"] = len(ras)
    result["other_count"] = len(other)
    return result


def earliest_date(conn) -> str | None:
    return conn.execute("SELECT MIN(date) AS d FROM pension_contributions").fetchone()["d"]
