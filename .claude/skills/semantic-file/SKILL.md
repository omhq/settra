---
name: semantic-file
description: Create, regenerate, or review Settra connector semantic files. Use when working on connectors/<connector>/semantics.yaml, adding analytics metadata for a Steampipe plugin, or converting table/column docs into metrics, dimensions, joins, filters, and caveats.
paths:
  - connectors/**/semantics.y*ml
  - connectors/**/connection.y*ml
  - connectors/**/prompts/semantic_rules.txt
  - connectors/**/prompts/introspection_*.txt
---

# Settra Semantic File

Create or update Settra semantic metadata in `connectors/<connector-key>/semantics.yaml`.

## Source of Truth

This skill is the canonical authoring reference for Settra semantic files. The current template version is `1`.

## Workflow

1. Read `connectors/<connector-key>/connection.yaml` to identify the connector key, Settra plugin key, docs URL, and expected Steampipe plugin version.
2. Set top-level `plugin` to the value Settra stores for the connection, normally the `plugin` value from `connection.yaml`.
3. Inspect any existing `connectors/<connector-key>/semantics.yaml` and preserve useful user/community edits.
4. Inspect the live schema when available. Prefer actual `information_schema.columns`, cached metadata under `/data/metadata`, or existing connector semantics over guessed columns.
5. Read connector-specific semantic or introspection prompt snippets under `connectors/<connector-key>/prompts/` when present.
6. Use Steampipe plugin docs for table intent and column meaning when local schema detail is incomplete.
7. Generate or update only `connectors/<connector-key>/semantics.yaml` unless the user asks for broader connector changes.
8. Keep the file valid YAML and use this top-level structure:
   - `plugin`
   - `version`
   - `generated_by`
   - `validated`
   - optional `ignored_column_postfixes`
   - `tables`
9. For every table, include `label`, `description`, `grain`, `type`, and useful `columns`.
10. Add `primary_time_column` when the table has an obvious default timestamp.
11. Treat created/updated timestamps as record lifecycle dates; for business events, status changes, or interval calculations, prefer a more specific semantic date column when one is available.
12. Add metrics only when the SQL expression is safe at the table grain.
13. Add dimensions for common groupings. Use `column` for direct columns and `sql` for expressions.
14. Add `common_filters`, `common_joins`, and `caveats` when they prevent bad queries.

## Canonical Structure Template

```yaml
plugin: plugin_key # Must match connection.yaml plugin.
version: 1 # Template/schema version for this file.
generated_by: ai # ai | community | user
validated: false # true only after testing against live schema.
ignored_column_postfixes: # Optional connector-level deterministic omissions. Currently, the Steampipe ones.
  - _ctx
  - sp_ctx

tables:
  source_table_name:
    label: Human Label
    description: What this table represents and when to use it.
    grain: id # One row per what? Be explicit.
    type: fact # fact | dimension | bridge
    primary_time_column: created_at # Optional default time column.
    notes: Optional high-signal usage guidance for the agent.

    columns:
      id:
        label: Record ID
        type: primary_key # primary_key | foreign_key | metric | dimension | date | json
        description: Stable row identifier.

      account_id:
        label: Account
        type: foreign_key
        references: account.id
        description: Joins this table to the account table.

      amount:
        label: Amount
        type: metric
        transform: amount / 100.0 # Optional SQL expression for normalized use.
        unit: currency # currency | count | percent | duration | bytes | custom
        currency_column: currency
        description: Raw amount stored in minor currency units.

      status:
        label: Status
        type: dimension
        values: [active, inactive]
        description: Known status enum values when available.

      created_at:
        label: Created Date
        type: date
        grain: day
        description: Record creation timestamp.

    metrics:
      total_amount:
        label: Total Amount
        sql: sum(amount) / 100.0
        unit: currency
        currency_column: currency
        description: Total amount in major currency units.

      records:
        label: Records
        sql: count(*)
        unit: count
        description: Number of records.

    dimensions:
      by_status:
        label: By Status
        column: status
        description: Group results by status.

      by_month:
        label: By Month
        sql: date_trunc('month', created_at)
        description: Calendar month bucket.

    common_filters:
      - label: Active only
        sql: status = 'active'
      - label: Last 30 days
        sql: created_at >= now() - interval '30 days'

    common_joins:
      - account on source_table_name.account_id = account.id

    caveats:
      - Mention fanout risks, nullable fields, JSON extraction, or API quirks.
```

## Semantics Rules

- `plugin` must match the connector plugin key loaded from `connection.yaml`.
- `version` is the semantic template version. Use `1` for the current format.
- `generated_by` records provenance: `ai`, `community`, or `user`.
- `validated` should stay `false` until table names, columns, joins, and metric SQL have been checked against a live Steampipe schema.
- `ignored_column_postfixes` removes noisy generated/system columns from deterministic semantic introspection before draft rows are stored. Exact column names can be listed here too because exact names match as suffixes.
- `grain` must state one row per what. This is the most important anti-fanout hint.
- `type` must be one of `fact`, `dimension`, or `bridge`.
- Column `type` should be one of `primary_key`, `foreign_key`, `metric`, `dimension`, `date`, or `json` when known.
- Created/updated date columns usually describe the record lifecycle. Use them when that lifecycle is the analytical event, but prefer a more specific semantic date for business event timing when one exists.
- Use `metrics.*.sql`, not `expression`, for canonical metric expressions.
- `metrics.*.sql` and `dimensions.*.sql` should be valid PostgreSQL expressions at the table grain.
- Use `dimensions.*.column` for simple group-by columns.
- Use `columns.*.transform` for normalized values such as minor-unit money, percentages, timestamps, JSON extraction, or casted dates.
- Use `columns.*.references` for foreign keys in `table.column` form.
- `common_filters`, `common_joins`, and `caveats` should be short, practical, and SQL-oriented because they are fed directly into SQL planning context.
- Do not use a metric or join if it can create fanout at the declared grain.

## Validation

After editing, run YAML parsing:

```bash
ruby -e "require 'yaml'; Dir['connectors/*/semantics.y*ml'].sort.each { |p| YAML.load_file(p) }; puts 'semantic yaml ok'"
```

When Python dependencies are available, also compile the backend. When Docker is available, run the backend semantic loader:

```bash
python3 -m compileall backend/app
docker compose run --rm --no-deps app python -c "import asyncio; from app.semantic.loader import load_semantic_layer; asyncio.run(load_semantic_layer()); print('semantic loaded')"
```
