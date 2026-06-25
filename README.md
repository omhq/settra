# Settra

**Self-hosted MCP server for business applications.**

Settra connects tools such as Google Sheets, Stripe, and HubSpot through
Steampipe, mounts Cube Core model files for those live app schemas, and exposes
trusted cubes, measures, dimensions, joins, segments, AI context, and query
execution through MCP.

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
        +-- Cube REST API proxy and query execution
        +-- aiosqlite -> /data/app.db
        |   connections
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

Available tools:

| Tool                                | Purpose                                                                     |
| ----------------------------------- | --------------------------------------------------------------------------- |
| `list_cubes`                        | List compiled Cube cubes, views, measures, dimensions, segments, joins, and source labels. |
| `get_cube`                          | Fetch full compiled metadata and source definition for one cube or view.    |
| `query_cube`                        | Execute Cube REST query JSON against the trusted semantic layer.            |
| `get_cube_meta`                     | Fetch the raw Cube `/v1/meta` metadata payload.                             |
| `list_connections`                  | List saved Settra connections without secrets.                              |
| `get_connection_metadata`           | Fetch non-secret live schema metadata for one saved connection.             |
| `sample_connection_table`           | Fetch a small bounded row sample from one saved connection table.           |
| `profile_connection_table`          | Fetch a bounded sample-based profile for one saved connection table.        |
| `save_semantic_overlay`             | Create or update a Cube YAML overlay under `/cube/conf/model/overlays`.     |
| `delete_generated_semantic_overlay` | Delete a generated overlay under `/cube/conf/model/overlays/generated`.     |

Available resources:

| Resource                          | Purpose                                 |
| --------------------------------- | --------------------------------------- |
| `settra://semantics/meta`         | Raw compiled Cube metadata.             |
| `settra://semantics/cubes`        | Summarized cube catalog.                |
| `settra://semantics/cubes/{name}` | Compiled metadata for one cube or view. |
| `settra://semantics/model/{path}` | Mounted Cube YAML model file content.   |

## Connectors

Connector definitions live in:

```text
connectors/<connector-key>/connection.yaml
```

Connector Cube models live next to them:

```text
connectors/<connector-key>/semantics.yaml
```

Those `semantics.yaml` files use Cube YAML directly. Docker Compose mounts each
one into `/cube/conf/model/<connector-key>.yaml`. Use the Semantics page or
the model-file API to edit the mounted Cube YAML.

The bundled files assume Steampipe schema names match connector keys. If a
connection uses a different slug, update the relevant Cube `sql_table` values.

Workspace-specific cross-app models can live in `semantic_overlays/`, which is
mounted into Cube at `/cube/conf/model/overlays`.

Settra reports model file source types so clients can distinguish where semantic
definitions came from:

| Source type | Meaning |
| --- | --- |
| `bundled_connector` | Static connector semantics packaged from `connectors/<key>/semantics.yaml`. |
| `overlay` | Hand-authored workspace overlay under `/cube/conf/model/overlays`. |
| `generated_overlay` | Agent-generated, user-specific overlay under `/cube/conf/model/overlays/generated`. |

Recommended MCP workflow for generated overlays:

1. Call `list_connections`.
2. Call `get_connection_metadata` for relevant connections.
3. Call `sample_connection_table` and `profile_connection_table` for
   user-specific or unfamiliar tables.
4. Inspect existing semantics with `list_cubes` and `get_cube`.
5. Write Cube YAML with `save_semantic_overlay` under `generated/*.yaml`.
6. Validate with `list_cubes` and `query_cube`.
7. Clean up failed experiments with `delete_generated_semantic_overlay`.

The sample/profile tools are structured introspection tools, not raw SQL
execution. They are bounded, redact obvious secret-like columns, and reconstruct
Google Sheets virtual worksheet tables from `googlesheets_cell` so agents can
infer columns such as dates, owners, notes, and revenue targets before writing
Cube YAML.

## HTTP API

The HTTP API supports administration, diagnostics, Cube model editing, and
Cube-backed query execution:

| Method                | Path                                | Description                                       |
| --------------------- | ----------------------------------- | ------------------------------------------------- |
| `GET`                 | `/api/health`                       | Steampipe connectivity check.                     |
| `GET`                 | `/api/health/fdw`                   | Per-connection FDW diagnostics.                   |
| `POST`                | `/api/health/fdw/{id}/refresh`      | Refresh Steampipe metadata cache.                 |
| `POST`                | `/api/health/steampipe/restart`     | Restart Steampipe when configured.                |
| `GET`                 | `/api/connectors`                   | List connector definitions.                       |
| `GET/POST/PUT/DELETE` | `/api/connections...`               | Manage saved app connections.                     |
| `POST`                | `/api/connections/{id}/retry`       | Re-validate connection credentials and FDW state. |
| `POST`                | `/api/connections/{id}/metadata`    | Fetch live Steampipe metadata.                    |
| `POST`                | `/api/query/`                       | Execute Cube REST query JSON.                     |
| `GET`                 | `/api/semantics/model`              | List Cube model files and Cube metadata status.   |
| `POST`                | `/api/semantics/model/sync`         | Refresh the mounted Cube model file view.         |
| `GET/PUT`             | `/api/semantics/model/files/{path}` | Read or update Cube YAML model files.             |
| `GET`                 | `/api/semantics/meta`               | Proxy Cube `/v1/meta` metadata.                   |
| `GET`                 | `/.well-known/oauth-protected-resource` | OAuth protected-resource metadata for MCP.     |
| `GET`                 | `/.well-known/oauth-authorization-server` | OAuth authorization-server metadata.         |
| `POST`                | `/oauth/register`                   | Dynamic client registration for MCP OAuth.        |
| `GET/POST`            | `/oauth/authorize`                  | Single-admin authorization-code + PKCE flow.      |
| `POST`                | `/oauth/token`                      | Authorization-code token exchange.                |

## Configuration

Common environment variables:

| Variable                            | Default                                | Purpose                                                     |
| ----------------------------------- | -------------------------------------- | ----------------------------------------------------------- |
| `STEAMPIPE_HOST`                    | `steampipe`                            | Steampipe service hostname.                                 |
| `STEAMPIPE_PORT`                    | `9193`                                 | Steampipe PostgreSQL port.                                  |
| `STEAMPIPE_CONFIG_DIR`              | `/steampipe/config` in compose         | Where connector `.spc` files are written.                   |
| `STEAMPIPE_DB_PASSWORD`             | `steampipe_pass` in compose            | Password for the Steampipe PostgreSQL user.                 |
| `STEAMPIPE_RESTART_COMMAND`         | unset                                  | Optional restart command for non-Docker deployments.        |
| `STEAMPIPE_RESTART_TIMEOUT_SECONDS` | `120`                                  | Restart command timeout.                                    |
| `CUBE_API_URL`                      | `http://cube:4000/cubejs-api`          | Backend-to-Cube REST API base URL.                          |
| `CUBE_API_SECRET`                   | `cube-dev-secret-change-me` in compose | Secret used to sign Cube REST API tokens.                   |
| `CUBE_MODEL_DIR`                    | `/cube/conf/model`                     | Directory where Cube model files live.                      |
| `DATA_DIR`                          | `/data`                                | SQLite data directory.                                      |
| `DB_PATH`                           | `/data/app.db`                         | SQLite database path.                                       |
| `CONNECTORS_DIR`                    | `/config/connectors`                   | Connector definitions and bundled Cube YAML files.          |
| `SECRET_KEY`                        | `dev-secret-change-me`                 | General secret key material.                                |
| `SETTRA_PUBLIC_URL`                 | derived from request if unset          | Public origin used as OAuth issuer and resource audience.   |
| `SETTRA_OAUTH_ENABLED`              | `false` locally; `true` on Hetzner     | Enables OAuth for ChatGPT-compatible MCP access.            |
| `SETTRA_OAUTH_ADMIN_USER`           | `settra`                               | Single-admin username for the built-in OAuth login page.    |
| `SETTRA_OAUTH_ADMIN_PASSWORD`       | unset                                  | Single-admin password for the built-in OAuth login page.    |
| `SETTRA_OAUTH_REDIRECT_HOSTS`       | `chatgpt.com`                          | Comma-separated allowlist for OAuth redirect hosts.         |
| `SETTRA_OAUTH_SCOPES`               | `settra:read settra:write`             | Space- or comma-separated scopes advertised for `/mcp`.     |
| `SETTRA_OAUTH_TOKEN_TTL_SECONDS`    | `3600`                                 | Lifetime for signed MCP access tokens.                      |
| `SETTRA_OAUTH_CODE_TTL_SECONDS`     | `300`                                  | Lifetime for one-time authorization codes.                  |
| `LOG_LEVEL`                         | `INFO`                                 | Backend log level.                                          |
| `MCP_ALLOWED_HOSTS`                 | localhost defaults                     | Comma-separated allowed hosts for MCP transport security.   |
| `MCP_ALLOWED_ORIGINS`               | localhost defaults                     | Comma-separated allowed origins for MCP transport security. |

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

| Client/deployment | Supported? | How to connect |
| --- | --- | --- |
| ChatGPT developer-mode connector on Hetzner | Yes | Paste the generated `https://<settra-host>/mcp/` URL. ChatGPT uses OAuth discovery and sends bearer tokens after login. |
| Other OAuth-capable MCP clients on Hetzner | Yes | Use the same `https://<settra-host>/mcp/` URL and complete OAuth authorization-code + PKCE. |
| Static-header MCP clients on Hetzner | Not by default | Public `/mcp` does not accept Basic Auth headers. Basic Auth protects only the admin UI and API. |
| Local/dev MCP clients | Yes | Local Docker keeps OAuth disabled by default, so clients can connect directly to `http://localhost:8000/mcp/`. |

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

| Variable | Purpose |
| --- | --- |
| `SETTRA_PUBLIC_URL` | Canonical public origin used as OAuth issuer and resource audience, for example `https://settra-203-0-113-10.sslip.io`. |
| `SETTRA_OAUTH_ENABLED` | Enables OAuth discovery, registration, authorization, token exchange, and `/mcp` bearer-token checks. |
| `SETTRA_OAUTH_ADMIN_USER` | Single-admin username for the built-in authorization page. |
| `SETTRA_OAUTH_ADMIN_PASSWORD` | Single-admin password for the built-in authorization page. |
| `SETTRA_OAUTH_REDIRECT_HOSTS` | Comma-separated allowlist for OAuth redirect hosts. Defaults to `chatgpt.com`. |
| `SETTRA_OAUTH_SCOPES` | Space- or comma-separated scopes advertised and required for `/mcp`. Defaults to `settra:read settra:write`. |
| `SETTRA_OAUTH_TOKEN_TTL_SECONDS` | Lifetime for signed MCP access tokens. Defaults to `3600`. |
| `SETTRA_OAUTH_CODE_TTL_SECONDS` | Lifetime for one-time authorization codes. Defaults to `300`. |

The built-in OAuth provider is meant to make a self-hosted single-admin Settra
deployment easy to connect from ChatGPT. For multi-user production deployments,
use a dedicated OAuth/OIDC identity provider and keep Settra as the resource
server that validates issuer, audience, expiry, and scopes.

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
