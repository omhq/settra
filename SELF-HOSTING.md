# Self-hosting

This guide is for the person deploying, operating, or developing Settra. For a
non-technical product overview, start with the [main README](README.md).

Settra is a self-hosted MCP server. It uses Steampipe to connect to business
apps, Cube Core to define trusted business metrics and relationships, and a
FastAPI backend to make those definitions and live queries available to AI
clients.

For the complete architecture, MCP tool catalog, HTTP API, and environment
variables, see [AGENTS.md](AGENTS.md).

## Get started locally

### Requirements

- Docker
- Node.js for the admin UI development server
- Python 3

Install the development dependencies:

```bash
cd frontend && npm install
cd ../backend && pip install -r requirements.txt
cd ..
```

Initialize the database, verify the Cube model files, and start the full stack:

```bash
make init
make dev
```

Open the admin UI at [http://localhost:5173](http://localhost:5173), add a
connection for a supported connector, and confirm the health checks pass.

To run the Docker stack without frontend hot reload:

```bash
make run          # start the stack
make run-build    # rebuild images and start
make down         # stop the stack
```

Useful development and diagnostic commands:

```bash
make build
make build-steampipe
docker compose logs -f app
docker compose logs -f cube
docker compose logs -f steampipe
```

## Connect an AI client

Settra speaks MCP over streamable HTTP. A local deployment exposes:

```text
http://localhost:8000/mcp/
```

Local Docker keeps OAuth disabled by default, so local clients can connect
directly. A typical streamable HTTP MCP configuration is:

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

The exact configuration screen and format depend on the AI client. For a
deployed server, use its HTTPS `/mcp` URL and complete OAuth when the client
prompts you.

## Deploy on Hetzner

[![Deploy on Hetzner](https://img.shields.io/badge/Deploy%20on-Hetzner-D50C2D?logo=hetzner&logoColor=white)](https://console.hetzner.cloud/projects)

A CX23 VPS with 2 vCPUs and 4 GB RAM is enough to start. Install the
[`hcloud`](https://github.com/hetznercloud/cli) CLI, create an API token context,
then upload an SSH key:

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

After the first boot, read the generated hostname and credentials on the server:

```bash
ssh -i ~/.ssh/settra_hetzner root@<server-ip>
cat /opt/settra/credentials.txt
```

The admin UI and API use Basic Auth. `/mcp` uses OAuth bearer tokens for AI
clients. The deployment gets a temporary `sslip.io` HTTPS hostname, so a custom
domain is not required.

Use the HTTPS MCP URL from `/opt/settra/credentials.txt` and complete OAuth when
prompted. ChatGPT developer-mode connectors work with the included Hetzner
deployment.

If services fail to start, check cloud-init and Docker on the VPS:

```bash
cloud-init status --long
tail -n 200 /var/log/cloud-init-output.log
cd /opt/settra && docker compose pull && docker compose up -d && docker compose ps
```

## Cross-app semantic models

Connector models describe one app each:

```text
connectors/<app>/semantics.yaml
```

Workspace-specific joins and metrics—such as Stripe revenue by HubSpot lifecycle
stage or sheet-backed targets versus actuals—belong in:

```text
semantic_overlays/*.yaml
```

See [semantic_overlays/README.md](semantic_overlays/README.md) for the recommended
pattern. Agents and contributors authoring overlay YAML should follow
[`.claude/skills/semantic-file/SKILL.md`](.claude/skills/semantic-file/SKILL.md),
which covers model layout, the MCP workflow, provenance fields, and validation.

Supported connectors currently include Stripe, HubSpot, and Google Sheets. To
add a connector, provide its `connection.yaml`, bundled `semantics.yaml`, and
Steampipe plugin declaration. See [AGENTS.md](AGENTS.md) and the existing
connectors for the full pattern.

## Contributing

Contributions are welcome, including connectors, Cube models, cross-app
overlays, MCP compatibility testing, deployment guides, and documentation
fixes. See [CONTRIBUTING.md](CONTRIBUTING.md) for details.
