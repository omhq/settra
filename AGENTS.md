# Settra — agent and developer reference

Settra is a self-hosted MCP server that makes durable snapshots of Google Drive
tabular files available to automated agents. Supported sources are native Google
Sheets, CSV, Excel, and Parquet files selected through Google Picker. dlt
performs complete loads into PostgreSQL, Cube Core is the canonical semantic
layer, and the MCP surface exposes bounded discovery plus Cube REST queries.

## Guardrails

- Keep Google Drive as the only source provider. Supported tabular formats are
  Google Sheets, CSV, Excel, and Parquet. Do not add provider selection,
  third-party source plugins, or cross-provider examples.
- Keep MCP clients on the Cube semantic contract. Tools inspect Cube metadata or
  execute Cube REST query JSON; they do not accept raw PostgreSQL SQL.
- Keep Cube Core as the only semantic layer.
- Do not ship default Cube models or semantic overlay files. Every active model
  must come from a successful user-source sync or an explicitly authored
  user-specific overlay.
- Active source models are generated under
  `/cube/conf/model/generated/connections` from successful sync manifests.
- Source-specific semantic edits live at runtime under
  `/cube/conf/model/overlays`. Agent-generated overlays are restricted to
  `/cube/conf/model/overlays/generated`.
- `/api/query/` accepts Cube REST query JSON. It is not a SQL endpoint.
- A Settra-owned PostgreSQL schema stores users, organizations, memberships,
  hashed browser sessions, source connection metadata, sync-run summaries,
  collections, OAuth state, and privacy-safe MCP metrics.
  Google credentials and MCP payload contents are not stored there.
- Google OAuth secrets are encrypted with `SECRET_KEY` on the data volume and
  never written to source YAML or generated Cube YAML.
- Sources, destinations, and pipes are separate concepts. Each pipe references
  one registered destination and owns one fixed namespace within it. Sync YAML
  may describe that binding but may not redirect the pipe around its database
  `destination_id` or fixed destination schema.

## Architecture

```text
Google Drive API + Google Sheets API
        |
        | file-specific OAuth via Google Picker
        v
FastAPI + dlt (:8000)
        |
        | full replace, insert-from-staging
        v
PostgreSQL (:5432)
        |
        v
Cube Core (:4000)
        |
        v
/mcp streamable HTTP -> automated agent / MCP client
```

The FastAPI process also owns the lean cron scheduler, Google OAuth flow,
per-source YAML validation, schema introspection, generated Cube models, MCP
metadata/sample/profile tools, and Cube REST proxy. No separate scheduler or
loader container is required.

The signed-in workspace's **Data** area manages its Google account, tabular-file pipes,
sync state and configuration, synchronized schemas, and collections. It presents
the destination separately on every pipe. The only current choice is the default
built-in PostgreSQL destination, configured by deployment environment variables.

## Google Drive tabular loading behavior

Each saved connection is a pipe from one Drive `file_id` to one registered
destination. The current built-in PostgreSQL destination assigns a stable schema
initially named from the connection slug. A sync:

1. Decrypts the saved Google refresh token in process.
2. Constructs a dlt `GcpOAuthCredentials` object and refreshes access as needed.
3. Inspects Drive metadata and detects Google Sheets, CSV, Excel, or Parquet.
   User-authored YAML may override the detected format.
4. Reads native Sheets through the Sheets API and downloads blob files through
   the Drive API. CSV delimiter, encoding, and header row are detected initially
   and persisted to YAML unless explicitly configured. Excel uses one table per
   selected worksheet; Parquet uses its embedded schema.
5. Applies YAML table/column rules and loads every enabled table with
   `write_disposition: replace` and
   `replace_strategy: insert-from-staging`. Empty, headerless, and disabled
   tables are skipped.
6. Removes previously managed tables that are no longer selected.
7. Applies PostgreSQL table/column comments.
8. Writes a privacy-safe manifest, refreshes bounded metadata, and regenerates
   Cube YAML.

The adapter currently reads each selected table into memory. Downloaded blob
contents are transient and are not written to the data volume. Add disk-backed
staging only for a concrete large-file or replay requirement; PostgreSQL is the
durable copy.

Per-source config lives at `/data/connections/<storage-key>.yaml`. The storage
key is globally unique while the displayed slug is organization-local. Example:

```yaml
version: 1
source:
  type: google_drive
  file_id: 1AbC_example
  file_name: sales_forecast.csv
  mime_type: text/csv
  format: csv
  sheets: [Orders, "Forecast *"]
  parsing:
    delimiter: comma
    encoding: utf-8-sig
    header_row: 1
destination:
  key: built_in_postgres
  type: postgres
  schema: sales_forecast
load:
  write_disposition: replace
  replace_strategy: insert-from-staging
  schema_contract:
    tables: evolve
    columns: evolve
    data_type: evolve
  schedule:
    enabled: true
    cron: "0 * * * *"
    timezone: UTC
schema:
  tables:
    Orders:
      table_name: orders
      description: One row per order
      columns:
        Order ID:
          name: order_id
          data_type: bigint
          description: Stable order identifier
        Ordered On:
          data_type: date
          description: Timezone-neutral business date
```

Table and column rules also accept `enabled: false`. Columns accept
`nullable: false`. Supported dlt type overrides are `binary`, `text`, `bigint`,
`double`, `bool`, `timestamp`, `date`, `decimal`, and `json`.

Allowed `source.format` values are `auto`, `google_sheets`, `csv`, `excel`, and
`parquet`. Delimiter, encoding, and header row may remain `auto`; a per-table
`header_row` overrides the source default.

For timezone-neutral dates in Cube, set
`meta.settra.semantic_type: business_date`; `query_cube` renders those values as
`YYYY-MM-DD` so clients do not apply viewer-local timezone shifts.

## MCP surface

The server is mounted at `/mcp` using streamable HTTP; `/mcp` normalizes to
`/mcp/`. MCP access requires a user-bound OAuth bearer token carrying the active
organization. The provider publishes discovery under `/.well-known/*` and
endpoints under `/oauth/*`. The global MCP URL starts with collection
discovery. `/mcp/collections/{slug}` is an optional pinned URL that injects the
collection into scoped tool calls while using the same server runtime.

Available tools:

| Tool | Purpose |
| --- | --- |
| `list_collections` | List compact logical pipe collections. |
| `get_collection_context` | Load one collection's instructions, pipes, destination tables, and cubes. |
| `list_cubes` | Search a bounded catalog of compiled cubes. |
| `get_cube` | Fetch one compact semantic definition. |
| `query_cube` | Execute one bounded Cube REST query object. |
| `get_cube_meta` | Search compact Cube `/v1/meta` detail. |
| `list_connections` | List connected Google Drive tabular files without secrets. |
| `get_connection_metadata` | Discover bounded synchronized tables and columns. |
| `sample_connection_table` | Fetch compact positional PostgreSQL snapshot rows. |
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
| `settra://collections/{collection}/semantics/meta` | Compiled metadata filtered to one collection. |
| `settra://collections/{collection}/semantics/cubes` | First collection cube page. |
| `settra://collections/{collection}/semantics/cubes/{name}` | Compact collection cube or view. |
| `settra://collections/{collection}/semantics/model/{path}` | Collection-bounded Cube YAML file. |

For the model-file resource, percent-encode slashes inside nested `{path}`
values. For example, use
`generated%2Fconnections%2Fsales_forecast.yaml`, not
`generated/connections/sales_forecast.yaml`.

## HTTP API

Except for registration configuration, registration, login, the Google OAuth
callback, and product naming, `/api` routes require an HTTP-only browser session.
Unsafe session-authenticated methods also require the matching CSRF cookie/header.

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/api/auth/config` | Return public registration availability. |
| `POST` | `/api/auth/register` | Create an account and private personal organization. |
| `POST` | `/api/auth/login` | Create an HTTP-only browser session. |
| `POST` | `/api/auth/logout` | Revoke the active browser session. |
| `GET` | `/api/auth/me` | Return the signed-in user and active organization. |
| `GET` | `/api/health` | PostgreSQL destination connectivity. |
| `GET` | `/api/destinations` | List registered load destinations without secrets. |
| `GET` | `/api/health/data` | Per-source loader diagnostics. |
| `POST` | `/api/health/data/{id}/refresh` | Perform a durable refresh. |
| `GET` | `/api/google-oauth/status` | Google app/account connection state. |
| `POST` | `/api/google-oauth/start` | Start the Google OAuth authorization flow. |
| `GET` | `/api/google-oauth/callback` | Exchange the Google authorization code. |
| `DELETE` | `/api/google-oauth` | Disconnect Google without deleting snapshots. |
| `POST` | `/api/google-picker/session` | Issue short-lived Picker configuration and access. |
| `GET` | `/.well-known/oauth-protected-resource` | Publish MCP protected-resource metadata. |
| `GET` | `/.well-known/oauth-authorization-server` | Publish OAuth authorization-server metadata. |
| `GET` | `/.well-known/openid-configuration` | Publish compatible OAuth discovery metadata. |
| `POST` | `/oauth/register` | Dynamically register an MCP OAuth client. |
| `GET/POST` | `/oauth/authorize` | Render or submit user-bound MCP authorization. |
| `POST` | `/oauth/token` | Exchange authorization codes or refresh tokens. |
| `GET/POST` | `/api/collections` | List or create logical pipe collections. |
| `GET/PUT/DELETE` | `/api/collections/{id}` | Read, update, or remove one collection. |
| `GET` | `/api/google-drive/config` | Google Drive tabular-source form configuration. |
| `GET` | `/api/google-drive/documentation` | Google Drive source setup guide. |
| `GET/POST` | `/api/connections` | List or create Drive tabular-file sources. |
| `GET/PUT/DELETE` | `/api/connections/{id}` | Read, update, or remove one source. |
| `GET` | `/api/connections/{id}/secrets` | Return an empty legacy-compatibility secret payload. |
| `POST` | `/api/connections/{id}/retry` | Retry a failed or pending source sync. |
| `POST` | `/api/connections/{id}/sync` | Run one complete dlt load. |
| `GET` | `/api/connections/{id}/sync-runs` | Read bounded sync history. |
| `GET/PUT` | `/api/connections/{id}/sync-config` | Read or validate/write source YAML. |
| `POST` | `/api/connections/{id}/metadata` | Refresh PostgreSQL schema metadata. |
| `POST` | `/api/query/` | Execute Cube REST query JSON. |
| `GET` | `/api/semantics/model` | Inspect the active model summary. |
| `POST` | `/api/semantics/model/sync` | Regenerate connection models from successful manifests. |
| `GET` | `/api/semantics/model/files` | List allowed Cube YAML files. |
| `GET/PUT/DELETE` | `/api/semantics/model/files/{path}` | Manage allowed Cube YAML files. |
| `GET` | `/api/semantics/meta` | Proxy Cube `/v1/meta`. |
| `GET` | `/api/requests` | Privacy-safe MCP request metrics. |
| `GET` | `/api/settings` | Deployment and MCP OAuth settings. |
| `GET` | `/api/settings/product` | Return the build-time product name without caching. |

## Configuration

Defaults below distinguish a directly started application from this repository's
Docker Compose deployment. “Same” means Compose does not override the
application default. Blank `APP_DB_*` Compose values deliberately trigger the
documented inheritance.

| Variable | Application default | Compose default | Purpose |
| --- | --- | --- | --- |
| `PRODUCT_NAME` | `Settra` | `Settra` | User-facing product name. |
| `CONFIG_DIR` | `/config` | same | Configuration root. |
| `CONNECTORS_DIR` | derived | `/config/connectors` | Directory containing `googledrive/` config. |
| `DATA_DIR` | `/data` | `/data` | Encrypted secrets, configs, manifests, and dlt state. |
| `CONNECTION_CONFIG_DIR` | `/data/connections` | `/data/connections` | Per-source YAML and manifest directory. |
| `DLT_PIPELINES_DIR` | `/data/dlt` | `/data/dlt` | dlt pipeline state directory. |
| `STATIC_DIR` | unset | `/opt/static` | Built admin UI directory. |
| `LOG_LEVEL` | `INFO` | `INFO` | Backend logging threshold. |
| `CORS_ALLOWED_ORIGINS` | `*` | same | Comma-separated browser CORS origins. |
| `POSTGRES_HOST` | `postgres` | `postgres` | Durable destination hostname. |
| `POSTGRES_PORT` | `5432` | `5432` | Durable destination port. |
| `POSTGRES_DATABASE` | `settra` | `settra` | Durable destination database. |
| `POSTGRES_USER` | `settra` | `settra` | Loader and Cube database user. |
| `POSTGRES_PASSWORD` | `settra` | `settra-dev-password` | Loader and Cube database password. |
| `APP_DB_HOST` | inherits `POSTGRES_HOST` | inherits | Optional product database hostname. |
| `APP_DB_PORT` | inherits `POSTGRES_PORT` | inherits | Optional product database port. |
| `APP_DB_DATABASE` | inherits `POSTGRES_DATABASE` | inherits | Optional product database name. |
| `APP_DB_USER` | inherits `POSTGRES_USER` | inherits | Optional product database user. |
| `APP_DB_PASSWORD` | inherits `POSTGRES_PASSWORD` | inherits | Optional product database password. |
| `APP_DB_SCHEMA` | `settra_app` | `settra_app` | Product-owned PostgreSQL schema managed by Alembic. |
| `GOOGLE_OAUTH_CLIENT_ID` | unset | unset | Google Web OAuth client ID. |
| `GOOGLE_OAUTH_CLIENT_SECRET` | unset | unset | Google Web OAuth client secret. |
| `GOOGLE_OAUTH_REDIRECT_URI` | request-derived | request-derived | Exact Google callback URI override. |
| `GOOGLE_CLOUD_PROJECT` | unset | unset | Optional Google Cloud project ID for dlt credentials. |
| `GOOGLE_PICKER_API_KEY` | unset | unset | Browser-restricted key for Google Picker API. |
| `GOOGLE_PICKER_APP_ID` | unset | unset | Numeric Google Cloud project number used by Picker. |
| `FRONTEND_URL` | unset | unset | Optional separate browser UI origin, such as the Vite dev server. |
| `GOOGLE_OAUTH_CREDENTIALS_PATH` | `/data/secrets/google_oauth.enc` | same | Legacy credential path; active encrypted credentials live under its `organizations/` sibling. |
| `CUBE_CONF_DIR` | `/cube/conf` | same | Cube configuration root. |
| `CUBE_MODEL_DIR` | `/cube/conf/model` | `/cube/conf/model` | Active Cube models. |
| `CUBE_API_URL` | `http://cube:4000/cubejs-api` | same | Cube REST base URL. |
| `CUBE_API_SECRET` | unset | `cube-dev-secret-change-me` | Cube JWT secret. |
| `CUBE_API_TIMEOUT_SECONDS` | `10` | same | Per-request Cube HTTP timeout. |
| `CUBE_QUERY_CONTINUE_WAIT_ATTEMPTS` | `8` | same | Maximum Cube continue-wait retries. |
| `CUBE_QUERY_CONTINUE_WAIT_SLEEP_SECONDS` | `1` | same | Seconds between Cube continue-wait retries. |
| `PUBLIC_URL` | request-derived | `http://localhost:8000` | MCP OAuth issuer and Google callback origin. |
| `REGISTRATION_ENABLED` | `true` | `true` | Allow new account and personal-workspace registration. |
| `APP_SESSION_TTL_SECONDS` | `2592000` | `2592000` | Browser-session lifetime. |
| `APP_SESSION_COOKIE_SECURE` | inferred from `PUBLIC_URL` | inferred | Require HTTPS for browser session and CSRF cookies. |
| `MCP_OAUTH_ENABLED` | `true` | `true` | Require user-bound OAuth for `/mcp`; disabling it disables MCP access rather than exposing tenants. |
| `SETTRA_OAUTH_SCOPES` | `settra:read settra:write` | same | Space- or comma-separated supported MCP OAuth scopes. |
| `SETTRA_OAUTH_REDIRECT_HOSTS` | `chatgpt.com` | same | Comma-separated dynamic-client redirect hosts. |
| `SETTRA_OAUTH_RESOURCE` | public origin | same | Optional OAuth protected-resource identifier. |
| `MCP_OAUTH_TOKEN_TTL_SECONDS` | `3600` | `3600` | Access-token lifetime. |
| `MCP_OAUTH_REFRESH_TOKEN_TTL_SECONDS` | `2592000` | `2592000` | Refresh-token lifetime. |
| `SETTRA_OAUTH_CODE_TTL_SECONDS` | `300` | same | Authorization-code lifetime. |
| `MCP_ALLOWED_HOSTS` | empty list | local loopback hosts | Complete comma-separated MCP transport Host allowlist. |
| `MCP_ALLOWED_ORIGINS` | empty list | local HTTP loopback origins | Complete comma-separated MCP transport Origin allowlist. |
| `MCP_REQUEST_HISTORY_LIMIT` | `10000` | same | Maximum retained privacy-safe MCP metric rows, with a minimum of 100. |
| `SEMANTIC_OVERLAY_COMPILE_ATTEMPTS` | `10` | same | Maximum overlay compile-status checks. |
| `SEMANTIC_OVERLAY_COMPILE_SLEEP_SECONDS` | `0.5` | same | Seconds between overlay compile-status checks. |
| `SECRET_KEY` | `dev-secret-change-me` | same | OAuth signing and Google secret encryption material. |

The Compose loopback allowlists are the exact values shown in `.env.example`:
`127.0.0.1,127.0.0.1:*,localhost,localhost:*,[::1],[::1]:*` for hosts and
`http://127.0.0.1,http://127.0.0.1:*,http://localhost,http://localhost:*,http://[::1],http://[::1]:*`
for origins. Setting either variable replaces its corresponding entire list;
the application does not append implicit defaults.

Compose image variables are `IMAGE`, `CUBE_IMAGE`, `POSTGRES_IMAGE`,
`LOCAL_PLATFORM`, `DEPLOY_PLATFORM`, and `PUBLISH_PLATFORMS`.

## Model files

The source form configuration lives at:

```text
connectors/googledrive/connection.yaml
```

No semantic YAML is packaged with Settra. After a successful load, Settra writes
`/data/connections/<storage-key>.manifest.yaml` and generates one Cube per synchronized
table in `/cube/conf/model/generated/connections/<storage-key>.yaml`. Generated metadata
records connection id/name/slug, Google source key, original tab, storage type,
and manifest time. Workspace overlays are created dynamically under
`/cube/conf/model/overlays/generated/organizations/<organization-id>` and persist
in the shared Cube runtime volume.

The MCP router is a package at `backend/app/routers/mcp/`. Keep one public tool
per module, shared helpers in `common.py`, resources in `resources.py`, and
assembly in `server.py`. Compact response policies live in
`backend/app/cube/projection.py`.

## Product database

Alembic migrations live in `backend/alembic/versions`. Runtime product queries
use an asyncpg pool scoped to `APP_DB_SCHEMA`; dlt continues to own each pipe's
registered destination namespace. Startup upgrades the product schema before
loading Cube models.

- `destinations` stores stable destination identity, type, non-secret
  configuration mode, and built-in/default flags. The seeded
  `built_in_postgres` record resolves credentials from `POSTGRES_*` at runtime.
- `users`, `organizations`, `organization_memberships`, and `user_sessions`
  establish the tenant boundary. Each signup creates one personal organization;
  sessions retain an active organization so shared organizations can be added
  without changing object ownership.
- `connections` stores source names, slugs, the fixed `googledrive` source
  marker, organization ownership, a globally unique storage key, destination
  foreign key and fixed target schema, status, and latest sync status fields. A
  connection is the durable source-to-destination pipe.
- `sync_runs` stores trigger, timing, status, table/row counts, dlt load IDs, and
  errors, never sheet values or credentials.
- `collections` stores organization-local names, slugs, descriptions, and agent
  instructions. `collection_pipes` stores only reusable pipe memberships;
  destination tables and cubes are always derived from each pipe.
- `mcp_requests` stores request names, timing, status, sizes, and estimated token
  counts, never payload contents.
- MCP OAuth tables store registered clients plus user- and organization-bound
  short-lived codes and hashed rotating refresh tokens. Access tokens are signed
  and not stored.

Rows whose `plugin` is not `googledrive` are ignored by runtime APIs,
diagnostics, model generation, and MCP discovery.

## Development

```bash
cd frontend && npm install
cd ../backend && pip install -r requirements.txt
cd ..

make dev
```

`make dev` starts PostgreSQL, the backend, Cube, and the frontend development
server. Backend startup applies Alembic migrations and synchronizes the Cube
model automatically. The `make init` target uses `--no-deps`; use it only when
the PostgreSQL service is already running.

Other useful commands:

```bash
make run
make run-build
make build
make down
docker compose logs -f app
docker compose logs -f cube
docker compose logs -f postgres
docker compose exec app python -m app.init
docker compose exec app python -m unittest discover -s tests -v
```

For documentation-only changes, run `git diff --check`.
