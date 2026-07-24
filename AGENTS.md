# Settra - Agent & Developer Reference

Settra is a self-hosted MCP server for business applications. It connects to
external apps through Steampipe, uses Cube Core as the canonical semantic layer,
and exposes trusted business-app metadata and query execution through MCP.

## Agent Guardrails

- Keep MCP clients on the Cube semantic contract. MCP tools should inspect Cube
  metadata or execute Cube REST query JSON, not raw Steampipe SQL.
- Keep Cube Core as the only semantic layer.
- User-facing semantic edits belong in Cube YAML files under
  `/cube/conf/model`. Bundled `connectors/*/semantics.yaml` files are templates;
  active connection models are generated under
  `/cube/conf/model/generated/connections`, and workspace overlays live under
  `semantic_overlays/*.yaml`.
- `/api/query/` accepts Cube REST query JSON. It is not a direct SQL endpoint.
- SQLite stores saved connection metadata and privacy-safe MCP request metrics.
  Connector credentials and MCP payload contents are not stored in SQLite;
  credentials are rendered to Steampipe `.spc` files.

## Architecture

```text
MCP client
        |
        v
/mcp streamable HTTP
        |
        v
FastAPI backend (:8000)
        |
        +-- MCP tools and resources backed by Cube metadata and queries
        +-- httpx -> Cube REST API
        +-- aiosqlite -> /data/app.db
        |   connections, MCP request metrics
        +-- aiofiles -> /steampipe/config/*.spc
        |   connector credentials rendered as Steampipe config
        +-- asyncpg -> steampipe:9193
        |   FDW diagnostics and metadata checks
        +-- /cube/conf/model
            mounted Cube YAML model files

Admin browser
        |
        v
FastAPI backend (:8000)
        |
        +-- /api/connectors, /api/connections, /api/health
        +-- /api/query, /api/semantics/model, /api/semantics/meta
        +-- optional static admin app from STATIC_DIR

Cube Core (:4000)
        |
        +-- reads /cube/conf/model
        +-- connects to Steampipe with the Postgres driver
        +-- exposes metadata and query results at /cubejs-api/v1

Steampipe service (:9193)
        |
        +-- reads /home/steampipe/.steampipe/config/*.spc
        +-- installs plugins declared by connectors/*/connection.yaml
        +-- exposes each saved connection as a PostgreSQL FDW schema
```

Steampipe is the bundled query adapter. Cube Core owns the semantic contract
above it.

## MCP Surface

The MCP server is mounted at `/mcp` using streamable HTTP. `/mcp` is normalized
to `/mcp/` by the FastAPI app. Public deployments should protect `/mcp` with
OAuth bearer-token authentication; the built-in single-admin OAuth provider
publishes discovery metadata under `/.well-known/*` and endpoints under
`/oauth/*`. It issues hashed, rotating refresh tokens and revokes a refresh-token
family when reuse is detected.

MCP clients should prefer existing compiled cubes and measures, inspect bounded
metadata/profile evidence before proposing cross-app relationships, and create
semantic overlays only after explicit user approval. Generated overlays should
preserve their purpose, grain, assumptions, relationship rules, metric
definitions, evidence, and validation results.
Read-only discovery covers hand-authored and generated overlays, including files
that did not compile. MCP create and update operations are restricted to
`/cube/conf/model/overlays/generated`. Deletion is a manual admin UI action.

Available tools:

| Tool                        | Description                                                                                                                                       |
| --------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------- |
| `list_cubes`                | Search a bounded, paginated catalog of compiled cubes; member previews are opt-in and capped, and `get_cube` provides compact one-cube semantics. |
| `get_cube`                  | Fetch one compact semantic definition with source, SQL, filters, references, relationships, and non-default behavior.                             |
| `query_cube`                | Execute one bounded Cube REST query object and return one compact data page with sentinel-based continuation fields; exact totals are opt-in.    |
| `get_cube_meta`             | Search compact, bounded Cube `/v1/meta` detail; member collections are opt-in, capped, and stripped of default UI fields.                         |
| `list_connections`          | List saved Settra connections without secrets, including slugs used in generated cube names and schemas.                                          |
| `get_connection_metadata`   | Search a bounded live-table catalog; the first ten columns per table are included by default, with table and column cursor pagination.            |
| `sample_connection_table`   | Fetch compact positional rows with column names once; scalar truncation metadata appears only when truncation occurred.                           |
| `profile_connection_table`  | Return a compact sampled profile keyed by column name; descriptions are opt-in and bounded, and differing source/inferred types are preserved.    |
| `list_semantic_overlays`    | List compact overlay summaries with path, models, compile state, manifest state, and purpose.                                                     |
| `get_semantic_overlay`      | Read exact overlay YAML once with compact compile status and missing manifest fields; use `get_cube` for compiled semantics.                      |
| `validate_semantic_overlay` | Dry-run proposed Cube YAML; pass the existing generated path for replacements; failures include compiler diagnostics.                            |
| `create_semantic_overlay`   | Create a validated and approved generated overlay and return compact manifest/compile status; fail if the path already exists.                    |
| `update_semantic_overlay`   | Replace an existing validated and approved generated overlay; return a diff summary by default and the full diff only when requested.             |
| `save_semantic_overlay`     | Deprecated generated-overlay upsert retained for compatibility; prefer create or update.                                                          |

Available resources:

| Resource                          | Description                                       |
| --------------------------------- | ------------------------------------------------- |
| `settra://semantics/meta`         | Raw compiled Cube `/v1/meta` metadata.            |
| `settra://semantics/cubes`        | First fixed page; use `list_cubes` to paginate.   |
| `settra://semantics/cubes/{name}` | Compact semantic definition by cube or view name. |
| `settra://semantics/model/{path}` | Mounted Cube YAML model file by path.             |

## Active HTTP API

| Method     | Path                                      | Description                                                          |
| ---------- | ----------------------------------------- | -------------------------------------------------------------------- |
| `GET`      | `/api/health`                             | Steampipe connectivity check.                                        |
| `GET`      | `/api/health/fdw`                         | Per-connection FDW diagnostics.                                      |
| `POST`     | `/api/health/fdw/{id}/refresh`            | Refresh Steampipe metadata cache.                                    |
| `POST`     | `/api/health/steampipe/restart`           | Restart Steampipe when configured.                                   |
| `GET`      | `/api/connectors`                         | List connector definitions.                                          |
| `GET`      | `/api/connections`                        | List saved app connections.                                          |
| `POST`     | `/api/connections`                        | Create a saved app connection and render its `.spc` file.            |
| `GET`      | `/api/connections/{id}`                   | Fetch one saved app connection.                                      |
| `PUT`      | `/api/connections/{id}`                   | Update a saved app connection and its `.spc` file.                   |
| `DELETE`   | `/api/connections/{id}`                   | Delete a saved app connection and remove its `.spc` file.            |
| `GET`      | `/api/connections/{id}/secrets`           | Return saved secret credential values from the rendered `.spc` file. |
| `POST`     | `/api/connections/{id}/retry`             | Re-validate connection credentials and FDW state.                    |
| `POST`     | `/api/connections/{id}/metadata`          | Fetch live Steampipe metadata.                                       |
| `POST`     | `/api/query/`                             | Execute Cube REST query JSON.                                        |
| `GET`      | `/api/semantics/model`                    | List Cube model files and Cube metadata status.                      |
| `POST`     | `/api/semantics/model/sync`               | Refresh the mounted Cube model file view.                            |
| `GET`      | `/api/semantics/model/files`              | List editable Cube model files.                                      |
| `GET`      | `/api/semantics/model/files/{path}`       | Read a Cube YAML model file.                                         |
| `PUT`      | `/api/semantics/model/files/{path}`       | Update a Cube YAML model file.                                       |
| `DELETE`   | `/api/semantics/model/files/{path}`       | Delete a generated overlay after user confirmation in the admin UI.  |
| `GET`      | `/api/semantics/meta`                     | Proxy Cube `/v1/meta` metadata.                                      |
| `GET`      | `/api/requests`                           | List retained MCP request metrics and token estimates.               |
| `GET`      | `/.well-known/oauth-protected-resource`   | OAuth protected-resource metadata for MCP clients.                   |
| `GET`      | `/.well-known/oauth-authorization-server` | OAuth authorization-server metadata.                                 |
| `POST`     | `/oauth/register`                         | Dynamic client registration for OAuth-capable MCP clients.           |
| `GET/POST` | `/oauth/authorize`                        | Single-admin authorization-code + PKCE login flow.                   |
| `POST`     | `/oauth/token`                            | Authorization-code token exchange.                                   |

## Environment

Backend environment variables:

| Variable                                 | Default                                                                     | Description                                                                              |
| ---------------------------------------- | --------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------- |
| `CONFIG_DIR`                             | `/config`                                                                   | Base directory for mounted configuration.                                                |
| `CONNECTORS_DIR`                         | Derived from `CONFIG_DIR`, then repo fallback                               | Connector definitions and bundled Cube YAML files.                                       |
| `DATA_DIR`                               | `/data`                                                                     | SQLite and metadata cache directory.                                                     |
| `DB_PATH`                                | `/data/app.db`                                                              | Optional SQLite path override.                                                           |
| `STATIC_DIR`                             | unset                                                                       | Optional static admin app directory; `/opt/static` and `static` are fallback candidates. |
| `STEAMPIPE_HOST`                         | `steampipe`                                                                 | Steampipe service hostname.                                                              |
| `STEAMPIPE_PORT`                         | `9193`                                                                      | Steampipe PostgreSQL port.                                                               |
| `STEAMPIPE_DB_PASSWORD`                  | unset in code; `steampipe_pass` in compose                                  | Password for the Steampipe DB user.                                                      |
| `STEAMPIPE_CONFIG_DIR`                   | `/home/steampipe/.steampipe/config` in code; `/steampipe/config` in compose | Where `.spc` files are written.                                                          |
| `STEAMPIPE_RESTART_COMMAND`              | unset                                                                       | Optional restart command for non-Docker deployments.                                     |
| `STEAMPIPE_RESTART_TIMEOUT_SECONDS`      | `120`                                                                       | Restart command timeout.                                                                 |
| `CUBE_CONF_DIR`                          | `/cube/conf`                                                                | Cube configuration directory.                                                            |
| `CUBE_MODEL_DIR`                         | `/cube/conf/model`                                                          | Directory containing Cube model files.                                                   |
| `CUBE_API_URL`                           | `http://cube:4000/cubejs-api`                                               | Backend-to-Cube REST API base URL.                                                       |
| `CUBE_API_SECRET`                        | unset in code; `cube-dev-secret-change-me` in compose                       | Secret used to sign Cube API JWTs.                                                       |
| `CUBE_API_TIMEOUT_SECONDS`               | `10`                                                                        | Cube REST request timeout.                                                               |
| `CUBE_QUERY_CONTINUE_WAIT_ATTEMPTS`      | `8`                                                                         | Poll attempts when Cube returns a continue-wait response.                                |
| `CUBE_QUERY_CONTINUE_WAIT_SLEEP_SECONDS` | `1`                                                                         | Delay between Cube continue-wait polls.                                                  |
| `SETTRA_PUBLIC_URL`                      | derived from request if unset                                               | Public origin used as OAuth issuer and resource audience.                                |
| `SETTRA_OAUTH_ENABLED`                   | `false` locally; `true` on Hetzner                                          | Enables OAuth discovery, registration, token exchange, and `/mcp` bearer checks.         |
| `SETTRA_OAUTH_ADMIN_USER`                | `settra`                                                                    | Single-admin username for the built-in OAuth login page.                                 |
| `SETTRA_OAUTH_ADMIN_PASSWORD`            | unset                                                                       | Single-admin password for the built-in OAuth login page.                                 |
| `SETTRA_OAUTH_REDIRECT_HOSTS`            | `chatgpt.com`                                                               | Comma-separated allowlist for OAuth redirect hosts.                                      |
| `SETTRA_OAUTH_SCOPES`                    | `settra:read settra:write`                                                  | Space- or comma-separated scopes advertised and required for `/mcp`.                     |
| `SETTRA_OAUTH_TOKEN_TTL_SECONDS`         | `3600`                                                                      | Lifetime for signed MCP access tokens.                                                   |
| `SETTRA_OAUTH_REFRESH_TOKEN_TTL_SECONDS` | `2592000`                                                                   | Inactivity lifetime for rotating MCP OAuth refresh tokens.                               |
| `SETTRA_OAUTH_CODE_TTL_SECONDS`          | `300`                                                                       | Lifetime for one-time authorization codes.                                               |
| `MCP_ALLOWED_HOSTS`                      | localhost defaults                                                          | Comma-separated allowed hosts for MCP transport security.                                |
| `MCP_ALLOWED_ORIGINS`                    | localhost defaults                                                          | Comma-separated allowed origins for MCP transport security.                              |
| `MCP_REQUEST_HISTORY_LIMIT`              | `10000`                                                                     | Maximum retained MCP tool/resource request metric rows.                                  |
| `SECRET_KEY`                             | `dev-secret-change-me`                                                      | General secret key material.                                                             |
| `LOG_LEVEL`                              | `INFO`                                                                      | Backend log level.                                                                       |

Compose and Makefile variables:

| Variable            | Default                       | Description                                       |
| ------------------- | ----------------------------- | ------------------------------------------------- |
| `IMAGE`             | `omhq/settra:0.0.1`           | App image name.                                   |
| `STEAMPIPE_IMAGE`   | `omhq/settra-steampipe:0.0.1` | Steampipe image name.                             |
| `CUBE_IMAGE`        | `cubejs/cube:latest`          | Cube image name.                                  |
| `STEAMPIPE_VERSION` | `2.4.4`                       | Steampipe version used by `Dockerfile.steampipe`. |
| `LOCAL_PLATFORM`    | host-derived                  | Local Docker build platform.                      |
| `DEPLOY_PLATFORM`   | `linux/amd64,linux/arm64`     | Multi-platform deploy target.                     |
| `PUBLISH_PLATFORMS` | `$(DEPLOY_PLATFORM)`          | Multi-platform publish target.                    |

## Connectors

Connector definitions live at:

```text
connectors/<connector-key>/connection.yaml
```

Connector Cube models live next to them:

```text
connectors/<connector-key>/semantics.yaml
```

To add a connector, add its connector definition, add or update its Cube YAML
model, and rebuild or restart the Steampipe service so the plugin installer sees
the connector plugin declaration.

## Cube Model Files

Cube model files use Cube YAML directly. Bundled connector `semantics.yaml`
files are templates, not active live connection models. Settra generates active
connection-specific files under
`/cube/conf/model/generated/connections/<connection-slug>.yaml`, rewriting
`sql_table` schemas to the actual Steampipe connection slug and prefixing cube
names when needed to avoid collisions across multiple connections for the same
app. For example, a Stripe connection named `stripe_sandbox` generates
`stripe_sandbox_charge` with
`sql_table: '"stripe_sandbox"."stripe_charge"'`.

Workspace-specific cross-app models can live in `semantic_overlays/`, mounted
into Cube at `/cube/conf/model/overlays`.

Model file source types:

- `bundled_connector`: static connector semantics packaged from
  `connectors/<key>/semantics.yaml`; used as templates.
- `generated_connection`: active connection-specific model generated from a
  bundled connector template under `/cube/conf/model/generated/connections`.
- `overlay`: hand-authored workspace overlay under `/cube/conf/model/overlays`.
- `generated_overlay`: agent-generated, user-specific overlay under
  `/cube/conf/model/overlays/generated`.

Recommended MCP workflow for generated overlays:

1. Call `list_connections`.
2. Call `get_connection_metadata` for relevant connections.
3. Call `sample_connection_table` and `profile_connection_table` for
   user-specific or unfamiliar tables.
4. Inspect compiled semantics with `list_cubes` and `get_cube`, then discover
   authored and failed models with `list_semantic_overlays`.
5. Call `get_semantic_overlay` before extending or replacing an existing model.
6. Draft the smallest reusable Cube YAML overlay. On every declared cube or
   view, preserve `purpose`, `requirement`, `grain`, `assumptions`, and
   `evidence` under `meta.settra`; add relationships, metrics, validation, and
   approval details when relevant.
7. Call `validate_semantic_overlay` with the proposed YAML and representative
   Cube REST `test_queries`; for replacements, pass the existing generated
   overlay path.
8. Explain the validation result, warnings, assumptions, and any business
   decisions that still need approval.
9. Use `create_semantic_overlay` for a new approved path or
   `update_semantic_overlay` for an approved replacement.
10. Verify with `list_cubes`, `get_semantic_overlay`, and `query_cube`.
11. Ask the user to clean up failed experiments manually from the admin UI.

The MCP router is a package at `backend/app/routers/mcp/`. Keep one public tool
per module, shared server/path/manifest helpers in `common.py`, resource
registration in `resources.py`, and package assembly in `server.py`. Keep
compact MCP response policies in `backend/app/cube/projection.py`; pass typed
projection inputs instead of expanding raw Cube metadata in tool modules.
Tool responses omit normal defaults, empty optional metadata, and request
echoes. The server instructions define absent fields as defaults and direct
clients to use the original call arguments plus `total` and `next_cursor` for
pagination. Raw resources are intentionally exempt when their description says
they expose raw metadata.

For timezone-neutral business dates, mark the Cube member with
`meta.settra.semantic_type: business_date`; `query_cube` renders those values as
`YYYY-MM-DD` so clients do not shift them into viewer-local timezones.

Do not expose or rely on arbitrary raw Steampipe SQL for MCP clients. Use the
structured sample/profile tools for introspection and Cube REST query JSON for
execution.

Bundled connector files are templates. Active connection-specific model files
resolve `sql_table` schemas and generated cube names from saved connection
slugs.

## SQLite Schema

SQLite lives at `/data/app.db` backed by `./app_data` in local compose. Schema
creation and migrations live in `backend/app/db.py`.

Current table groups include:

- `connections` for saved connector metadata. Credentials are stored in
  Steampipe `.spc` files, not SQLite.
- `mcp_requests` for tool/resource names, timing, status, payload sizes, and
  estimated token counts. Request and response contents are not stored.
- `oauth_clients` and `oauth_authorization_codes` for MCP OAuth dynamic client
  registration and short-lived authorization codes. `oauth_refresh_tokens`
  stores hashed rotating refresh tokens and token-family state. Access tokens
  are signed with `SECRET_KEY`; they are not stored in SQLite.

## Development

```bash
# First-time setup
cd frontend && npm install
cd backend && pip install -r requirements.txt

# Initialize SQLite and verify mounted Cube model files
make init

# Full stack: frontend dev server plus Docker stack
make dev

# Docker stack only
make run

# Docker stack with rebuild
make run-build

# Rebuild app image
make build

# Rebuild Steampipe image
make build-steampipe

# Stop compose services
make down
```

Useful checks:

```bash
docker compose logs -f app
docker compose logs -f cube
docker compose logs -f steampipe
docker compose exec app python -m app.init
docker compose exec steampipe steampipe query "SELECT * FROM steampipe_internal.steampipe_connection"
```

When changing documentation only, run:

```bash
git diff --check -- README.md AGENTS.md
```
