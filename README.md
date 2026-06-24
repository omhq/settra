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
the app, Cube Core, Steampipe, and Caddy with Basic Auth in front of the MCP
server, admin UI, and API.

```bash
./deploy/hetzner/deploy.sh
```

When deploying images from your own DockerHub namespace:

```bash
SETTRA_IMAGE=<dockerhub-user>/settra:0.0.1 \
SETTRA_STEAMPIPE_IMAGE=<dockerhub-user>/settra-steampipe:0.0.1 \
./deploy/hetzner/deploy.sh
```

The Hetzner deployment writes generated semantic overlays to a persistent
`semantic_overlays` volume mounted at `/cube/conf/model/overlays`. Cube dev mode
is enabled by default so agent-generated model files hot reload; set
`CUBEJS_DEV_MODE=false` only when model changes are handled as deploy/restart
events.

### Remote MCP Clients

Point streamable HTTP MCP clients at:

```text
https://<settra-host>/mcp/
```

The Hetzner helper places Caddy Basic Auth in front of the app. For MCP clients
that support custom headers, send:

```text
Authorization: Basic <base64(username:password)>
```

Example client shape:

```json
{
  "mcpServers": {
    "settra": {
      "type": "streamable-http",
      "url": "https://settra-203-0-113-10.sslip.io/mcp/",
      "headers": {
        "Authorization": "Basic c2V0dHJhOnBhc3N3b3Jk"
      }
    }
  }
}
```

Treat Basic Auth as the simple single-user deployment mode. For broader or
multi-user exposure, put Settra behind an OAuth 2.1/OIDC gateway and issue
audience-bound tokens for the MCP server instead of sharing a static credential.

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
