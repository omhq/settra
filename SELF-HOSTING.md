# Self-hosting

This guide is for people deploying, operating, or developing Settra. For the
product overview, start with the [main README](README.md).

Settra is a self-hosted MCP server for sheet data. dlt performs complete Google
Sheets loads into dedicated PostgreSQL schemas, Cube Core defines the trusted
semantic contract, and FastAPI makes synchronized worksheet metadata and values
available to automated agents.

For the complete architecture, MCP tool catalog, HTTP API, and environment
variables, see [AGENTS.md](AGENTS.md).

## Get started locally

### Requirements

- Docker
- Node.js for the admin UI development server
- Python 3

Install development dependencies:

```bash
cd frontend && npm install
cd ../backend && pip install -r requirements.txt
cd ..
```

Before connecting Google, create a Web application OAuth client and a
browser-restricted API key in Google Cloud. Enable the Drive, Sheets, and Google
Picker APIs, then add this local redirect URI:

```text
http://localhost:8000/api/google-oauth/callback
```

Use the [complete Google Cloud setup guide](GCP-SETUP.md) for direct Console
links, consent-screen settings, OAuth scopes, API-key restrictions, production
URLs, and troubleshooting.

Copy `.env.example` to `.env`, set `GOOGLE_OAUTH_CLIENT_ID`,
`GOOGLE_OAUTH_CLIENT_SECRET`, `GOOGLE_PICKER_API_KEY`,
`GOOGLE_PICKER_APP_ID` (the numeric project number), and strong deployment
secrets. Then start the full development stack:

```bash
make dev
```

`make dev` starts PostgreSQL, FastAPI, Cube, and the frontend development
server. FastAPI startup applies the Alembic migrations and synchronizes the Cube
model automatically. The `make init` target uses `--no-deps` and is only useful
when PostgreSQL is already running.

Open [http://localhost:5173](http://localhost:5173), connect Google under
**Data → Connections**, then add a spreadsheet under **Data → Pipes**. The first
full synchronization runs immediately.

To run the Docker stack without frontend hot reload:

```bash
make run
make run-build
make down
```

Useful diagnostics:

```bash
make build
docker compose logs -f app
docker compose logs -f cube
docker compose logs -f postgres
```

Settra automatically applies its Alembic migrations at backend startup. Use
`make migrate` to apply them explicitly, and see [DATABASE.md](DATABASE.md) for
the product-schema layout and migration workflow.

## Connect an agent

Settra speaks MCP over streamable HTTP. A local deployment exposes:

```text
http://localhost:8000/mcp/
```

Local Docker disables OAuth by default. A typical MCP configuration is:

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

For a public deployment, use its HTTPS `/mcp` URL and complete OAuth when the
client prompts you.

## Deploy on Hetzner

[![Deploy on Hetzner](https://img.shields.io/badge/Deploy%20on-Hetzner-D50C2D?logo=hetzner&logoColor=white)](https://console.hetzner.cloud/projects)

A CX23 VPS with 2 vCPUs and 4 GB RAM is enough to start. Install the
[`hcloud`](https://github.com/hetznercloud/cli) CLI, create an API token context,
and upload an SSH key:

```bash
mkdir -p ~/.ssh && chmod 700 ~/.ssh
ssh-keygen -t ed25519 -C "settra-hetzner" -f ~/.ssh/settra_hetzner
hcloud ssh-key create --name settra --public-key-from-file ~/.ssh/settra_hetzner.pub
```

Deploy:

```bash
./deploy/hetzner/deploy.sh
```

To use custom image tags:

```bash
SETTRA_IMAGE=<dockerhub-user>/settra:0.0.1 \
POSTGRES_IMAGE=postgres:17-alpine \
./deploy/hetzner/deploy.sh
```

After first boot, read the generated hostname and credentials:

```bash
ssh -i ~/.ssh/settra_hetzner root@<server-ip>
cat /opt/settra/credentials.txt
```

The admin UI and API use Basic Auth. `/mcp` uses OAuth bearer tokens for agents.
The deployment receives a temporary `sslip.io` HTTPS hostname, so a custom
domain is optional.

If services fail to start:

```bash
cloud-init status --long
tail -n 200 /var/log/cloud-init-output.log
cd /opt/settra && docker compose pull && docker compose up -d && docker compose ps
```

## Per-source semantic models

After every successful load, Settra introspects the PostgreSQL snapshot and
generates an active Cube model under:

```text
/cube/conf/model/generated/connections/<sheet-slug>.yaml
```

The source YAML in `/data/connections/<sheet-slug>.yaml` controls tab selection,
the cron schedule, type overrides, physical names, schema contracts, and table
or column descriptions. Settra ships no default semantic model or overlay.
User-specific overlays created through the semantic API or MCP tools live only
under `/cube/conf/model/overlays`, in the shared Cube runtime volume.

## Contributing

Contributions are welcome when they improve the sheet data workflow for agents,
semantic quality, MCP compatibility, privacy, deployment, or documentation. See
[CONTRIBUTING.md](CONTRIBUTING.md).
