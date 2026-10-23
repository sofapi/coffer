"""Read-only audit of money values in a Coffer database.

Finds income, expense and invoice-line values that SQLite has stored with an
unexpected type, or that cannot be read safely as money — the rows that
pre-date server-side validation (see TECH-DEBT.md §2). It changes nothing: the
database is opened with SQLite's read-only mode, so even an accidental write
would fail.

Run it against a COPY, never the live file. The simplest copy is
Backup -> Download backup in the app; or `docker compose stop`, copy
data/coffer.db, `docker compose start`.

Usage:
    python audit_money.py path/to/coffer-backup.db

Exit status: 0 = no findings, 1 = findings printed, 2 = could not read the file.
"""

import sqlite3
import sys
from decimal import Decimal, InvalidOperation
from pathlib import Path

from finance import MAX_AMOUNT, PENNY

# (table, column, label, negative values allowed?) — mirrors the entry rules in
# app.py: only expenses may be negative (the refund stand-in).
COLUMNS = [
    ("income", "amount", "amount", False),
    ("expenses", "amount", "amount", True),
    ("invoice_lines", "amount", "amount", False),
    ("invoice_lines", "rate", "rate", False),
    ("invoice_lines", "hours", "hours", False),
]


def problems(value, as_summed, allow_negative: bool) -> list[str]:
    """Why a stored value is not safely a money amount; empty if it is fine.

    `as_summed` is SQLite's own CAST(value AS REAL) — what SUM() and every
    report actually used for this row.
    """
    if value is None:
        return ["NULL (counted as 0)"]
    if isinstance(value, bytes):
        return [f"stored as a BLOB (counted as {as_summed!r})"]
    if isinstance(value, str):
        # SQLite keeps text that does not look numeric ("abc", "1,200") as
        # TEXT, and SUM() reads only its numeric prefix: "1,200" -> 1.
        return [f"stored as TEXT (counted as {as_summed!r})"]
    try:
        amount = Decimal(repr(value))
    except InvalidOperation:
        return ["not a number"]
    if not amount.is_finite():
        return ["not a finite number"]
    found = []
    if amount < 0 and not allow_negative:
        found.append("negative (now rejected on entry)")
    if amount != amount.quantize(PENNY):
        found.append("more than two decimal places")
    if abs(amount) >= MAX_AMOUNT:
        found.append(f"{MAX_AMOUNT:,} or more (now rejected on entry)")
    return found


def audit(conn) -> tuple[int, list[tuple]]:
    """(rows checked, [(table, id, column, value, reason), ...])."""
    checked, findings = 0, []
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    for table, column, label, allow_negative in COLUMNS:
        if table not in tables:
            continue
        query = f"SELECT id, {column}, CAST({column} AS REAL) FROM {table} ORDER BY id"
        for row_id, value, as_summed in conn.execute(query):
            checked += 1
            for reason in problems(value, as_summed, allow_negative):
                findings.append((table, row_id, label, value, reason))
    return checked, findings


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__.strip().split("Usage:")[1].split("Exit")[0].strip(), file=sys.stderr)
        return 2
    path = Path(argv[1])
    if not path.is_file():
        print(f"No such file: {path}", file=sys.stderr)
        return 2
    # A backup (Download backup, or a copy of a stopped install) has no -wal
    # file: open it immutable, which creates no -wal/-shm files at all. If a
    # -wal is present it holds committed data that must be read, so fall back
    # to read-only mode (SQLite may then create an empty -shm index file).
    wal = path.with_name(path.name + "-wal")
    mode = "mode=ro" if wal.exists() and wal.stat().st_size else "immutable=1"
    try:
        conn = sqlite3.connect(f"{path.resolve().as_uri()}?{mode}", uri=True)
        checked, findings = audit(conn)
        conn.close()
    except sqlite3.DatabaseError as exc:
        print(f"Could not read {path} as a Coffer database: {exc}", file=sys.stderr)
        return 2

    print(f"Checked {checked} stored values in {path.name} (read-only).")
    if not findings:
        print("No problems found: every income, expense and invoice-line value is a valid amount.")
        return 0
    print(f"{len(findings)} problem(s) found:\n")
    print(f"{'table':<14} {'id':>6}  {'column':<7} {'stored value':<20} problem")
    for table, row_id, label, value, reason in findings:
        print(f"{table:<14} {row_id:>6}  {label:<7} {value!r:<20} {reason}")
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
