# Settra — agent and developer reference

Settra is a self-hosted MCP server that makes live sheet data available to
automated agents. The current implementation supports Google Sheets as its only
source. Steampipe is the read-only adapter, Cube Core is the canonical semantic
layer, and the MCP surface exposes bounded discovery plus Cube REST queries.

## Guardrails

- Keep Google Sheets as the only source. Do not add provider selection,
  additional connector directories, third-party app plugins, or cross-provider
  examples.
- Keep MCP clients on the Cube semantic contract. Tools inspect Cube metadata or
  execute Cube REST query JSON; they do not accept raw Steampipe SQL.
- Keep Cube Core as the only semantic layer.
- The packaged Google Sheets YAML in `connectors/googlesheets/semantics.yaml` is
  a template. Active spreadsheet models are generated under
  `/cube/conf/model/generated/connections`.
- Worksheet-specific semantic edits belong in `semantic_overlays/*.yaml`.
  Agent-generated overlays are restricted to
  `/cube/conf/model/overlays/generated`.
- `/api/query/` accepts Cube REST query JSON. It is not a SQL endpoint.
- SQLite stores spreadsheet connection metadata and privacy-safe MCP metrics.
  Google credentials and MCP payload contents are not stored in SQLite;
  credentials are rendered to Steampipe `.spc` files.

## Architecture

```text
Automated agent / MCP client
        |
        v
/mcp streamable HTTP
        |
        v
FastAPI backend (:8000)
        |
        +-- MCP metadata, sample, profile, semantic, and query tools
        +-- httpx -> Cube REST API
        +-- aiosqlite -> /data/app.db
        +-- aiofiles -> /steampipe/config/*.spc
        +-- asyncpg -> steampipe:9193
        +-- /cube/conf/model
                |
                v
          Cube Core (:4000)
                |
                v
          Steampipe (:9193)
                |
                v
          Google Sheets API
```

The admin UI manages connected sheet data, semantic models, MCP request
metrics, service health, and deployment settings.

## Google Sheets behavior

Each saved connection maps to one `spreadsheet_id`. The Steampipe plugin exposes
spreadsheet, sheet, and cell metadata plus configured dynamic sheet tables.
Settra also synthesizes virtual worksheet tables from `googlesheets_cell` when
it can read a clean first-row header mapping.

For agent workflows:

1. List connected sheet sources.
2. Discover exact tab and column names with bounded metadata.
3. Sample or profile only relevant worksheet tables.
4. Prefer an existing compiled Cube model.
5. When semantics are missing, draft and validate the smallest sheet-specific
   overlay, explain assumptions, and mutate only after user approval.
6. Query through Cube REST JSON and verify the result.

For timezone-neutral dates, set
`meta.settra.semantic_type: business_date`; `query_cube` renders those values as
`YYYY-MM-DD` so clients do not apply viewer-local timezone shifts.

## MCP surface

The server is mounted at `/mcp` using streamable HTTP; `/mcp` normalizes to
`/mcp/`. Public deployments should protect it with OAuth bearer authentication.
The built-in single-admin provider publishes discovery under `/.well-known/*`
and endpoints under `/oauth/*`.

Available tools:

| Tool | Purpose |
| --- | --- |
| `list_cubes` | Search a bounded catalog of compiled cubes. |
| `get_cube` | Fetch one compact semantic definition. |
| `query_cube` | Execute one bounded Cube REST query object. |
| `get_cube_meta` | Search compact Cube `/v1/meta` detail. |
| `list_connections` | List connected Google spreadsheets without secrets. |
| `get_connection_metadata` | Discover bounded live worksheet tables and columns. |
| `sample_connection_table` | Fetch compact positional worksheet rows. |
| `profile_connection_table` | Return a bounded sample profile by column. |
| `list_semantic_overlays` | List authored and generated sheet overlays. |
| `get_semantic_overlay` | Read exact overlay YAML and compile status. |
| `validate_semantic_overlay` | Dry-run proposed Cube YAML and test queries. |
| `create_semantic_overlay` | Create an approved generated overlay. |
| `update_semantic_overlay` | Replace an approved generated overlay. |
| `save_semantic_overlay` | Deprecated generated-overlay upsert. |

Available resources:

| Resource | Purpose |
| --- | --- |
| `settra://semantics/meta` | Raw compiled Cube metadata. |
| `settra://semantics/cubes` | First fixed cube page. |
| `settra://semantics/cubes/{name}` | Compact cube or view definition. |
| `settra://semantics/model/{path}` | Mounted Cube YAML model file. |

## HTTP API

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/api/health` | Steampipe connectivity. |
| `GET` | `/api/health/fdw` | Per-spreadsheet FDW diagnostics. |
| `POST` | `/api/health/fdw/{id}/refresh` | Refresh spreadsheet metadata cache. |
| `POST` | `/api/health/steampipe/restart` | Restart Steampipe when configured. |
| `GET` | `/api/google-sheets/config` | Google Sheets form configuration. |
| `GET` | `/api/google-sheets/documentation` | Google Sheets setup guide. |
| `GET` | `/api/connections` | List connected spreadsheets. |
| `POST` | `/api/connections` | Connect a spreadsheet and render its `.spc` file. |
| `GET` | `/api/connections/{id}` | Fetch one spreadsheet connection. |
| `PUT` | `/api/connections/{id}` | Update spreadsheet access. |
| `DELETE` | `/api/connections/{id}` | Disconnect a spreadsheet. |
| `GET` | `/api/connections/{id}/secrets` | Return saved secret fields from `.spc`. |
| `POST` | `/api/connections/{id}/retry` | Revalidate access and FDW state. |
| `POST` | `/api/connections/{id}/metadata` | Refresh live worksheet metadata. |
| `POST` | `/api/query/` | Execute Cube REST query JSON. |
| `GET/POST` | `/api/semantics/model[/sync]` | Inspect or refresh model files. |
| `GET/PUT/DELETE` | `/api/semantics/model/files/{path}` | Manage allowed Cube YAML files. |
| `GET` | `/api/semantics/meta` | Proxy Cube `/v1/meta`. |
| `GET` | `/api/requests` | Privacy-safe MCP request metrics. |
| `GET` | `/api/settings` | Deployment and OAuth settings. |

## Configuration

Important backend variables:

| Variable | Default | Purpose |
| --- | --- | --- |
| `PRODUCT_NAME` | `Settra` | User-facing product name. |
| `CONFIG_DIR` | `/config` | Configuration root. |
| `CONNECTORS_DIR` | derived | Directory containing `googlesheets/` config. |
| `DATA_DIR` | `/data` | SQLite and metadata cache. |
| `DB_PATH` | `/data/app.db` | SQLite path override. |
| `STATIC_DIR` | unset | Built admin UI directory. |
| `STEAMPIPE_HOST` | `steampipe` | Steampipe hostname. |
| `STEAMPIPE_PORT` | `9193` | Steampipe PostgreSQL port. |
| `STEAMPIPE_DB_PASSWORD` | unset | Steampipe password. |
| `STEAMPIPE_CONFIG_DIR` | `/home/steampipe/.steampipe/config` | Generated `.spc` directory. |
| `CUBE_MODEL_DIR` | `/cube/conf/model` | Active Cube models. |
| `CUBE_API_URL` | `http://cube:4000/cubejs-api` | Cube REST base URL. |
| `CUBE_API_SECRET` | deployment value | Cube JWT secret. |
| `SETTRA_PUBLIC_URL` | request-derived | OAuth issuer and audience. |
| `SETTRA_OAUTH_ENABLED` | `false` locally | Protect `/mcp` with OAuth. |
| `SETTRA_OAUTH_ADMIN_USER` | `settra` | Admin OAuth username. |
| `SETTRA_OAUTH_ADMIN_PASSWORD` | unset | Admin OAuth password. |
| `MCP_ALLOWED_HOSTS` | localhost defaults | MCP transport allowed hosts. |
| `MCP_ALLOWED_ORIGINS` | localhost defaults | MCP transport allowed origins. |
| `SECRET_KEY` | development value | General signing material. |

Compose image variables remain `IMAGE`, `STEAMPIPE_IMAGE`, `CUBE_IMAGE`,
`STEAMPIPE_VERSION`, `LOCAL_PLATFORM`, `DEPLOY_PLATFORM`, and
`PUBLISH_PLATFORMS`.

## Model files

The source configuration lives at:

```text
connectors/googlesheets/connection.yaml
connectors/googlesheets/semantics.yaml
```

For a spreadsheet named `Sales Forecast` with slug `sales_forecast`, Settra
rewrites template schemas such as:

```text
"googlesheets"."googlesheets_cell"
```

to:

```text
"sales_forecast"."googlesheets_cell"
```

and prefixes cube names when needed to keep multiple connected spreadsheets
distinct. Generated model metadata records connection id, name, slug, and the
Google Sheets source key.

The MCP router is a package at `backend/app/routers/mcp/`. Keep one public tool
per module, shared helpers in `common.py`, resources in `resources.py`, and
assembly in `server.py`. Compact response policies live in
`backend/app/cube/projection.py`.

## SQLite

SQLite schema creation and migrations live in `backend/app/db.py`.

- `connections` stores spreadsheet names, slugs, the fixed `googlesheets`
  source marker, and status. Credentials remain in `.spc` files.
- `mcp_requests` stores request names, timing, status, sizes, and estimated token
  counts, never payload contents.
- OAuth tables store registered clients, short-lived codes, and hashed rotating
  refresh tokens. Access tokens are signed and not stored.

Legacy rows whose `plugin` is not `googlesheets` are ignored by runtime APIs,
diagnostics, model generation, and MCP discovery.

## Development

```bash
cd frontend && npm install
cd ../backend && pip install -r requirements.txt
cd ..

make init
make dev
```

Other useful commands:

```bash
make run
make run-build
make build
make build-steampipe
make down
docker compose logs -f app
docker compose logs -f cube
docker compose logs -f steampipe
docker compose exec app python -m app.init
```

For documentation-only changes, run `git diff --check`.
