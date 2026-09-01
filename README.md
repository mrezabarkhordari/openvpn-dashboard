# OpenVPN Dashboard (`openvpn-dashboard`)

A self-hosted web UI for managing OpenVPN accounts: create users, issue client configs, watch live connections, and track usage.

The stack is Docker Compose. You can run **OpenVPN + the UI together**, or attach the UI to an OpenVPN directory that already exists on the host.

## Layout

| Path | Role |
|---|---|
| `config/` | Django project package (`config.settings`, URLs, WSGI/ASGI) |
| `openvpn_dashboard/` | Django app (models, views, templates, migrations) |
| `docker/` | Container images, supervisord, and OpenVPN helpers |
| `scripts/` | Install and operational scripts |
| `docs/` | Migration and production notes |

## Features

- **Users and accounts** — create users, attach VPN accounts, edit, delete
- **Client configs** — download `.ovpn` files; renew certificates
- **Access control** — activate, deactivate, and auto-expire accounts
- **Live status** — green indicator when a client is connected (from OpenVPN `status.log`)
- **Usage** — lifetime download / upload / total; reset per account or all accounts
- **Sessions** — connect / disconnect history per account
- **Daily statistics** — per-server and per-account rollups
- **Server settings** — public hostname and port used inside generated configs
- **Auto-refresh** — optional live reload of the account list (Off / 5s / 10s / 30s / 60s)

## How it fits together

| Service | Role |
|---|---|
| **web** | Django UI (Gunicorn), default host port **8800** |
| **collector** | Reads OpenVPN `status.log`, updates live usage and sessions |
| **scheduler** | Marks expired accounts (hourly) |
| **openvpn** | Optional. Compose profile `vpn`. Writes PKI and `status.log` into the shared data directory |

The UI and OpenVPN share one directory mounted at `/etc/openvpn` inside the containers (`server.conf`, `status.log`, `easy-rsa/pki/`, `ccd/`).

OpenVPN should use **status-version 2**. The status file must live on that mounted tree (`OPENVPN_STATUS_LOG`, default `/etc/openvpn/status.log`), not under host `/var/log/openvpn` unless that path is also mounted.

## Requirements

- Docker and Docker Compose v2
- Linux host (UDP **1194** is published when you run the built-in OpenVPN service)
- A reserved admin password and a Django `SECRET_KEY` (do not commit these)

## Quick start

### 1. Clone and configure

```bash
git clone https://github.com/YOUR_ORG/openvpn-dashboard.git
cd openvpn-dashboard
cp .env.example .env
```

Edit `.env` before the first start. At minimum set `SECRET_KEY`, `ADMIN_PASSWORD`, and `OPENVPN_SERVER_ADDRESS`. Optionally set `ADMIN_USERNAME` (default `admin`), `WEB_PORT` (default `8800`), and `TIME_ZONE` (default `UTC`).

Generate a secret key:

```bash
python3 -c "from secrets import token_urlsafe; print(token_urlsafe(50))"
```

### 2. Choose a deploy mode

**Mode A — full stack** (OpenVPN + UI + collector + scheduler)

```bash
./install.sh
# or
docker compose --env-file .env --profile vpn up -d --build
```

Data default: `./stack-data/openvpn` (`OPENVPN_DATA_DIR`). An empty volume generates a new PKI via Easy-RSA.

**Mode B — UI only** (existing OpenVPN on the host)

Set `OPENVPN_DATA_DIR` to the existing tree (often `/etc/openvpn`). The host needs Easy-RSA PKI, `server.conf`, writable `ccd/`, and `status.log` (status-version 2 recommended) on that mounted tree. `--ui-only` requires `OPENVPN_DATA_DIR` to be set.

```bash
./install.sh --ui-only
# or
docker compose --env-file .env up -d --build
```

**OpenVPN only:**

```bash
./install.sh --vpn-only
```

**Simple** (one container: web + collector + scheduler via supervisord)

```bash
docker compose --profile simple up -d
```

### 3. Open the UI

Browse `http://HOST:8800/login/` and sign in with `ADMIN_USERNAME` / `ADMIN_PASSWORD`. The first start creates that admin user.

## Using the UI

### Users

User Management → create a user → open User Info to see accounts.

### Accounts

From Account List or a user page:

1. **+ New Account** — user, duration (days) or expiration date
2. **Download** — `.ovpn` for the client
3. **Activate / Deactivate**
4. **Renew certificate**
5. **Sessions**
6. **Reset usage**
7. **Delete**

The account name on User Info opens the edit page (`?next=` returns to the user).

Days left is computed live from the expiration date. Connected = green dot from `status.log`.

### Config download settings

Account list header: **Server** and **Port** (public values written into `.ovpn`). Press Enter to save.

### Auto-refresh

Dropdown: Off, 5s, 10s, 30s, 60s (stored in browser `localStorage`).

### Statistics

Daily Usage comes from `aggregate_daily_stats`. If the page is empty, run a backfill (see Operations).

## Configuration

Copy `.env.example` to `.env`. Do not commit `.env`.

| Variable | Default | Purpose |
|---|---|---|
| `SECRET_KEY` | *(required)* | Django secret key. Generate a unique value; never commit a real key |
| `DEBUG` | `False` | Keep `False` in production |
| `ALLOWED_HOSTS` | `*` | Comma-separated hostnames |
| `TIME_ZONE` | `UTC` | Display and scheduler timezone |
| `LOG_LEVEL` | `INFO` | `DEBUG`, `INFO`, `WARNING`, `ERROR`, or `CRITICAL` |
| `ADMIN_USERNAME` | `admin` | Initial admin username (created on first start) |
| `ADMIN_PASSWORD` | *(required)* | Initial admin password |
| `ADMIN_EMAIL` | `admin@localhost` | Initial admin email |
| `WEB_PORT` | `8800` | Host port for the Django UI |
| `CSRF_TRUSTED_ORIGINS` | *(empty)* | Comma-separated origins, e.g. `https://vpn.example.com` |
| `SESSION_COOKIE_SECURE` | `False` | Set `True` behind HTTPS |
| `CSRF_COOKIE_SECURE` | `False` | Set `True` behind HTTPS |
| `SERVER_URL` | *(empty)* | Public UI URL; can also be edited on the Account List page |
| `OPENVPN_DATA_DIR` | `./stack-data/openvpn` | Host path mounted at `/etc/openvpn` |
| `OPENVPN_SERVER_ADDRESS` | *(required)* | Public hostname or IP written into `.ovpn` files |
| `OPENVPN_SERVER_PORT` | `1194` | Public OpenVPN port written into `.ovpn` files |
| `OPENVPN_PROTOCOL` | `udp` | Protocol written into `.ovpn` files (`udp` or `tcp`) |
| `OPENVPN_CERT_EXPIRE` | `825` | Certificate validity in days (new certs and renewals) |
| `OPENVPN_STATUS_LOG` | `/etc/openvpn/status.log` | Status log path inside the container (must be on the mounted tree) |
| `CLIENT_CONFIGS_PATH` | `./ovpn-configs` | Host directory for generated `.ovpn` files |
| `DATABASE_HOST_PATH` | `./stack-data/ui` | Host directory for the SQLite database |
| `USAGE_COLLECTOR_INTERVAL` | `2.0` | How often the collector reads `status.log` (seconds) |
| `USAGE_COMMIT_INTERVAL` | `10.0` | How often usage is committed to the database (seconds) |

Built-in OpenVPN service (profile `vpn`): `OPENVPN_ENDPOINT`, `OPENVPN_PORT` (default `1194`, keep in sync with `OPENVPN_SERVER_PORT`), `OPENVPN_PROTO` (default `udp`), `OPENVPN_SUBNET` (default `10.8.0.0/24`), `OPENVPN_STATUS_INTERVAL` (default `10`), `OPENVPN_CONTAINER_NAME` (default `openvpn`).

Inside the container, paths default to `OPENVPN_DIR=/etc/openvpn`, `OPENVPN_EASY_RSA_DIR=/etc/openvpn/easy-rsa`, `OPENVPN_CCD_DIR=/etc/openvpn/ccd`, `OPENVPN_LOG_DIR=/etc/openvpn`. Optional HTTPS: `SECURE_HSTS_SECONDS` (default `0`), `SECURE_HSTS_INCLUDE_SUBDOMAINS`, `SECURE_HSTS_PRELOAD`. Optional image labels: `IMAGE_NAME`, `IMAGE_TAG`.

There is no `SERVER_PORT` environment variable; use `WEB_PORT` and `SERVER_URL`.

Example `server.conf` status lines:

```
status /etc/openvpn/status.log
status-version 2
```

## Operations

Rebuild the web service only:

```bash
docker compose --env-file .env --profile vpn up -d --build --no-deps web
```

Expired accounts: the scheduler runs `check_expired_accounts --daemon`.

Daily usage backfill:

```bash
docker exec openvpn-dashboard python manage.py aggregate_daily_stats --all
```

Logs: `docker compose --env-file .env logs -f` (add `--profile vpn` for the full stack).

Backup `stack-data/ui`, `OPENVPN_DATA_DIR`, and `ovpn-configs`. The PKI is secret — treat it like a password.

## Data layout

| Path | Contents |
|---|---|
| `stack-data/ui` | Django database (`DATABASE_HOST_PATH`) |
| `stack-data/openvpn` | PKI, `server.conf`, `status.log`, `ccd/` (`OPENVPN_DATA_DIR`) |
| `ovpn-configs` | Generated client `.ovpn` files (`CLIENT_CONFIGS_PATH`) |

Do not commit `.env`, `stack-data/`, or real `.ovpn` files.

## Development

Local development uses `config.settings` (`DJANGO_SETTINGS_MODULE=config.settings`; `manage.py` sets this by default).

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
export DJANGO_SETTINGS_MODULE=config.settings
python manage.py migrate
python manage.py runserver
```

Collector (second terminal): `python manage.py collect_usage`

## Security notes

Keep `DEBUG=False` in production. Set `ALLOWED_HOSTS` and `CSRF_TRUSTED_ORIGINS` to your real hostname. Enable `SESSION_COOKIE_SECURE` and `CSRF_COOKIE_SECURE` on HTTPS. Never publish `.env` or the PKI (`easy-rsa/pki/`).

## Troubleshooting

| Symptom | What to check |
|---|---|
| Connected indicator empty | `status.log` on the mounted tree, readable, status-version 2 |
| Usage stays at zero | Collector running; same `OPENVPN_DATA_DIR` as OpenVPN |
| Statistics page empty | Run `aggregate_daily_stats --all` |
| CSRF errors | Set `CSRF_TRUSTED_ORIGINS` (scheme + host + port) |
| Port already in use | Change `WEB_PORT` in `.env` |

## Acknowledgements

This project would not exist without work published by others. Thank you.

- **[angristan/openvpn-install](https://github.com/angristan/openvpn-install)** — the OpenVPN installer our optional VPN container is built from (PKI, `server.conf`, client profiles). The image pins a known commit and adds a thin wrapper for Docker; the hard parts are Angristan’s.
- **[tonyseek/openvpn-status](https://github.com/tonyseek/openvpn-status)** — parses OpenVPN `status.log` so the collector can show live connections and usage. That library is the status/usage exporter this UI sits on.

## License

[MIT](LICENSE)
