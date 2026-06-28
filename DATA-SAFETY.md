# DATA SAFETY — read before you commit or push

Coffer handles **real personal and financial data**: customer names and
addresses, invoices, income and expenses. This file is the contract for keeping
that data out of Git, out of the published image, and out of anywhere public.

> The golden rule: **code and configuration templates go in Git. Data never
> does.** When in doubt, leave it out.

## What must NEVER be committed

| Item | Why |
|------|-----|
| `data/` (the whole directory) | Holds the live SQLite database and uploaded logos. |
| `*.db`, `*.sqlite*`, `*.db-wal`, `*.db-shm`, `*.db-journal` | The database and its sidecar files — actual financial records. |
| `invoice_logo.*` | Uploaded business logo — personal/identifying. |
| `.env` (and any `.env.*` except `.env.example`) | May hold secrets/tokens. |
| `*.key`, `*.pem`, `*.crt`, `*.secret`, `secrets/` | Credentials. |
| `backups/`, `*.bak`, `*.dump`, `*.tar.gz`, `*.zip` | Backups are full copies of the financial database. |
| `*.csv` | Coffer exports income/expenses as CSV — real money data. |
| `.claude/` | Local tooling settings; may reference private paths. |

All of the above are already listed in **`.gitignore`** (so Git won't stage
them) and **`.dockerignore`** (so they can't leak into the published image).

## What IS safe to commit

- Application code: `app.py`, `db.py`, `pdf_gen.py`.
- Templates and static assets: `templates/`, `static/`.
- Container & CI: `Dockerfile`, `docker-compose*.yml`, `.github/`.
- Docs: `README.md`, `SETUP.md`, this file.
- Templates of config: **`.env.example`** (no real values).
- `data/.gitkeep` — an empty placeholder so the folder exists; nothing else
  from `data/`.
- `seed_sample.py` — **dummy** development data only.

## Test fixtures and sample data

Any fixture, seed, screenshot, or example **must use invented data**. Never
copy a real customer, invoice, amount, address, or logo into a fixture, a doc,
or a test. `seed_sample.py` follows this — fictional companies
(`Acme Widgets Ltd`, `…@example`) and round-number amounts. Keep it that way.

## Verify before you commit (every time)

A 10-second check that nothing sensitive is staged:

```bash
# 1. Is anything ignored slipping through? (should print nothing)
git status --porcelain | grep -iE '\.db|\.sqlite|\.env$|\.csv|invoice_logo|backup|\.bak'

# 2. Confirm the ignores are actually active (should each print the path)
git check-ignore data/coffer.db .env data/invoice_logo.png

# 3. Eyeball exactly what will be committed
git status
git diff --cached --stat
```

If step 1 prints anything, **stop** and fix `.gitignore` before committing. If
something sensitive was *already* committed in a previous commit, do not just
delete it in a new commit — the data stays in history. Treat it as a leak:
rewrite history (e.g. `git filter-repo`) before pushing, and rotate anything
secret that was exposed.

## Before the repo goes public

- The published GHCR image is built from the `.dockerignore`'d context, so it
  contains **code only** — verify once with
  `docker run --rm ghcr.io/sofapi/coffer:latest ls -la /app` (no `coffer.db`,
  no `invoice_logo.*` under `/app/data`).
- Remember Coffer has **no auth** — a public repo is fine, a publicly-reachable
  *instance* is not (see SETUP.md → Security).
