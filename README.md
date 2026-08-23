# Settra

**Make sheet data durable and easy for automated agents to use.**

Settra synchronizes Google Sheets into PostgreSQL and makes the durable snapshots
available to AI assistants and automated agents through MCP. Agents can discover
worksheet schemas, inspect bounded samples, and query synchronized values
through a governed semantic layer.

It is built for teams that use spreadsheets as operational data stores and want
agents to work with that data safely and repeatably.

> [!IMPORTANT]
> You can run Settra on a server you control or ask us to host it for you. For
> managed hosting, email
> [support@outermeasure.com](mailto:support@outermeasure.com).

## What can agents do?

- Find overdue items in an operations tracker.
- Summarize this month's pipeline from a sales worksheet.
- Compare actual values with targets stored in another tab.
- Identify rows that changed or need follow-up.
- Reuse an approved definition such as “active customer” or “recognized
  revenue” in later queries.

## How it works

```mermaid
flowchart LR
    sheet["Google Sheets<br/>Operational rows and values"]
    sync["dlt full sync<br/>OAuth + loading rules"]
    postgres["PostgreSQL<br/>Durable snapshots"]
    settra["Cube + Settra<br/>Approved semantics"]
    agent["Automated agent<br/>MCP client"]
    task["Question or workflow"]

    task --> agent
    agent -->|"structured metadata and queries"| settra
    sheet --> sync
    sync --> postgres
    postgres --> settra
    settra -->|"bounded results"| agent
```

Settra uses the first row of each selected tab as column headers and performs a
complete replacement load with dlt. PostgreSQL keeps the last successful
snapshot available while a new one is staged. Per-source YAML controls schedules,
type overrides, names, schema contracts, and descriptions.

Cube Core is the canonical semantic layer. It gives agents stable names,
measures, dimensions, business definitions, and validation rules instead of
unrestricted SQL access.

Collections group related pipes into focused agent workspaces. An agent using
the global MCP URL asks which collection to use, loads its context once, and
queries only its derived destination tables and cubes. A collection-specific
MCP URL can optionally pin that selection.

## How data is handled

When self-hosted, Settra runs inside infrastructure you control. The Google OAuth
refresh token is encrypted with `SECRET_KEY` on the data volume and is not stored
in the product database or source YAML. MCP request/response contents are also
not stored; PostgreSQL request history contains privacy-safe usage metrics only.

Query results are sent to the AI assistant or agent you connect, so that
provider's privacy and retention policies still apply.

## What you need

- A Google Sheet with a header row and tabular data.
- A Google Cloud Web OAuth client plus a browser-restricted Google Picker API
  key. Settra requests file-specific access only to spreadsheets users select.
- A Settra deployment.
- An MCP-compatible AI assistant or automated agent.

## For developers

- [Self-hosting and technical setup](SELF-HOSTING.md)
- [Product database and migrations](DATABASE.md)
- [Google Cloud OAuth and Picker setup](GCP-SETUP.md)
- [Architecture and API reference](AGENTS.md)
- [Google Sheets setup guide](connectors/googlesheets/README.md)
- [Contributing](CONTRIBUTING.md)

Settra is open source under the [Apache License 2.0](LICENSE).
