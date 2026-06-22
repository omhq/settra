# Settra — Agent & Developer Reference

Settra is a self-hosted MCP server on top of business applications. 
The server connects to external apps without replicating their data into a 
warehouse, maintains semantic metadata, and is using a Cube Core-powered 
semantic layer for cubes, measures, dimensions, joins, and business definitions.

## Architecture

```text
MCP client / admin browser
        |
        v
FastAPI backend (:8000)
        |
        +-- aiosqlite -> /data/app.db
        |   connections, models, semantic metadata, semantic AI runs
        +-- aiofiles -> /steampipe/config/*.spc
        |   connector credentials rendered as Steampipe config
        +-- httpx -> external provider APIs
        |   credential validation
        +-- asyncpg -> steampipe:9193
        |   schema introspection and metadata checks
        +-- LiteLLM
            model calls for semantic AI assistance

Steampipe service (:9193)
        |
        +-- reads /home/steampipe/.steampipe/config/*.spc
        +-- installs plugins declared by connectors/*/connection.yaml
```

Steampipe is the bundled query adapter today. Keep adapter boundaries explicit
so other SQL-capable engines can be added later.

## Active API Routes

| Method | Path | Description |
| --- | --- | --- |
| `GET` | `/api/health` | Steampipe connectivity check |
| `GET` | `/api/health/fdw` | Per-connection FDW diagnostics |
| `POST` | `/api/health/fdw/{id}/refresh` | Refresh Steampipe metadata cache |
| `POST` | `/api/health/steampipe/restart` | Restart Steampipe when configured |
| `GET` | `/api/connectors` | List connector definitions |
| `GET/POST/PUT/DELETE` | `/api/connections...` | Manage saved app connections |
| `POST` | `/api/connections/{id}/retry` | Re-validate connection credentials |
| `POST` | `/api/connections/{id}/metadata` | Fetch live Steampipe metadata |
| `GET` | `/api/model-providers` | List model provider definitions |
| `GET/POST/PUT/DELETE` | `/api/models...` | Manage encrypted model configs |
| `POST` | `/api/query/` | Placeholder direct SQL endpoint |
| `GET/POST/PATCH/DELETE` | `/api/semantics...` | Introspect, edit, confirm, and serve semantic metadata |

## Environment

| Variable | Default | Description |
| --- | --- | --- |
| `STEAMPIPE_HOST` | `steampipe` | Steampipe service hostname |
| `STEAMPIPE_PORT` | `9193` | Steampipe PostgreSQL port |
| `STEAMPIPE_DB_PASSWORD` | `steampipe_pass` in compose | Password for the Steampipe DB user |
| `STEAMPIPE_CONFIG_DIR` | `/steampipe/config` in compose | Where `.spc` files are written |
| `STEAMPIPE_RESTART_COMMAND` | unset | Optional restart command for non-Docker deployments |
| `STEAMPIPE_RESTART_TIMEOUT_SECONDS` | `20` | Restart command timeout |
| `DATA_DIR` | `/data` | SQLite and metadata cache directory |
| `DB_PATH` | `/data/app.db` | Optional SQLite path override |
| `CONNECTORS_DIR` | `/config/connectors` | Connector definitions and semantics |
| `MODEL_PROVIDERS_YAML` | `/config/models/providers.yaml` | Model provider definitions |
| `SECRET_KEY` | `dev-secret-change-me` | Encryption key material |
| `LOG_LEVEL` | `INFO` | Backend log level |
| `AGENT_DEBUG` | `false` | Verbose semantic-assistance logging |
| `AGENT_LOG_PROMPTS` | `false` | Log rendered prompts |
| `LITELLM_DEBUG` | `false` | LiteLLM debug logging |
| `LLM_REQUEST_TIMEOUT_SECONDS` | `90` | Model request timeout |
| `LLM_VISIBLE_RETRIES` | `2` | Model-provider retry count |
| `LLM_RETRY_BASE_DELAY_SECONDS` | `1` | Base retry delay |

## Connector Metadata

Connector definitions live at `connectors/<connector-key>/connection.yaml`.
Semantic metadata for the same connector lives at
`connectors/<connector-key>/semantics.yaml`.

To add a connector, add its connector definition, optionally add semantic
metadata, and rebuild or restart the Steampipe service so the plugin installer
sees the new connector.

## SQLite Schema

SQLite lives at `/data/app.db` backed by `./app_data` in local compose. Schema
creation and migrations live in `backend/app/db.py`.

Current table groups include:

- `connections` for saved connector metadata. Credentials are stored in
  Steampipe `.spc` files, not SQLite.
- `models` for encrypted model provider settings.
- `semantic_tables`, `semantic_columns`, `semantic_relationships`,
  `semantic_metrics`, and `semantic_metadata` for semantic guidance.
- `semantic_ai_runs` for AI-assisted semantic introspection history.

## Development

```bash
# First-time setup
cd frontend && npm install
cd backend && pip install -r requirements.txt

# Initialize SQLite tables and load connector semantics
make init

# Full stack
make dev

# Docker stack only
make run

# Rebuild app image
make build

# Rebuild Steampipe image
make build-steampipe
```

Useful checks:

```bash
docker compose logs -f app
docker compose logs -f steampipe
docker compose exec app python -m app.init
docker compose exec steampipe steampipe query "SELECT * FROM steampipe_internal.steampipe_connection"
```
