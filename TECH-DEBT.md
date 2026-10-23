# Technical debt

Known issues that are deliberately **not** fixed yet, with enough detail to
plan the work. Nothing here is a data-loss bug today; each item is a source of
small inaccuracies or a risk that grows with the data.

---

## 1. Legacy money columns use binary floating point

Pension contributions (`pension_contributions.net_pence`) are stored as integer
pence and calculated with `Decimal` — see `pensions.py`. Everything older is
not. Converting it is a migration, validation and reconciliation project in its
own right and must not be bundled with feature work.

### Where floats are stored

| Table | Column | Type | Meaning |
|-------|--------|------|---------|
| `income` | `amount` | `REAL NOT NULL` | Money received, pounds |
| `expenses` | `amount` | `REAL NOT NULL` | Money paid out, pounds |
| `invoice_lines` | `amount` | `REAL NOT NULL` | Line value, pounds |
| `invoice_lines` | `hours` | `REAL DEFAULT 0` | Quantity (not money, but multiplied into `amount`) |
| `invoice_lines` | `rate` | `REAL DEFAULT 0` | Price per hour, pounds |

`REAL` is an IEEE-754 double: `0.1 + 0.2` is stored and summed as
`0.30000000000000004`.

### How values are calculated today

- **Entry.** Every money input (`/income/add`, `/expenses/add`,
  `/invoices/<id>/add-line`, `/api/income`, `/api/expenses`, `/api/invoices`)
  is parsed with `finance.parse_money` (Decimal, at most 2 dp) and then
  converted with `float()` for the `REAL` column. A blank line amount is
  `hours * rate` in Decimal, rounded half-up to the penny. *Before* that
  validation was added, amounts were stored unparsed (text included) and the
  line product was stored unrounded (1.5 h × £33.33 = `49.995`) — existing
  databases may still hold such rows; `audit_money.py` lists them.
- **Aggregation.** `SUM(amount)` in SQLite (double arithmetic), then:
  - `finance.py` (dashboard) rounds each result with `round(x, 2)`;
  - the Reports page subtracts unrounded sums and formats with the `money`
    filter (`f"{x:,.2f}"`);
  - CSV exports format each row with `f"{x:.2f}"`;
  - invoice totals are `sum()` in Python (`invoice_detail`,
    `api_invoice_detail`) and `total += amount` in `pdf_gen.py`.
- **Display.** Every surface formats to 2 dp at the last moment, so most
  representation error is invisible.

### Rounding exposure

1. **Accumulated error in sums.** Each value carries up to ~1e-16 relative
   error; sums of thousands of rows stay far below half a penny, so totals are
   very unlikely to be wrong by a displayed penny today. Low risk, but unproven.
2. **Half-penny boundaries.** Python's `round()` and `:.2f` round the binary
   value, not the decimal one: `round(2.675, 2)` → `2.67` and `f"{1.005:.2f}"`
   → `1.00`. A value that is genuinely `x.xx5` (from `hours * rate`) can round
   down where a person would round up. **Real exposure:** unrounded invoice
   lines.
3. **Inconsistent rounding points.** The dashboard rounds per total, the Reports
   page rounds only at display, CSV rounds per row. With unrounded line amounts
   a CSV's rows can sum to a penny different from the Reports total.
4. **Line total vs PDF.** A PDF prints each line rounded and a total of the
   unrounded values, so the printed lines may not add up to the printed total.
5. **Rows stored before validation (separate, worse).** Amounts used to be
   stored unparsed, so a non-numeric value was kept as TEXT (SQLite type
   affinity) and `SUM` coerces it: `'abc'` counts as `0`, and `'1,200'` counts
   as **`1`**. New entry is now validated (§2), but existing rows are not
   changed; run `audit_money.py` against a backup to find any.

### Migration that would eventually be required

Target: `amount_pence INTEGER NOT NULL` on `income`, `expenses`,
`invoice_lines`; `rate_pence INTEGER` on `invoice_lines`; `hours` either kept as
`REAL` (it is a quantity) or stored as integer hundredths. All arithmetic in
`Decimal` or integer pence, with one documented rounding rule (half-up) applied
at one documented point (when a line amount is created).

Steps:

1. ~~**Fix input validation first** (§2) so no new bad rows appear.~~ Done for
   money values.
2. **Audit existing data** with `audit_money.py` (text/NULL/BLOB values,
   non-finite values, sub-penny values, now-prohibited negatives). Each finding
   needs a human decision before conversion; the migration must refuse to run
   while any remain unresolved.
3. **Additive schema change.** Add the new `*_pence` columns alongside the old
   ones (SQLite `ALTER TABLE ... ADD COLUMN` is safe and instant). Do not drop
   or rewrite the `REAL` columns in the same release.
4. **Backfill** `amount_pence = CAST(ROUND(amount * 100) AS INTEGER)` — but do
   the rounding in Python with `Decimal(repr(amount)).quantize(Decimal('0.01'),
   ROUND_HALF_UP)` so the `x.xx5` cases round as a person expects, and log every
   row whose value changed by the rounding.
5. **Switch reads** to the pence columns; keep writing both for one release so
   a rollback to the previous image still sees correct `REAL` values.
6. **Later release:** stop writing the `REAL` columns. Only drop them (table
   rebuild in SQLite) once no supported image reads them.

Rollback at every step is "run the previous image": the old columns stay
authoritative until step 5 ships, and remain populated until step 6.

### Proving before/after totals are identical

Run on a **copy** of the production database (from **Backup → Download
backup**), never the live file:

1. Before migrating, capture a reconciliation snapshot: for each table, row
   count; `SUM(amount)`; per-row values formatted to 2 dp; and, for each UK tax
   year and each calendar month, the totals the app currently shows (Reports
   income / expenses / profit, dashboard revenue / costs / net, outstanding
   balance, every invoice total, every CSV export).
2. Migrate the copy.
3. Recompute the same snapshot from the new pence columns.
4. Assert: identical row counts and ids; every row's 2 dp value equal to its
   pence value; every period total equal to the penny; every invoice total and
   CSV byte-for-byte identical apart from rows flagged in step 2 of the
   migration. Any difference must be explained by a logged rounding decision.
5. Keep the snapshot and diff report alongside the release as the audit trail,
   and add the reconciliation script as an automated test against a synthetic
   database containing the known edge cases (`x.xx5` values, `0.1 + 0.2`, large
   sums, negative expenses, text-typed amounts).

---

## 2. Income, expense and invoice input validation — partly done

**Money values: done.** All six routes that store an amount, rate or hours
validate with `finance.parse_money` and reject malformed input with the normal
error alert (forms) or a `400 {"error": ...}` (API), writing nothing. Rules:
plain digits with at most two decimal places; no commas, symbols, exponents,
NaN or Infinity; only expenses may be negative (the existing refund stand-in);
under £10,000,000. Values stored before this change are reported by
`audit_money.py`; they are not altered.

**Still open — other fields on the same routes:**
- Dates are not validated: a malformed date is stored and then falls outside
  every date-range query (forms and API).
- A missing required non-money field (`date`, `description`, `customer_id`)
  returns a 400 from the form routes and a 500 (`KeyError`) from the API.
- `/invoices/<id>/status` accepts any string as a status.
- `/api/invoices` accepts a `customer_id` that does not exist (foreign keys
  are on, so this is a 500 rather than bad data).

Fix with the same pattern (validate, then redirect with `?error=` or return
400), with tests.
