<div align="center">

# Coffer

### Simple finance tracking for the self-employed.

Invoices, income, expenses and reports for sole traders and small businesses —
self-hosted, single container, your data stays yours.

</div>

---

## What it is

Coffer is a lightweight, self-hosted finance tracker for small self-employed
businesses. It does the handful of things a sole trader actually needs, well:

- **Customers** — a simple contact book for who you bill.
- **Invoices** — numbered invoices with line items, generated as clean PDFs.
- **Income & expenses** — log what comes in and what goes out, with categories.
- **Dashboard** — monthly revenue, costs and net at a glance, over 6 months,
  12 months, year to date or a custom range.
- **Reports** — totals and breakdowns over any date range.
- **Exports** — CSV of income and expenses for your accountant or tax return.
- **Appearance** — ten built-in colour palettes, including a dark one and a
  high-contrast one.
- **Webhooks** — fire a notification (e.g. to n8n) when an invoice is created.

It is deliberately small: one container, a SQLite database, no build pipeline,
no account to sign up for. The data lives in a single folder you control and
back up.

## Stack

```
Flask + Gunicorn  ·  SQLite  ·  fpdf2 (PDF invoices)  ·  plain HTML/CSS/JS
```

No Node build, no external database, no runtime dependencies beyond Python.

## Quick start

```bash
git clone https://github.com/sofapi/coffer.git
cd coffer

cp .env.example .env        # optional — sensible defaults work as-is

docker compose pull         # fetch the prebuilt image from GHCR
docker compose up -d
```

Open <http://localhost:5000>.

Set your business name and upload an invoice logo under **Invoice Settings**,
and pick a colour palette under **Appearance**.

**Updating:** `docker compose pull && docker compose up -d`.

**Build from source instead** (contributors):

```bash
docker compose -f docker-compose.yml -f docker-compose.build.yml up -d --build
```

See [`SETUP.md`](SETUP.md) for first-time deployment, GHCR/private-image notes,
environment variables, volumes, and backup/restore.

## Your data

Everything Coffer stores — the SQLite database and any uploaded invoice logo —
lives in the bind-mounted `data/` directory. That folder is the only thing you
need to back up, and it is **never** committed to Git. Read
[`DATA-SAFETY.md`](DATA-SAFETY.md) before you push anything anywhere.

## ⚠️ Security note

Coffer currently ships with **no authentication**. It is built to run on a
trusted private network (a homelab, a LAN, behind a VPN). **Do not expose it
directly to the public internet** without putting authentication in front of it
(a reverse proxy with auth, an identity-aware proxy, or a VPN). Adding optional
built-in auth is the top item on the roadmap.

## What the dashboard numbers mean

Coffer only knows what you type into it, so the dashboard is careful about what
it claims. In particular it reports **Net**, not profit:

| Metric | Definition |
|--------|------------|
| **Invoiced** | Value of every invoice issued in the period, paid or not. |
| **Revenue** | Income entries + paid invoices, dated in the period. |
| **Costs** | All expenses dated in the period. |
| **Net** | Revenue − Costs. **Not** gross or net profit — there is no cost of sales, tax or depreciation in the data. |
| **Net margin** | Net ÷ Revenue, or a dash when there is no revenue. |
| **Outstanding** | Unpaid invoice balance as at today, across all time. |

Two limitations worth knowing:

- Coffer does not store **payment dates**, so a paid invoice counts in the month
  it was *issued*.
- Income entries and invoices are separate ledgers with no link between them. If
  you log an invoice payment as income **and** mark the invoice paid, it is
  counted twice.

The exact rules, including the double-counting guards, are written out at the
top of [`finance.py`](finance.py) — that docstring is the source of truth.

## Appearance

**Appearance** offers ten palettes (Coffer Classic is the default and looks
exactly like it always has). Everything the UI paints with is a semantic design
token defined in [`theme.py`](theme.py) — nav, cards, buttons, tables, charts,
focus rings, status badges and alerts all follow the selection, and the choice
is stored in the existing `settings` table.

**Adding a palette** is one entry in `PALETTES` in `theme.py`; the settings page,
the generated stylesheet and persistence all pick it up automatically. The test
suite then checks it for WCAG AA contrast and distinguishable status and chart
colours, so a palette that fails accessibility fails CI.

## Development

```bash
python -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt

pytest                       # tests
ruff check .                 # lint
flask --app app run          # dev server on :5000
```

## Sample data (development)

To explore the UI with obviously-fake data:

```bash
python seed_sample.py        # dummy customers/income/expenses/invoice
```

It seeds only if the database is empty (use `--force` to override) and contains
no real information.

## License

MIT.
