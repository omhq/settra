# Settra

**Ask questions across your CRM, billing, and sheets. Get instant answers from live data without a warehouse setup.**

Settra connects your business apps, like Stripe, HubSpot, and Google Sheets, into a
single source for reporting and analysis. Connect each source once, then generate
reports or answer questions using live data pulled directly from the original systems.

> [!IMPORTANT]
> You can run it on a server you control or ask us to host it for you. You
> do not need to be a developer to use it after setup. For managed hosting,
> email [support@outermeasure.com](mailto:support@outermeasure.com).

https://github.com/user-attachments/assets/63f8b52a-7618-405d-9601-d24eea2bdbbf

## What can I ask?

- "Which customers have not paid in the last 60 days?"
- "Which HubSpot leads became paying Stripe customers?"
- "Compare this month's Stripe revenue with the target in my Google Sheet."
- "What changed since last week, and which accounts should I follow up with?"

You can ask follow-up questions as you would with an analyst. When a useful
definition or relationship is approved, such as what counts as revenue or how a
contact maps to a customer, that rule can be kept for future questions.

## How it works

<img width="4867" height="2117" alt="workflow" src="https://github.com/user-attachments/assets/d46276f7-58f9-43d9-9a48-2f7c53476ff1" />

You connect your apps and AI assistant once. After that, this loop runs again
for every question. If a value changes in your Google Sheet, the next query
reads the updated value; you do not need to upload the sheet again.

For cross-app questions, it can combine data during the same request. For
example, it can compare current Stripe revenue with targets in Google Sheets
or connect HubSpot leads to their Stripe payment history.

## Why not just upload a file or use an API?

**An uploaded file is a snapshot.** It is easy to analyze, but it becomes stale
as soon as the source changes. You have to export and upload it again.

**An API is a doorway into one app.** It gives a developer access to data, but
it does not tell your AI which fields matter, how records in different apps
relate, or what your business means by "revenue."

**This setup uses those APIs for your AI.** It provides one place to query
multiple apps, adds the business context needed to interpret the results, and
lets that context be reviewed and reused. Once it is set up, you can ask a new
question instead of building a new integration.

## How your data is handled

When you self-host, it runs inside infrastructure you control and queries your
apps only when needed. Your app credentials stay on that server, and MCP
request or response contents are not stored in its request history.

The requested results are sent to the AI assistant you connected so it can
answer your question. The privacy and data-retention policies of that AI
provider still apply.

## What you need

- A deployment, either self-hosted or managed for you.
- At least one supported app: Stripe, HubSpot, or Google Sheets.
- A compatible AI assistant.
- One-time technical help if you choose to self-host and do not deploy software
  yourself.

## For developers

- [Self-hosting and technical setup](SELF-HOSTING.md)
- [Architecture and API reference](AGENTS.md)
- [Contributing](CONTRIBUTING.md)
- [Cross-app model examples](semantic_overlays/README.md)

The project is open source and released under the [Apache License 2.0](LICENSE).
