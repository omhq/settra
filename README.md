# Settra

**Self-hosted analytics agent over your connected app data.**

Settra is a self-hosted analytics agent for teams that want useful answers from their
operational tools without first building a data warehouse, ETL pipeline, or dashboard
stack.

Connect apps like Google Sheets, Stripe, and HubSpot, bring your own model keys, and
talk to your data from the browser, Telegram, or WhatsApp. Settra queries source systems
through a pluggable Zero-ETL layer and gives the agent a semantic layer it can actually
read: tables, columns, relationships, reusable metrics, contracts, and business context.

The bundled engine today is Steampipe. Settra treats the query engine as an adapter
boundary, so other SQL-capable engines can be added over time.

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

You can override the defaults with environment variables.
For example, to deploy a production-named server in
Falkenstein with a larger instance type:

```bash
HCLOUD_SERVER_NAME=settra-prod \
HCLOUD_SERVER_TYPE=cx32 \
HCLOUD_SERVER_IMAGE=ubuntu-26.04 \
HCLOUD_SERVER_LOCATION=fsn1 \
HCLOUD_SSH_KEY=settra \
HCLOUD_FIREWALL_NAME=settra-prod \
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

## Configuration

Settra uses environment variables for service configuration, model providers, connector directories,
logging, and worker behavior.

Common variables include:

| Variable                  | Purpose                                                      |
| ------------------------- | ------------------------------------------------------------ |
| `STEAMPIPE_HOST`          | Steampipe service hostname                                   |
| `STEAMPIPE_PORT`          | Steampipe PostgreSQL port                                    |
| `STEAMPIPE_CONFIG_DIR`    | Where connector config files are written                     |
| `DATA_DIR`                | SQLite data directory                                        |
| `DB_PATH`                 | SQLite database path                                         |
| `CONNECTORS_DIR`          | Connector definitions and semantic metadata                  |
| `CHANNELS_DIR`            | Messaging channel definitions                                |
| `MODEL_PROVIDERS_YAML`    | Model provider definitions                                   |
| `SECRET_KEY`              | Encryption key material for stored model and channel secrets |
| `PUBLIC_API_URL`          | Public API origin for webhook setup                          |
| `CHAT_WORKER`             | Enable or disable the chat worker                            |
| `MESSAGING_WORKER`        | Enable or disable messaging workers                          |
| `CHAT_MAX_RESULT_ROWS`    | Max rows returned to chat context                            |
| `CHAT_MAX_QUERY_ATTEMPTS` | Max SQL repair attempts per run                              |

Use a strong `SECRET_KEY` before putting Settra in front of real data. Changing it later can make
existing encrypted secrets unreadable.

## Current connectors

The current distribution includes connector definitions for:

- Google Sheets
- Stripe
- HubSpot

Connector definitions live in:

```text
connectors/<connector-key>/connection.yaml
```

Semantic metadata for each connector lives next to it:

```text
connectors/<connector-key>/semantics.yaml
```

You can add new connectors by creating a connector definition and, optionally, a semantic
metadata file.

## The semantic layer

Semantics teach the agent how to reason about the data, what each table represents, how rows
should be counted, which columns are keys or measures, how to join tables, relationships, and
which metric expressions are safe to reuse. Settra can generate initial semantics from connected
data. You can then improve them with AI assistance or edit them by hand. Better semantic context
means better analytical queries, fewer hallucinated joins, and answers that match how your business
actually thinks about its data.

The semantic layer helps the agent understand:

- What each table represents.
- Which columns are identifiers, timestamps, dimensions, and measures.
- How rows should be counted.
- Which joins are meaningful.
- Which metrics are safe to reuse.
- Which assumptions or query patterns should be avoided.

## Privacy and control

Settra is designed for teams that are uncomfortable sending all app data into a third-party analytics
SaaS. You self-host, BYOK, no data replication, editable semantics.

## Using Settra with messaging apps

Settra can connect messaging channels so users can talk to their agent without opening the browser.

Current channel support includes:

- Telegram
- WhatsApp

## Roadmap

Near-term areas that would make Settra more useful:

- Exportable reports.
- Basic charts for answers that need visual context.
- Scheduling.

## Local development

```bash
# First-time setup
cd frontend && npm install
cd ../backend && pip install -r requirements.txt
cd ..

# Initialize SQLite tables and load agent prompts + connector semantics
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

## Need help setting it up?

If you like the idea but do not want to wire everything together yourself, paid setup help is available.

Typical setup work can include:

- Deploying Settra on your infrastructure.
- Connecting your apps.
- Configuring model providers.
- Creating and reviewing semantic metadata.
- Setting up Telegram or WhatsApp access.
- Adding custom connectors.
- Training your team on safe usage.

Contact us here https://www.outermeasure.com/contact if you need help adapting Settra to your business workflow.

## Contributing

Contributions are welcome, especially:

- new connectors,
- semantic metadata improvements,
- deployment guides,
- security hardening,
- documentation fixes,
- real-world examples.

Please see [`CONTRIBUTING.md`](CONTRIBUTING.md) for details.

## License

Settra is released under the Apache License 2.0. See [`LICENSE`](LICENSE).
