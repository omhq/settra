# Settra

**Settra is being refocused into a self-hosted MCP server for business apps,
powered by Cube Core semantics.**

Settra connects tools such as Google Sheets, Stripe, and HubSpot through
Steampipe, mounts Cube Core model files for those live app schemas, and will
expose trusted cubes, measures, dimensions, joins, and metadata through the MCP
surface.

The product direction is MCP-only. Browser chat, Telegram, WhatsApp, model
provider management, and other messaging-channel surfaces have been removed.
The remaining React app is an admin console for connections, Cube model editing,
and service health.

## Architecture

```text
Future MCP client / admin browser
        |
        v
FastAPI backend (:8000)
        |
        +-- SQLite: connections
        +-- connector definitions: connectors/*/connection.yaml
        +-- connector Cube models: connectors/*/semantics.yaml
        +-- Cube model files: cube/model/**/*.yml
        +-- Cube REST metadata proxy: cube:4000/cubejs-api/v1/meta
        +-- Steampipe PostgreSQL service for live app schemas

Cube Core (:4000)
        |
        +-- reads /cube/conf/model
        +-- connects to Steampipe as a Postgres source

Steampipe (:9193)
        |
        +-- reads rendered .spc credential files
        +-- exposes each saved connection as a PostgreSQL schema
```

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
one into `/cube/conf/model/<connector-key>.yaml`, so Cube compiles them without
a Settra translation step. Use the Semantics page to edit the mounted Cube YAML.
The bundled files assume Steampipe schema names match connector keys such as
`googlesheets`, `hubspot`, and `stripe`; if a connection uses a different slug,
update the relevant Cube `sql_table` values.

## Configuration

Common environment variables:

| Variable | Purpose |
| --- | --- |
| `STEAMPIPE_HOST` | Steampipe service hostname |
| `STEAMPIPE_PORT` | Steampipe PostgreSQL port |
| `STEAMPIPE_CONFIG_DIR` | Where connector `.spc` files are written |
| `STEAMPIPE_DB_PASSWORD` | Password for the Steampipe PostgreSQL user |
| `CUBE_API_URL` | Backend-to-Cube REST API base URL |
| `CUBE_API_SECRET` | Secret used to sign Cube REST API tokens |
| `CUBE_MODEL_DIR` | Directory where Cube model files live |
| `DATA_DIR` | SQLite data directory |
| `DB_PATH` | SQLite database path |
| `CONNECTORS_DIR` | Connector definitions and bundled Cube YAML files |
| `SECRET_KEY` | General secret key material |
| `LOG_LEVEL` | Backend log level |

Use strong `SECRET_KEY` and `CUBE_API_SECRET` values before putting Settra in
front of real data.

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

# Watch logs
docker compose logs -f app
docker compose logs -f cube
docker compose logs -f steampipe
```

## Semantic Layer

Cube Core is the canonical semantic layer. Settra no longer maintains its own
`semantic_*` SQLite tables or semantic editing service.

Current flow:

1. A saved Settra connection creates a Steampipe schema.
2. Cube reads the connector’s mounted `semantics.yaml` as Cube YAML.
3. Cube compiles the model and exposes metadata through `/cubejs-api/v1/meta`.
4. The Settra Semantics page edits those Cube YAML files and displays the
   Cube-compiled metadata.

## Deployment

Settra can run anywhere containers can run. The included Hetzner helper deploys
the app, Cube Core, Steampipe, and Caddy with Basic Auth in front of the admin
UI and API.

```bash
./deploy/hetzner/deploy.sh
```

When deploying images from your own DockerHub namespace:

```bash
SETTRA_IMAGE=<dockerhub-user>/settra:0.0.1 \
SETTRA_STEAMPIPE_IMAGE=<dockerhub-user>/settra-steampipe:0.0.1 \
./deploy/hetzner/deploy.sh
```

## Contributing

Contributions are welcome, especially:

- MCP server implementation work
- Cube model validation improvements
- new connectors
- connector Cube models
- deployment guides
- security hardening
- documentation fixes

Please see [`CONTRIBUTING.md`](CONTRIBUTING.md) for details.

## License

Settra is released under the Apache License 2.0. See [`LICENSE`](LICENSE).
