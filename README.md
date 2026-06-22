# Settra

**Self-hosted MCP server for business app analytics.**

Settra is an MCP server that sits on top of business apps. It connects to systems 
such as Google Sheets, Stripe, and HubSpot without copying their data into a warehouse, 
builds a governed semantic layer, and exposes that business context to MCP clients.

The product direction is MCP-only. Browser chat, Telegram, WhatsApp, and other
messaging-channel surfaces have been removed. The remaining React app is an
admin console for configuring connections, model providers, semantic metadata,
and service health while the MCP server surface is built out.

## Current Shape

```text
MCP client / admin browser
        |
        v
FastAPI backend
        |
        +-- SQLite metadata: connections, models, semantics, AI introspection runs
        +-- connector definitions: connectors/*/connection.yaml
        +-- semantic metadata: connectors/*/semantics.yaml
        +-- Steampipe PostgreSQL service for live app schemas and queries
```

## Current Connectors

The current distribution includes connector definitions for:

- Google Sheets
- Stripe
- HubSpot

Connector definitions live in:

```text
connectors/<connector-key>/connection.yaml
```

Semantic metadata lives next to each connector:

```text
connectors/<connector-key>/semantics.yaml
```

## Semantic Layer

Settra’s semantic layer describes what connected tables mean: identifiers,
timestamps, measures, dimensions, relationships, reusable metrics, and rules for
safe interpretation. The current repo stores this metadata in SQLite and YAML;
the new direction is to power that layer with Cube Core.

## Configuration

Common environment variables:

| Variable | Purpose |
| --- | --- |
| `STEAMPIPE_HOST` | Steampipe service hostname |
| `STEAMPIPE_PORT` | Steampipe PostgreSQL port |
| `STEAMPIPE_CONFIG_DIR` | Where connector config files are written |
| `STEAMPIPE_RESTART_COMMAND` | Optional command used by the Status page restart action |
| `STEAMPIPE_RESTART_TIMEOUT_SECONDS` | Timeout for the optional restart command |
| `DATA_DIR` | SQLite data directory |
| `DB_PATH` | SQLite database path |
| `CONNECTORS_DIR` | Connector definitions and semantic metadata |
| `MODEL_PROVIDERS_YAML` | Model provider definitions |
| `SECRET_KEY` | Encryption key material for stored model secrets |
| `LOG_LEVEL` | Backend log level |
| `AGENT_DEBUG` | Verbose semantic-assistance logging |
| `AGENT_LOG_PROMPTS` | Log rendered semantic-assistance prompts |
| `LITELLM_DEBUG` | LiteLLM debug logging |
| `LLM_REQUEST_TIMEOUT_SECONDS` | Model request timeout |
| `LLM_VISIBLE_RETRIES` | Visible model-provider retry count |
| `LLM_RETRY_BASE_DELAY_SECONDS` | Base delay for model-provider retries |

Use a strong `SECRET_KEY` before putting Settra in front of real data. Changing
it later can make existing encrypted secrets unreadable.

## Local Development

```bash
# First-time setup
cd frontend && npm install
cd ../backend && pip install -r requirements.txt
cd ..

# Initialize SQLite tables and load connector semantics
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
docker compose logs -f steampipe
```

## Deployment

Settra can run anywhere containers can run. The included Hetzner helper deploys
the app, Steampipe, and Caddy with Basic Auth in front of the admin UI and API.

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
- Cube Core semantic-layer integration
- new connectors
- semantic metadata improvements
- deployment guides
- security hardening
- documentation fixes

Please see [`CONTRIBUTING.md`](CONTRIBUTING.md) for details.

## License

Settra is released under the Apache License 2.0. See [`LICENSE`](LICENSE).
