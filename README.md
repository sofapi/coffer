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
- **Reports** — totals and breakdowns over any date range.
- **Exports** — CSV of income and expenses for your accountant or tax return.
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

Set your business name and upload an invoice logo under **Invoice Settings**.

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

## Sample data (development)

To explore the UI with obviously-fake data:

```bash
python seed_sample.py        # dummy customers/income/expenses/invoice
```

It seeds only if the database is empty (use `--force` to override) and contains
no real information.

## License

MIT.
