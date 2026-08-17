# Self-hosting

This guide is for people deploying, operating, or developing Settra. For the
product overview, start with the [main README](README.md).

Settra is a self-hosted MCP server for sheet data. The current Google Sheets
adapter uses Steampipe for read-only access, Cube Core defines the trusted
semantic contract, and a FastAPI backend makes worksheet metadata and current
values available to automated agents.

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

Initialize the database, verify the Google Sheets Cube template, and start the
full stack:

```bash
make init
make dev
```

Open [http://localhost:5173](http://localhost:5173), connect a Google Sheet, and
confirm the health checks pass. The in-app setup guide explains how to create a
service account and share the spreadsheet with Viewer access.

To run the Docker stack without frontend hot reload:

```bash
make run
make run-build
make down
```

Useful diagnostics:

```bash
make build
make build-steampipe
docker compose logs -f app
docker compose logs -f cube
docker compose logs -f steampipe
```

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
SETTRA_STEAMPIPE_IMAGE=<dockerhub-user>/settra-steampipe:0.0.1 \
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

## Sheet-specific semantic models

The packaged template in `connectors/googlesheets/semantics.yaml` describes the
Google Sheets metadata, sheet, and cell tables. Each connected spreadsheet gets
an active generated model under:

```text
/cube/conf/model/generated/connections/<sheet-slug>.yaml
```

Worksheet-specific models belong in `semantic_overlays/*.yaml`. Use them to map
real header names, document row grain, define measures, normalize dates, or
preserve approved business rules. See
[semantic_overlays/README.md](semantic_overlays/README.md).

## Contributing

Contributions are welcome when they improve the sheet data workflow for agents,
semantic quality, MCP compatibility, privacy, deployment, or documentation. See
[CONTRIBUTING.md](CONTRIBUTING.md).
