# Settra — Agent & Developer Reference

Complete reference for AI agents and developers working on this codebase.

---

## What is Settra?

Settra is a self-hosted analytics agent built around a pluggable Zero-ETL query layer and an extensive semantics layer for analysis jobs over data in external apps. The current bundled engine is Steampipe: users connect services such as Google Sheets, Stripe, and HubSpot through the UI; Settra validates credentials, writes Steampipe `.spc` config, introspects schemas into semantic metadata, and lets the browser chat or messaging channels run governed analysis against the data in place. The engine layer is intended to support other SQL-capable adapters such as CloudQuery, osquery, and foreign data wrapper engines as they are added.

---

## Architecture

```
Browser (React/Vite)
        │  HTTP  (dev: localhost:5173 → proxy → :8000)
        ▼
FastAPI backend  (:8000)
        │
        ├── aiosqlite → /data/app.db   (connections, chat, models, messaging, semantics)
        ├── aiofiles  → /steampipe/config/*.spc  (per-connection HCL files, shared volume)
        ├── httpx     → external provider APIs  (credential validation)
        ├── asyncpg   → steampipe:9193  (metadata introspection + SQL analysis)
        ├── LiteLLM   → configured model providers
        └── workers   → queued chat and messaging jobs

Zero-ETL engine adapter  (current: Steampipe service :9193)
        ├── Steampipe service with embedded PostgreSQL FDW
        ├── reads config from /home/steampipe/.steampipe/config/*.spc  (shared volume)
        └── installs declared plugins from connectors/*/connection.yaml
```

Steampipe is the only bundled engine today. The codebase treats it as the current Zero-ETL adapter, not the boundary of the product model; future adapters can reuse the same connection, semantic metadata, chat, and messaging surfaces where their schemas can be exposed to Settra.

### Shared volumes

| Volume / bind       | App mount           | Steampipe mount                      | Purpose                                                             |
| ------------------- | ------------------- | ------------------------------------ | ------------------------------------------------------------------- |
| `steampipe_config`  | `/steampipe/config` | `/home/steampipe/.steampipe/config`  | `.spc` credential files written by backend, read by steampipe       |
| `steampipe_db`      | —                   | `/home/steampipe/.steampipe/db`      | PostgreSQL data dir, plugin .so binaries                            |
| `steampipe_plugins` | —                   | `/home/steampipe/.steampipe/plugins` | Persisted Steampipe plugin installs for local connector development |
| `./app_data`        | `/data`             | —                                    | SQLite database (`app.db`)                                          |

---

## Services

### `app` (FastAPI)

- **Image**: `omhq/settra:0.0.1` — built from `Dockerfile`
- **Entry**: `uvicorn main:app --reload --host 0.0.0.0 --port 8000`
- **Source**: `backend/` (hot-reloaded via volume mount in dev)
- **Python**: 3.12-slim
- **Key deps**: FastAPI, aiosqlite, aiofiles, httpx, pyyaml, asyncpg, uvicorn

#### API routes

| Method                  | Path                                     | Description                                                                                          |
| ----------------------- | ---------------------------------------- | ---------------------------------------------------------------------------------------------------- |
| `GET`                   | `/api/health`                            | Steampipe connectivity check (asyncpg SELECT 1)                                                      |
| `GET`                   | `/api/config`                            | Runtime config exposed to the frontend (for example `PUBLIC_API_URL`)                                |
| `GET`                   | `/api/connectors`                        | List available connector types from `connectors/*/connection.yaml`                                   |
| `GET`                   | `/api/connections`                       | List all saved connections (SQLite metadata)                                                         |
| `POST`                  | `/api/connections`                       | Create connection: validate creds → write .spc → insert DB row                                       |
| `GET`                   | `/api/connections/{id}`                  | Get single connection                                                                                |
| `PUT`                   | `/api/connections/{id}`                  | Update connection (re-validates creds)                                                               |
| `DELETE`                | `/api/connections/{id}`                  | Delete connection + remove .spc file                                                                 |
| `POST`                  | `/api/connections/{id}/retry`            | Re-validate credentials; update status in DB                                                         |
| `POST`                  | `/api/connections/{id}/metadata`         | Fetch live Steampipe metadata for a connection                                                       |
| `GET`                   | `/api/model-providers`                   | List model provider definitions from `models/providers.yaml`                                         |
| `GET/POST/PUT/DELETE`   | `/api/models...`                         | Manage encrypted model configs and test model connectivity                                           |
| `GET/POST/DELETE`       | `/api/chat/threads...`                   | Manage chat threads, messages, and clearing/deleting threads                                         |
| `POST`                  | `/api/chat/`                             | Start a streamed analysis run backed by the chat job worker                                          |
| `GET`                   | `/api/chat/requests/{request_id}/events` | Stream queued chat run events                                                                        |
| `POST`                  | `/api/query/`                            | Placeholder direct SQL query endpoint; browser analysis uses `/api/chat/`                            |
| `GET/POST/PUT/DELETE`   | `/api/messaging...`                      | Manage messaging providers/configs and receive provider webhooks                                     |
| `GET/POST/PATCH/DELETE` | `/api/semantics...`                      | Introspect, edit, confirm, and serve semantic tables, columns, relationships, metrics, and contracts |

#### Environment variables

| Variable                  | Default                                                                           | Description                                                         |
| ------------------------- | --------------------------------------------------------------------------------- | ------------------------------------------------------------------- |
| `STEAMPIPE_HOST`          | `steampipe`                                                                       | Steampipe service hostname                                          |
| `STEAMPIPE_PORT`          | `9193`                                                                            | Steampipe PostgreSQL port                                           |
| `STEAMPIPE_DB_PASSWORD`   | `steampipe_pass` in compose; `""` code fallback                                   | Password for the `steampipe` DB user                                |
| `STEAMPIPE_CONFIG_DIR`    | `/steampipe/config` in compose; `/home/steampipe/.steampipe/config` code fallback | Where .spc files are written                                        |
| `DATA_DIR`                | `/data`                                                                           | SQLite database directory                                           |
| `DB_PATH`                 | `/data/app.db`                                                                    | Optional override for the SQLite database path                      |
| `CONNECTORS_DIR`          | `/config/connectors`                                                              | Connector definitions and semantic metadata                         |
| `CHANNELS_DIR`            | `/config/channels`                                                                | Messaging channel definitions                                       |
| `MODEL_PROVIDERS_YAML`    | `/config/models/providers.yaml`                                                   | Model provider definitions                                          |
| `SECRET_KEY`              | `dev-secret-change-me`                                                            | Encryption key material for model and channel secrets               |
| `PUBLIC_API_URL`          | `""`                                                                              | Public HTTPS API origin used when generating webhook setup commands |
| `STATIC_DIR`              | `/opt/static`                                                                     | Built frontend static directory for monolith deployments            |
| `CHAT_WORKER`             | `true`                                                                            | Enable or disable the in-app chat worker                            |
| `MESSAGING_WORKER`        | `true`                                                                            | Enable or disable the in-app messaging worker                       |
| `LOG_LEVEL`               | `INFO`                                                                            | Backend log level                                                   |
| `AGENT_DEBUG`             | `false`                                                                           | Verbose agent logging                                               |
| `AGENT_LOG_PROMPTS`       | `false`                                                                           | Log rendered agent prompts                                          |
| `LITELLM_DEBUG`           | `false`                                                                           | LiteLLM debug logging                                               |
| `CHAT_MAX_RESULT_ROWS`    | `100`                                                                             | Max rows returned to chat analysis context                          |
| `CHAT_MAX_QUERY_ATTEMPTS` | `5`                                                                               | Max SQL repair/retry attempts per chat run                          |

### `steampipe`

- **Image**: `omhq/settra-steampipe:0.0.1` — built from `Dockerfile.steampipe`
- **Base**: `ubuntu:24.04`
- **Steampipe**: downloaded from GitHub at build time via `STEAMPIPE_VERSION` (default `2.4.4`)
- **PostgreSQL FDW**: embedded in Steampipe, listens on `0.0.0.0:9193`
- **OS user**: `steampipe` (uid=9193) — no root access inside container
- **Entry**: `/usr/local/bin/steampipe-init.sh`

#### Environment variables

| Variable                      | Default              | Description                                         |
| ----------------------------- | -------------------- | --------------------------------------------------- |
| `STEAMPIPE_DATABASE_PASSWORD` | `steampipe_pass`     | PostgreSQL password for the `steampipe` user        |
| `CONNECTORS_DIR`              | `/config/connectors` | Connector metadata scanned for plugin install specs |

#### Steampipe directory layout

```
/home/steampipe/.steampipe/
├── config/       ← shared .spc files written by the app
├── db/           ← Steampipe embedded PostgreSQL data
├── logs/         ← Steampipe logs
└── plugins/      ← persisted Steampipe plugin installs
```

---

## Connection Validation Flow

### Creating / updating a connection

1. Frontend sends `POST /api/connections` with `{name, plugin, credentials}`.
2. Backend validates the plugin key exists in `connectors/<key>/connection.yaml`.
3. Backend calls the provider's `test_request` URL with the credentials (e.g. `GET https://api.stripe.com/v1/account` with `Authorization: Bearer <api_key>`).
4. If the provider returns HTTP 200 → write `<slug>.spc` to the shared config volume, insert DB row with `status=active`.
5. If the provider returns non-200 or times out → return HTTP 422, nothing is written.

### Retrying a connection (`POST /api/connections/{id}/retry`)

1. Look up `slug` and `plugin` from SQLite.
2. Read credentials back from the `.spc` file (never stored in SQLite).
3. Re-run the provider REST API check.
4. Update `status` in SQLite to `active` or `failed`.
5. Return `{id, status, detail}`.

> **Note**: The retry flow validates provider credentials directly and no longer depends on an FDW query succeeding.

---

## Steampipe Init Script (`scripts/steampipe-init.sh`)

Runs as `steampipe` user on every container start. Steps:

1. **Read connector metadata** from `CONNECTORS_DIR`.
2. **Install missing plugins** declared by each `connection.yaml` as `plugin@plugin_version`.
3. **Build-time mode** exits after plugin install when `STEAMPIPE_INIT_INSTALL_ONLY=true`.
4. **Start service** with `exec steampipe service start --foreground`.

---

## Debug Logging

Use Docker logs while developing:

```bash
docker compose logs -f app
docker compose logs -f steampipe
```

For more backend/agent detail, set `LOG_LEVEL=DEBUG`, `AGENT_DEBUG=true`, `AGENT_LOG_PROMPTS=true`, or `LITELLM_DEBUG=true` on the app container.

---

## Backend → Steampipe Connectivity

The backend connects to Steampipe's PostgreSQL with asyncpg for health checks, metadata introspection, semantic context building, and SQL generated by the chat agent. Available schemas depend on saved connection slugs, installed plugins, and provider credentials. Use `POST /api/connections/{id}/metadata`, `/api/health`, and `docker compose logs -f steampipe` when debugging schema visibility.

---

## Operational Notes

- `POST /api/query/` is still a placeholder direct SQL endpoint. User-facing analysis goes through `POST /api/chat/` and the chat worker.
- Connector credential validation uses provider `test_request` HTTP checks. A connection can validate even if a Steampipe plugin later fails to install, load, or expose tables.
- Steampipe plugin versions are pinned in each `connectors/<key>/connection.yaml`. If schemas are missing, check `docker compose logs -f steampipe`, `docker compose exec steampipe steampipe plugin list`, and the connection metadata endpoint.
- The app stores model/channel secrets encrypted with `SECRET_KEY`; changing `SECRET_KEY` makes existing encrypted secrets unreadable.

---

## Development Workflow

```bash
# First-time setup
cd frontend && npm install
cd backend && pip install -r requirements.txt

# Initialize SQLite tables and load agent prompts + connector semantics
make init

# Full stack (docker compose app + steampipe + Vite dev server in parallel)
make dev

# Docker stack only (no Vite)
make run

# Rebuild the steampipe image (needed after connector metadata or Dockerfile.steampipe changes)
make build-steampipe

# Rebuild the app image
make build

# Force-recreate steampipe container (picks up init script changes without rebuild)
IMAGE=omhq/settra:0.0.1 STEAMPIPE_IMAGE=omhq/settra-steampipe:0.0.1 \
  docker compose up -d --no-build --force-recreate steampipe

# Check logs
docker compose logs -f steampipe
docker compose logs -f app

# Open a shell in the steampipe container
docker compose exec steampipe /bin/sh

# Run a steampipe query directly
docker compose exec steampipe steampipe query "SELECT * FROM steampipe_internal.steampipe_connection"
```

---

## File Structure

```
settra/
├── Makefile                        # Dev and build commands
├── docker-compose.yml              # Service definitions and volumes
├── Dockerfile                      # App (FastAPI) image
├── Dockerfile.steampipe            # Steampipe image (installs Steampipe + declared plugins)
├── connectors/                     # Per-connector definitions and semantic metadata
│   └── <connector>/
│       ├── connection.yaml         # Connector type definition and plugin version
│       └── semantics.yaml          # Agent semantic metadata for this connector
├── AGENTS.md                       # This file
│
├── scripts/
│   └── steampipe-init.sh           # Steampipe container entrypoint
│
├── backend/
│   ├── requirements.txt
│   ├── main.py                     # FastAPI app, CORS, router registration, DB init
│   └── app/
│       ├── db.py                   # SQLite schema migrations (aiosqlite)
│       └── routers/
│           ├── chat.py             # Chat threads, streaming runs, queued events
│           ├── connections.py      # Connection CRUD, validation, metadata
│           ├── health.py           # /api/health — steampipe TCP/asyncpg check
│           ├── messaging.py        # Messaging providers, configs, webhooks
│           ├── model_configs.py    # Model provider definitions and encrypted configs
│           ├── query.py            # Placeholder direct SQL query endpoint
│           ├── runtime_config.py   # Frontend runtime config
│           └── semantics.py        # Semantic introspection, edits, contracts
│
└── frontend/
    ├── package.json
    ├── vite.config.ts
    └── src/
        └── ...                     # React + TypeScript + Tailwind v4 + shadcn/ui
```

---

## Connector Metadata Schema

Connector definitions live at `connectors/<connector-key>/connection.yaml`.
Each connection file becomes a card in the UI. Semantic metadata for that same connector lives next to it at `connectors/<connector-key>/semantics.yaml`.

```yaml
name: Display Name
plugin: <steampipe-plugin-name> # matches steampipe hub plugin name
plugin_version: v1.2.0 # steampipe plugin version to install
logo: <filename>.svg
description: Short description
docs: https://hub.steampipe.io/...
test_table: <table-name>
test_request:
  url: https://api.example.com/endpoint # validated on create/update/retry
  auth_header: "Bearer {api_key}" # {field_key} interpolated from credentials
fields:
  - key: api_key
    label: API Key
    type: secret # renders as password input
    placeholder: "..."
    help: "..."
    required: true
```

To add a new connector: add `connectors/<connector-key>/connection.yaml`, optionally add `connectors/<connector-key>/semantics.yaml`, and restart/rebuild steampipe so the plugin installer sees the new connector.

### Semantic Metadata Schema

The canonical semantic file template, field guidance, and validation workflow live in `.claude/skills/semantic-file/SKILL.md`. Read that skill before generating or reviewing `connectors/<connector-key>/semantics.yaml`.

At a glance, semantic files use top-level `plugin`, `version`, `generated_by`, `validated`, optional `ignored_column_postfixes`, and `tables`. Use `metrics.*.sql` for reusable metric expressions, `dimensions.*.column` for simple dimensions, `dimensions.*.sql` for computed dimensions, and `columns.*.transform` for normalized field use. Keep `validated: false` until names, joins, and expressions have been tested against the live Steampipe schema.

Claude Code users can invoke the project skill `/semantic-file` to generate or review connector semantic files. The skill lives at `.claude/skills/semantic-file/SKILL.md`.

---

## SQLite Schema

SQLite lives at `/data/app.db` (backed by `./app_data` in local compose). Schema creation and migrations live in `backend/app/db.py` and are versioned by `PRAGMA user_version`.

Current table groups include:

- `connections` for saved connector metadata. Credentials are **never stored in SQLite**; they live only in `.spc` files on the `steampipe_config` volume.
- `model_configs` for encrypted model provider settings.
- `chat_threads`, `chat_messages`, `chat_thread_connections`, `chat_requests`, `chat_jobs`, and `chat_run_events` for browser and worker chat state.
- `messaging_configs`, `messaging_conversations`, `messaging_events`, and `messaging_jobs` for channel integrations such as Telegram and WhatsApp.
- `semantic_tables`, `semantic_columns`, `semantic_relationships`, `semantic_metrics`, and `semantic_metadata` for generated, reviewed, and file-backed semantic guidance.
- `agent_prompts` for seeded system prompts and connector prompt snippets.
