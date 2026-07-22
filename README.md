# Settra

**Ask once. Keep the model.**

Settra gives AI assistants a governed analytics layer over live business apps.
Connect Stripe, HubSpot, Google Sheets, and other tools once, then ask questions
in plain language. When the assistant figures out a useful metric or join, it
saves that model so the next question starts from what you already know.

You get answers from live data—not a one-off export—with semantics you can
reuse, review, and extend over time.

https://github.com/user-attachments/assets/63f8b52a-7618-405d-9601-d24eea2bdbbf

## How it works

1. **Connect your apps** in the admin UI. Settra stores credentials securely and
   exposes each app through Steampipe.
2. **Ask a question** through an MCP client (ChatGPT, Cursor, Claude, etc.).
   The assistant inspects your apps, proposes metrics and relationships, and
   validates them against live data.
3. **Keep the model.** Approved semantics are saved as Cube YAML overlays and
   compiled into a shared semantic layer you can query again and again.

Under the hood: Steampipe adapts each app to SQL, Cube Core owns the semantic
contract, and Settra exposes cubes, measures, and query execution through MCP at
`/mcp`.

## Get started locally

**Requirements:** Docker, Node.js (for the admin UI dev server), Python 3.

```bash
# First-time setup
cd frontend && npm install
cd ../backend && pip install -r requirements.txt
cd ..

# Initialize the database and verify Cube model files
make init

# Full stack (admin UI + Docker services)
make dev
```

Open the admin UI at [http://localhost:5173](http://localhost:5173), add a
connection for a supported connector, then confirm health checks pass.

Docker-only (no frontend hot reload):

```bash
make run          # start stack
make run-build    # rebuild images and start
make down         # stop
```

Useful while developing:

```bash
make build              # rebuild app image
make build-steampipe    # rebuild Steampipe image
docker compose logs -f app
docker compose logs -f cube
docker compose logs -f steampipe
```

## Connect an AI assistant

Settra speaks MCP over streamable HTTP. Point your client at:

```text
http://localhost:8000/mcp/
```

Local Docker keeps OAuth disabled by default, so most clients can connect
directly. A typical Cursor or Claude Desktop config:

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

On a deployed server, use the HTTPS URL from `/opt/settra/credentials.txt`
and complete OAuth when prompted. ChatGPT developer-mode connectors work out
of the box on the included Hetzner deployment.

## Deploy on Hetzner

[![Deploy on Hetzner](https://img.shields.io/badge/Deploy%20on-Hetzner-D50C2D?logo=hetzner&logoColor=white)](https://console.hetzner.cloud/projects)

A CX23 VPS (2 vCPU, 4 GB RAM, ~$5/month) is enough to start. Install the
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

Custom image tags:

```bash
SETTRA_IMAGE=<dockerhub-user>/settra:0.0.1 \
SETTRA_STEAMPIPE_IMAGE=<dockerhub-user>/settra-steampipe:0.0.1 \
./deploy/hetzner/deploy.sh
```

After first boot, read the generated hostname and credentials on the server:

```bash
ssh -i ~/.ssh/settra_hetzner root@<server-ip>
cat /opt/settra/credentials.txt
```

The admin UI and API use Basic Auth. `/mcp` uses OAuth bearer tokens for AI
clients. The deployment gets a temporary `sslip.io` HTTPS hostname—no custom
domain required.

If services fail to start, check cloud-init and Docker on the VPS:

```bash
cloud-init status --long
tail -n 200 /var/log/cloud-init-output.log
cd /opt/settra && docker compose pull && docker compose up -d && docker compose ps
```

## Cross-app semantics

Connector models describe one app each (`connectors/<app>/semantics.yaml`).
Workspace-specific joins and metrics—Stripe revenue by HubSpot lifecycle stage,
sheet-backed targets vs actuals—belong in `semantic_overlays/*.yaml`.

See [`semantic_overlays/README.md`](semantic_overlays/README.md) for the
recommended pattern. Agents and contributors authoring overlay YAML should follow
[`.claude/skills/semantic-file/SKILL.md`](.claude/skills/semantic-file/SKILL.md),
which covers model layout, MCP workflow, provenance fields, and validation.

## For developers

| Doc | Contents |
| --- | --- |
| [`AGENTS.md`](AGENTS.md) | Architecture, MCP tools and resources, HTTP API, environment variables |
| [`CONTRIBUTING.md`](CONTRIBUTING.md) | How to contribute |
| [`SECURITY.md`](SECURITY.md) | Reporting security issues |

Supported connectors today: Stripe, HubSpot, Google Sheets. New connectors need
a `connection.yaml`, bundled `semantics.yaml`, and a Steampipe plugin
declaration—see `AGENTS.md` and existing connectors for the pattern.

## Contributing

Contributions are welcome—connectors, Cube models, cross-app overlays, MCP
compatibility testing, deployment guides, and documentation fixes.

Please see [`CONTRIBUTING.md`](CONTRIBUTING.md) for details.

## License

Settra is released under the Apache License 2.0. See [`LICENSE`](LICENSE).
