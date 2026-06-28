# Coffer — Setup & Operations Guide

This covers first-time deployment, the GHCR image, environment variables,
persistent storage, and backup/restore.

## 1. Requirements

- Docker + Docker Compose v2.
- A host on a **trusted network** (see Security below — there is no built-in
  auth yet).

## 2. First-time deployment (pull the prebuilt image)

```bash
git clone https://github.com/sofapi/coffer.git
cd coffer
cp .env.example .env        # optional; defaults are fine
docker compose pull
docker compose up -d
```

Open <http://localhost:5000>. On first boot Coffer creates an empty SQLite
database automatically — there is no migration step. Then:

1. Go to **Invoice Settings** and set your **business name** (this drives the
   header on invoices and the app's nav bar) and upload a **logo** if you want
   one on your PDFs.
2. Add a customer, create an invoice, log some income and expenses.

### Build from source instead

For local development or if you'd rather not pull a published image:

```bash
docker compose -f docker-compose.yml -f docker-compose.build.yml up -d --build
```

## 3. The GHCR image & visibility

The image is published to **GitHub Container Registry** as
`ghcr.io/sofapi/coffer:latest` by the workflow in `.github/workflows/`, on every
push to `main` (plus `:vX.Y.Z` when you push a git tag).

After the **first** successful publish, the package is **Private** by default.
Choose one:

- **Make it Public** (simplest — anyone can `docker compose pull` with no login):
  GitHub → your profile → Packages → `coffer` → Package settings → Change
  visibility → Public.
- **Keep it Private** and authenticate on each host that pulls it (below).

### Pulling a private image with `docker login ghcr.io`

On the deployment host, log in once with a GitHub Personal Access Token that has
the `read:packages` scope:

```bash
echo "<YOUR_GITHUB_PAT>" | docker login ghcr.io -u <your-github-username> --password-stdin
docker compose pull
docker compose up -d
```

The login is cached in `~/.docker/config.json`, so you only do it once per host
(until the token expires).

### Forking

If you fork Coffer, repoint the image at your own namespace: edit the `image:`
line in `docker-compose.yml` to `ghcr.io/<you>/coffer` — the workflow already
publishes under `${{ github.repository }}`, so it follows your fork automatically.

## 4. Environment variables

All optional — set them in `.env` (copied from `.env.example`) or directly in
`docker-compose.yml`.

| Variable | Default | Purpose |
|----------|---------|---------|
| `COFFER_IMAGE_TAG` | `latest` | Which published image tag to run. Pin to a `vX.Y.Z` for a frozen deploy. |
| `COFFER_PORT` | `5000` | Host port for the web UI (container always listens on 5000). |
| `DB_PATH` | `/app/data/coffer.db` | Database path **inside** the container. Leave as-is. |
| `TZ` | `Europe/London` | Container timezone. |

## 5. Persistent storage

Coffer keeps **all** state in one place: the `data/` directory, bind-mounted to
`/app/data` in the container.

```
data/
├── coffer.db          # SQLite database — customers, invoices, income, expenses
└── invoice_logo.*     # uploaded invoice logo (if any)
```

This directory is **git-ignored** and is the **only** thing you need to back up.
Everything else (code, image) is reproducible from Git/GHCR.

> Using a host path elsewhere? Copy `docker-compose.override.example.yml` →
> `docker-compose.override.yml` and point the `data` mount at it. The override
> file is git-ignored, so your host path never gets committed. (If you don't
> need it, ignore this — the default `./data` works out of the box.)

## 6. Backups & restore

Because everything lives in `data/`, backup is a file copy of a folder. SQLite
in WAL mode is safe to copy while running, but the cleanest backup is taken with
the container stopped.

**Back up:**

```bash
cd /path/to/coffer
docker compose stop                          # optional but cleanest
tar czf coffer-backup-$(date +%Y%m%d-%H%M%S).tar.gz data/
docker compose start
# move the .tar.gz off-box (it contains real financial data — treat it as such)
```

**Restore:**

```bash
cd /path/to/coffer
docker compose down
rm -rf data && mkdir data
tar xzf coffer-backup-YYYYMMDD-HHMMSS.tar.gz   # recreates data/
docker compose up -d
```

Backup archives contain real financial data — store them securely and **never**
commit them (the `.gitignore` already blocks `*.tar.gz`, `backups/`, `*.bak`).

## 7. Security

Coffer has **no authentication** today. Run it only where you trust the network:

- A homelab / LAN you control.
- Behind a VPN (WireGuard, Tailscale).
- Behind a reverse proxy that adds authentication (e.g. an identity-aware proxy,
  or basic auth at the proxy layer).

**Do not** publish port 5000 to the open internet. Anyone who can reach it can
read and edit your finances. Adding optional built-in auth is the top roadmap
item; until it lands, the network boundary is your only protection.

## 8. Troubleshooting

- **`pull access denied` / `denied`** — the GHCR package is Private and the host
  isn't logged in. Either make the package Public, or `docker login ghcr.io`
  (section 3).
- **Container unhealthy** — check `docker compose logs coffer`. The healthcheck
  hits `/health`; if the app didn't start, the logs say why.
- **Empty app after restore** — confirm `data/coffer.db` exists and the `data/`
  mount in `docker-compose.yml` points where you think it does.
