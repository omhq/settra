# Settra

**Ask once. Keep the model.**

Settra gives AI assistants a governed analytics layer over live business
apps. Ask a question, then keep the resulting business model for every
question that follows.

## Architecture

Settra connects tools such as Google Sheets, Stripe, and HubSpot through
Steampipe, mounts Cube Core model files for those live app schemas, and exposes
trusted cubes, measures, dimensions, joins, segments, AI context, and query
execution through MCP. The agent does not need a complete data model before it
starts. It inspects the applications involved in a question, proposes the
required metrics and relationships, validates them, and saves them as
reusable semantics.

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
        +-- Cube REST API proxy and query execution
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
        +-- /api/semantics/model, /api/semantics/meta

Cube Core (:4000)
        |
        +-- reads /cube/conf/model
        +-- connects to Steampipe with the Postgres driver
        +-- exposes metadata and query results at /cubejs-api/v1

Steampipe (:9193)
        |
        +-- reads /home/steampipe/.steampipe/config/*.spc
        +-- installs plugins declared by connectors/*/connection.yaml
        +-- exposes each saved connection as a PostgreSQL FDW schema
```

## MCP Surface

Settra mounts its MCP server at `/mcp` using streamable HTTP. MCP clients use
Cube as the semantic contract; they do not query raw Steampipe tables directly.
The server instructions tell agents to prefer existing compiled cubes and
measures, inspect bounded metadata/profile evidence before proposing cross-app
relationships, and create semantic overlays only after explicit user approval.
Generated overlays should preserve their purpose, grain, assumptions,
relationship rules, metric definitions, evidence, and validation results.
Read-only discovery covers both hand-authored and generated overlays, including
files that did not compile. Agent writes are restricted to
`/cube/conf/model/overlays/generated`.

MCP tool responses omit normal defaults, empty optional metadata, and request
echoes. The server instructions define absent fields as defaults and direct
clients to use the original tool arguments plus `total` and `next_cursor` for
pagination. Resources explicitly described as raw are intentionally exempt.

Available tools:

| Tool                        | Purpose                                                                                                                                           |
| --------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------- |
| `list_cubes`                | Search a bounded, paginated catalog of compiled cubes; member previews are opt-in and capped, and `get_cube` provides compact one-cube semantics. |
| `get_cube`                  | Fetch one compact semantic definition with source, SQL, filters, references, relationships, and non-default behavior.                             |
| `query_cube`                | Execute one bounded Cube REST query object and return one compact data array; arrays and independent batching are not supported.                  |
| `get_cube_meta`             | Search compact, bounded Cube `/v1/meta` detail; member collections are opt-in, capped, and stripped of default UI fields.                         |
| `list_connections`          | List saved Settra connections without secrets, including slugs used in generated cube names and schemas.                                          |
| `get_connection_metadata`   | Search a bounded live-table catalog; the first ten columns per table are included by default, with table and column cursor pagination.            |
| `sample_connection_table`   | Fetch compact positional rows with column names once; scalar truncation metadata appears only when truncation occurred.                           |
| `profile_connection_table`  | Return a compact sampled profile keyed by column name; descriptions are opt-in and bounded, and differing source/inferred types are preserved.    |
| `list_semantic_overlays`    | List compact overlay summaries with path, models, compile state, manifest state, and purpose.                                                     |
| `get_semantic_overlay`      | Read exact overlay YAML once with compact compile status and missing manifest fields; use `get_cube` for compiled semantics.                      |
| `validate_semantic_overlay` | Dry-run proposed Cube YAML; successful results are compact, while failures include compiler diagnostics.                                          |
| `create_semantic_overlay`   | Create a validated, approved generated overlay and return compact manifest/compile status; fail if the path already exists.                       |
| `update_semantic_overlay`   | Replace an existing validated, approved generated overlay; return a diff summary by default and the full diff only when requested.                |
| `save_semantic_overlay`     | Deprecated generated-overlay upsert retained for older MCP clients; prefer create or update.                                                      |

Available resources:

| Resource                          | Purpose                                         |
| --------------------------------- | ----------------------------------------------- |
| `settra://semantics/meta`         | Raw compiled Cube metadata.                     |
| `settra://semantics/cubes`        | First fixed page; use `list_cubes` to paginate. |
| `settra://semantics/cubes/{name}` | Compact semantics for one cube or view.         |
| `settra://semantics/model/{path}` | Mounted Cube YAML model file content.           |

## Connectors

Connector definitions live in:

```text
connectors/<connector-key>/connection.yaml
```

Connector Cube models live next to them:

```text
connectors/<connector-key>/semantics.yaml
```

Those `semantics.yaml` files use Cube YAML directly, but they are templates.
When a saved connection exists, Settra generates an active connection-specific
Cube model under `/cube/conf/model/generated/connections/<connection-slug>.yaml`.
The generated file rewrites `sql_table` schemas to the actual Steampipe
connection slug and prefixes cube names when needed to avoid collisions across
multiple connections for the same app. For example, a Stripe connection named
`stripe_sandbox` generates cubes such as `stripe_sandbox_charge` with
`sql_table: '"stripe_sandbox"."stripe_charge"'`.

Workspace-specific cross-app models can live in `semantic_overlays/`, which is
mounted into Cube at `/cube/conf/model/overlays`.

Settra reports model file source types so clients can distinguish where semantic
definitions came from:

| Source type            | Meaning                                                                                                                      |
| ---------------------- | ---------------------------------------------------------------------------------------------------------------------------- |
| `bundled_connector`    | Static connector semantics packaged from `connectors/<key>/semantics.yaml`; used as templates, not live connection models.   |
| `generated_connection` | Active connection-specific model generated from a bundled connector template under `/cube/conf/model/generated/connections`. |
| `overlay`              | Hand-authored workspace overlay under `/cube/conf/model/overlays`.                                                           |
| `generated_overlay`    | Agent-generated, user-specific overlay under `/cube/conf/model/overlays/generated`.                                          |

Recommended MCP workflow for generated overlays:

1. Call `list_connections`.
2. Call `get_connection_metadata` for relevant connections.
3. Call `sample_connection_table` and `profile_connection_table` for
   user-specific or unfamiliar tables.
4. Inspect compiled semantics with `list_cubes` and `get_cube`, then call
   `list_semantic_overlays` to discover authored, failed, duplicate, or stale
   overlays.
5. Call `get_semantic_overlay` before extending or replacing an existing model.
6. Draft the smallest reusable Cube YAML overlay. Preserve provenance under
   each cube or view's `meta.settra` mapping.
7. Call `validate_semantic_overlay` with the proposed YAML and representative
   Cube REST `test_queries`.
8. Explain the validation result, warnings, assumptions, and any business
   decisions that still need approval.
9. Use `create_semantic_overlay` for a new approved path or
   `update_semantic_overlay` for an approved replacement.
10. Verify with `list_cubes`, `get_semantic_overlay`, and `query_cube`.
11. Ask the user to clean up failed experiments manually from the admin UI.

New or updated generated overlays require these provenance fields on every
declared cube or view. `relationships`, `metrics`, `validation`, and `approval`
should also be preserved when relevant:

```yaml
meta:
  settra:
    purpose: Compare revenue targets with matched actual revenue
    requirement: Show monthly target, actual, attainment, gap, and unmatched revenue
    grain: One row per month
    assumptions:
      - Stripe customers match HubSpot contacts by normalized email
    relationships:
      - from: stripe_customer.email
        to: hubspot_contact.email
        cardinality: many_to_one after HubSpot email deduplication
    evidence:
      matched_customers: 10
      unmatched_customers: 2
      revenue_coverage_percent: 98.4
```

The sample/profile tools are structured introspection tools, not raw SQL
execution. They are bounded, redact obvious secret-like columns, and reconstruct
Google Sheets virtual worksheet tables from `googlesheets_cell` so agents can
infer columns such as dates, owners, notes, and revenue targets before writing
Cube YAML.

## HTTP API

The HTTP API supports administration, diagnostics, Cube model editing, and
Cube-backed query execution:

| Method                | Path                                      | Description                                       |
| --------------------- | ----------------------------------------- | ------------------------------------------------- |
| `GET`                 | `/api/health`                             | Steampipe connectivity check.                     |
| `GET`                 | `/api/health/fdw`                         | Per-connection FDW diagnostics.                   |
| `POST`                | `/api/health/fdw/{id}/refresh`            | Refresh Steampipe metadata cache.                 |
| `POST`                | `/api/health/steampipe/restart`           | Restart Steampipe when configured.                |
| `GET`                 | `/api/connectors`                         | List connector definitions.                       |
| `GET/POST/PUT/DELETE` | `/api/connections...`                     | Manage saved app connections.                     |
| `POST`                | `/api/connections/{id}/retry`             | Re-validate connection credentials and FDW state. |
| `POST`                | `/api/connections/{id}/metadata`          | Fetch live Steampipe metadata.                    |
| `POST`                | `/api/query/`                             | Execute Cube REST query JSON.                     |
| `GET`                 | `/api/semantics/model`                    | List Cube model files and Cube metadata status.   |
| `POST`                | `/api/semantics/model/sync`               | Refresh the mounted Cube model file view.         |
| `GET/PUT`             | `/api/semantics/model/files/{path}`       | Read or update Cube YAML model files.             |
| `DELETE`              | `/api/semantics/model/files/{path}`       | Delete a generated overlay from the admin UI.     |
| `GET`                 | `/api/semantics/meta`                     | Proxy Cube `/v1/meta` metadata.                   |
| `GET`                 | `/api/requests`                           | List MCP request metrics and token estimates.     |
| `GET`                 | `/.well-known/oauth-protected-resource`   | OAuth protected-resource metadata for MCP.        |
| `GET`                 | `/.well-known/oauth-authorization-server` | OAuth authorization-server metadata.              |
| `POST`                | `/oauth/register`                         | Dynamic client registration for MCP OAuth.        |
| `GET/POST`            | `/oauth/authorize`                        | Single-admin authorization-code + PKCE flow.      |
| `POST`                | `/oauth/token`                            | Authorization-code token exchange.                |

## Configuration

Common environment variables:

| Variable                                 | Default                                | Purpose                                                     |
| ---------------------------------------- | -------------------------------------- | ----------------------------------------------------------- |
| `STEAMPIPE_HOST`                         | `steampipe`                            | Steampipe service hostname.                                 |
| `STEAMPIPE_PORT`                         | `9193`                                 | Steampipe PostgreSQL port.                                  |
| `STEAMPIPE_CONFIG_DIR`                   | `/steampipe/config` in compose         | Where connector `.spc` files are written.                   |
| `STEAMPIPE_DB_PASSWORD`                  | `steampipe_pass` in compose            | Password for the Steampipe PostgreSQL user.                 |
| `STEAMPIPE_RESTART_COMMAND`              | unset                                  | Optional restart command for non-Docker deployments.        |
| `STEAMPIPE_RESTART_TIMEOUT_SECONDS`      | `120`                                  | Restart command timeout.                                    |
| `CUBE_API_URL`                           | `http://cube:4000/cubejs-api`          | Backend-to-Cube REST API base URL.                          |
| `CUBE_API_SECRET`                        | `cube-dev-secret-change-me` in compose | Secret used to sign Cube REST API tokens.                   |
| `CUBE_MODEL_DIR`                         | `/cube/conf/model`                     | Directory where Cube model files live.                      |
| `DATA_DIR`                               | `/data`                                | SQLite data directory.                                      |
| `DB_PATH`                                | `/data/app.db`                         | SQLite database path.                                       |
| `CONNECTORS_DIR`                         | `/config/connectors`                   | Connector definitions and bundled Cube YAML files.          |
| `SECRET_KEY`                             | `dev-secret-change-me`                 | General secret key material.                                |
| `SETTRA_PUBLIC_URL`                      | derived from request if unset          | Public origin used as OAuth issuer and resource audience.   |
| `SETTRA_OAUTH_ENABLED`                   | `false` locally; `true` on Hetzner     | Enables OAuth for ChatGPT-compatible MCP access.            |
| `SETTRA_OAUTH_ADMIN_USER`                | `settra`                               | Single-admin username for the built-in OAuth login page.    |
| `SETTRA_OAUTH_ADMIN_PASSWORD`            | unset                                  | Single-admin password for the built-in OAuth login page.    |
| `SETTRA_OAUTH_REDIRECT_HOSTS`            | `chatgpt.com`                          | Comma-separated allowlist for OAuth redirect hosts.         |
| `SETTRA_OAUTH_SCOPES`                    | `settra:read settra:write`             | Space- or comma-separated scopes advertised for `/mcp`.     |
| `SETTRA_OAUTH_TOKEN_TTL_SECONDS`         | `3600`                                 | Lifetime for signed MCP access tokens.                      |
| `SETTRA_OAUTH_REFRESH_TOKEN_TTL_SECONDS` | `2592000`                              | Inactivity lifetime for rotating MCP OAuth refresh tokens.  |
| `SETTRA_OAUTH_CODE_TTL_SECONDS`          | `300`                                  | Lifetime for one-time authorization codes.                  |
| `LOG_LEVEL`                              | `INFO`                                 | Backend log level.                                          |
| `MCP_ALLOWED_HOSTS`                      | localhost defaults                     | Comma-separated allowed hosts for MCP transport security.   |
| `MCP_ALLOWED_ORIGINS`                    | localhost defaults                     | Comma-separated allowed origins for MCP transport security. |
| `MCP_REQUEST_HISTORY_LIMIT`              | `10000`                                | Maximum retained MCP request metric rows.                   |

## Local Development

```bash
# First-time setup
cd frontend && npm install
cd ../backend && pip install -r requirements.txt
cd ..

# Initialize SQLite and verify mounted Cube model files
make init

# Full development stack
make dev

# Docker stack only
make run
```

Useful commands:

```bash
# Rebuild the app image
make build

# Rebuild the Steampipe image
make build-steampipe

# Run backend initialization inside Docker
docker compose exec app python -m app.init

# Inspect Steampipe connections
docker compose exec steampipe steampipe query "SELECT * FROM steampipe_internal.steampipe_connection"

# Watch logs
docker compose logs -f app
docker compose logs -f cube
docker compose logs -f steampipe
```

## Semantic Layer

Cube Core is the canonical semantic layer.

1. A saved connection renders a Steampipe `.spc` file.
2. Cube reads the connector’s mounted `semantics.yaml` as Cube YAML.
3. Cube compiles the model and exposes metadata through `/cubejs-api/v1/meta`.
4. MCP clients inspect compiled metadata through MCP tools and resources.
5. MCP clients execute semantic queries through `query_cube`, which sends Cube
   REST query JSON to Cube.
6. Cube queries Steampipe’s FDW-backed PostgreSQL schemas and returns trusted
   semantic results.

## Deployment

Can run anywhere containers can run. The included Hetzner helper deploys
the app, Cube Core, Steampipe, and Caddy. It derives a public hostname from the
server IP using `sslip.io`, so a deployment works without owning a domain. Caddy
keeps Basic Auth in front of the admin UI and API, while `/mcp` uses OAuth
bearer-token authentication for ChatGPT and other OAuth-capable MCP clients.

## Deployment

Settra can run anywhere containers can run.

### Quick deploy on Hetzner

[![Deploy on Hetzner](https://img.shields.io/badge/Deploy%20on-Hetzner-D50C2D?logo=hetzner&logoColor=white)](https://console.hetzner.cloud/projects)

For now, the lowest cost Hetzner VPS is a CX23 x86 with 2 vCPUs, 4GB of RAM, and a 40GB SSD running
Ubuntu 26.04 for $5/month. It sits in Helsinki.

Install the hcloud cli and create a context:

- Install the cli however you want.
- From the Hetzner Console, go to Security -> API Tokens, and generate a token.
- Run `hcloud context create <context-name>` and paste in your token.

Create a local SSH key and upload the public key to Hetzner:

```bash
mkdir -p ~/.ssh
chmod 700 ~/.ssh
ssh-keygen -t ed25519 -C "settra-hetzner" -f ~/.ssh/settra_hetzner
hcloud ssh-key create \
  --name settra \
  --public-key-from-file ~/.ssh/settra_hetzner.pub
```

Deploy:

```bash
./deploy/hetzner/deploy.sh
```

When deploying images from your own DockerHub namespace, pass the same tags you
published:

```bash
SETTRA_IMAGE=<dockerhub-user>/settra:0.0.1 \
SETTRA_STEAMPIPE_IMAGE=<dockerhub-user>/settra-steampipe:0.0.1 \
./deploy/hetzner/deploy.sh
```

Connect using the private key:

```bash
hcloud server list # to get the server ip
ssh -i ~/.ssh/settra_hetzner root@<server-ip>
```

The server generates a temporary `sslip.io` HTTPS hostname and Basic Auth
credentials on first boot. Get them here `cat /opt/settra/credentials.txt`.

Open the printed Settra URL in a browser. The React app and API are protected by
Basic Auth; Telegram webhooks remain public at
`https://<settra-host>/api/messaging/webhooks/telegram/<config_id>`.

If the server boots but the app is not running, check cloud-init and Docker from within the VPS:

```bash
cloud-init status --long
tail -n 200 /var/log/cloud-init-output.log
cd /opt/settra
docker compose pull
docker compose up -d
docker compose ps
```

The Hetzner deployment writes generated semantic overlays to a persistent
`semantic_overlays` volume mounted at `/cube/conf/model/overlays`. Cube dev mode
is enabled by default so agent-generated model files hot reload; set
`CUBEJS_DEV_MODE=false` only when model changes are handled as deploy/restart
events.

### Remote MCP Clients

For ChatGPT developer-mode connectors, use the generated MCP URL from
`/opt/settra/credentials.txt`:

```text
https://<settra-host>/mcp/
```

The OAuth login username and password in `credentials.txt` are the same initial
single-admin credentials generated for Basic Auth. ChatGPT discovers OAuth
metadata at `/.well-known/oauth-protected-resource`, registers a client through
`/oauth/register`, sends the user through `/oauth/authorize`, exchanges the code
at `/oauth/token`, then calls `/mcp` with `Authorization: Bearer <token>`.

MCP client support depends on how the server is deployed:

| Client/deployment                           | Supported?     | How to connect                                                                                                          |
| ------------------------------------------- | -------------- | ----------------------------------------------------------------------------------------------------------------------- |
| ChatGPT developer-mode connector on Hetzner | Yes            | Paste the generated `https://<settra-host>/mcp/` URL. ChatGPT uses OAuth discovery and sends bearer tokens after login. |
| Other OAuth-capable MCP clients on Hetzner  | Yes            | Use the same `https://<settra-host>/mcp/` URL and complete OAuth authorization-code + PKCE.                             |
| Static-header MCP clients on Hetzner        | Not by default | Public `/mcp` does not accept Basic Auth headers. Basic Auth protects only the admin UI and API.                        |
| Local/dev MCP clients                       | Yes            | Local Docker keeps OAuth disabled by default, so clients can connect directly to `http://localhost:8000/mcp/`.          |

For local/dev static-header clients, omit the `headers` block unless you add
your own reverse proxy in front of the app. A typical local config looks like:

```json
{
  "mcpServers": {
    "settra": {
      "type": "streamable-http",
      "url": "http://localhost:8000/mcp/"
    }
  }
}
```

To test the OAuth path locally, set:

```text
SETTRA_OAUTH_ENABLED=true
SETTRA_PUBLIC_URL=http://localhost:8000
SETTRA_OAUTH_ADMIN_USER=settra
SETTRA_OAUTH_ADMIN_PASSWORD=settra
```

Important OAuth environment variables:

| Variable                                 | Purpose                                                                                                                 |
| ---------------------------------------- | ----------------------------------------------------------------------------------------------------------------------- |
| `SETTRA_PUBLIC_URL`                      | Canonical public origin used as OAuth issuer and resource audience, for example `https://settra-203-0-113-10.sslip.io`. |
| `SETTRA_OAUTH_ENABLED`                   | Enables OAuth discovery, registration, authorization, token exchange, and `/mcp` bearer-token checks.                   |
| `SETTRA_OAUTH_ADMIN_USER`                | Single-admin username for the built-in authorization page.                                                              |
| `SETTRA_OAUTH_ADMIN_PASSWORD`            | Single-admin password for the built-in authorization page.                                                              |
| `SETTRA_OAUTH_REDIRECT_HOSTS`            | Comma-separated allowlist for OAuth redirect hosts. Defaults to `chatgpt.com`.                                          |
| `SETTRA_OAUTH_SCOPES`                    | Space- or comma-separated scopes advertised and required for `/mcp`. Defaults to `settra:read settra:write`.            |
| `SETTRA_OAUTH_TOKEN_TTL_SECONDS`         | Lifetime for signed MCP access tokens. Defaults to `3600`.                                                              |
| `SETTRA_OAUTH_REFRESH_TOKEN_TTL_SECONDS` | Inactivity lifetime for rotating MCP OAuth refresh tokens. Defaults to `2592000`.                                       |
| `SETTRA_OAUTH_CODE_TTL_SECONDS`          | Lifetime for one-time authorization codes. Defaults to `300`.                                                           |

The built-in OAuth provider is meant to make a self-hosted single-admin Settra
deployment easy to connect from ChatGPT. It issues rotating refresh tokens so
ChatGPT can renew one-hour access tokens without another interactive login;
reusing an invalidated refresh token revokes that token family. For multi-user
production deployments, use a dedicated OAuth/OIDC identity provider and keep
Settra as the resource server that validates issuer, audience, expiry, and
scopes.

## Contributing

Contributions are welcome, especially:

- MCP client compatibility testing
- Cube model validation improvements
- new connectors
- connector Cube models
- cross-app semantic overlays
- deployment guides
- security hardening
- documentation fixes

Please see [`CONTRIBUTING.md`](CONTRIBUTING.md) for details.

## License

Settra is released under the Apache License 2.0. See [`LICENSE`](LICENSE).
