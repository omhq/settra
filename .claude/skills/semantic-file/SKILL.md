---
name: semantic-file
description: Create, update, or review Cube semantic overlay files under semantic_overlays/*.yaml. Use when building cross-app Cube YAML cubes that combine existing connector models such as Stripe, HubSpot, or Google Sheets through Steampipe FDW; adding overlay measures, dimensions, segments, SQL, or caveats; validating Cube overlay files; or moving workspace-specific semantics out of connector-owned models.
paths:
  - semantic_overlays/**/*.y*ml
  - semantic_overlays/README.md
---

# Cube Semantic Overlay Files

Help create and maintain Cube YAML overlay files in `semantic_overlays/`.
Overlay files are mounted into Cube at `/cube/conf/model/overlays` and are used
for workspace-specific cross-app semantics that do not belong in an individual
connector model.

## Architecture Context

```text
MCP client
        |
        v
/mcp streamable HTTP  ->  FastAPI backend (:8000)
        |                     +-- MCP tools backed by Cube metadata and queries
        |                     +-- /cube/conf/model (mounted Cube YAML)
        |                     +-- Steampipe FDW (:9193) for live app schemas
        v
Cube Core (:4000)  ->  compiles model, exposes /cubejs-api/v1
```

- Cube Core is the canonical semantic layer. MCP clients use Cube as the
  semantic contract—they do not query raw Steampipe tables directly.
- Steampipe exposes saved app connections as PostgreSQL FDW schemas.
- Connector-owned Cube models live in `connectors/<connector-key>/semantics.yaml`
  and should stay focused on their own app.
- Overlay files live in `semantic_overlays/*.yaml` and define curated Cube YAML
  models across apps or workspace-specific domains.
- Agent-generated overlays are written under
  `/cube/conf/model/overlays/generated` via MCP create/update tools.
- Do not create or edit `connection.yaml`, `.spc` credential files, or
  `semantic_*` persistence for overlay work.

## Model File Layout

Connector definitions:

```text
connectors/<connector-key>/connection.yaml
connectors/<connector-key>/semantics.yaml   # template, not the live model
```

When a saved connection exists, Settra generates an active connection-specific
Cube model under
`/cube/conf/model/generated/connections/<connection-slug>.yaml`. The generated
file rewrites `sql_table` schemas to the actual Steampipe connection slug and
prefixes cube names when needed to avoid collisions. For example, a Stripe
connection named `stripe_sandbox` generates `stripe_sandbox_charge` with
`sql_table: '"stripe_sandbox"."stripe_charge"'`.

| Source type            | Meaning                                                                                                                      |
| ---------------------- | ---------------------------------------------------------------------------------------------------------------------------- |
| `bundled_connector`    | Static connector semantics from `connectors/<key>/semantics.yaml`; templates only.                                           |
| `generated_connection` | Active connection-specific model under `/cube/conf/model/generated/connections`.                                             |
| `overlay`              | Hand-authored workspace overlay under `/cube/conf/model/overlays`.                                                           |
| `generated_overlay`    | Agent-generated overlay under `/cube/conf/model/overlays/generated`.                                                         |

Hand-authored overlays live in `semantic_overlays/`, mounted at
`/cube/conf/model/overlays`. Read-only discovery covers hand-authored and
generated overlays, including files that did not compile. Agent writes are
restricted to `/cube/conf/model/overlays/generated`.

## MCP Workflow for Generated Overlays

The server instructions tell agents to prefer existing compiled cubes and
measures, inspect bounded metadata/profile evidence before proposing cross-app
relationships, and create semantic overlays only after explicit user approval.
Generated overlays should preserve purpose, grain, assumptions, relationship
rules, metric definitions, evidence, and validation results.

Recommended workflow:

1. Call `list_connections`.
2. Call `get_connection_metadata` for relevant connections.
3. Call `sample_connection_table` and `profile_connection_table` for
   user-specific or unfamiliar tables.
4. Inspect compiled semantics with `list_cubes` and `get_cube`, then call
   `list_semantic_overlays` to discover authored, failed, duplicate, or stale
   overlays.
5. Call `get_semantic_overlay` before extending or replacing an existing model.
6. Draft the smallest reusable Cube YAML overlay. Preserve provenance under
   each cube or view's `meta.settra` mapping.
7. Call `validate_semantic_overlay` with the proposed YAML and representative
   Cube REST `test_queries`; for replacements, pass the existing generated
   overlay path.
8. Explain the validation result, warnings, assumptions, and any business
   decisions that still need approval.
9. Use `create_semantic_overlay` for a new approved path or
   `update_semantic_overlay` for an approved replacement.
10. Verify with `list_cubes`, `get_semantic_overlay`, and `query_cube`.
11. Ask the user to clean up failed experiments manually from the admin UI.

### MCP Tools for Semantic Work

| Tool                        | Purpose                                                                                                                                           |
| --------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------- |
| `list_cubes`                | Search compiled cubes; member previews are opt-in and capped; use `get_cube` for one-cube detail.                                               |
| `get_cube`                  | Compact semantic definition with source, SQL, filters, references, relationships.                                                                 |
| `query_cube`                | Execute bounded Cube REST query JSON; business dates normalized to `YYYY-MM-DD`.                                                                |
| `get_cube_meta`             | Search compact Cube `/v1/meta` detail; member collections opt-in and capped.                                                                      |
| `list_connections`          | Saved connections without secrets, including slugs used in generated cube names.                                                                  |
| `get_connection_metadata`   | Bounded live-table catalog; first ten columns per table by default.                                                                               |
| `sample_connection_table`   | Compact positional rows with column names once.                                                                                                   |
| `profile_connection_table`  | Sampled column profile keyed by name; opt-in descriptions.                                                                                        |
| `list_semantic_overlays`    | Overlay summaries with path, models, compile state, manifest state, purpose.                                                                      |
| `get_semantic_overlay`      | Exact overlay YAML with compile status; use `get_cube` for compiled semantics.                                                                    |
| `validate_semantic_overlay` | Dry-run proposed Cube YAML; failures include compiler diagnostics.                                                                               |
| `create_semantic_overlay`   | Create validated, approved generated overlay; fail if path exists.                                                                                |
| `update_semantic_overlay`   | Replace existing validated overlay; diff summary by default.                                                                                      |

MCP tool responses omit normal defaults, empty optional metadata, and request
echoes. Use original call arguments plus `total` and `next_cursor` for
pagination.

The sample/profile tools are structured introspection tools, not raw SQL
execution. They are bounded, redact obvious secret-like columns, and reconstruct
Google Sheets virtual worksheet tables from `googlesheets_cell` so agents can
infer columns such as dates, owners, notes, and revenue targets before writing
Cube YAML.

### Provenance Fields

New or updated generated overlays require these fields on every declared cube
or view. Preserve `relationships`, `metrics`, `validation`, and `approval`
when relevant:

```yaml
meta:
  settra:
    purpose: Compare revenue targets with matched actual revenue
    requirement: Show monthly target, actual, attainment, gap, and unmatched revenue
    grain: One row per month
    assumptions:
      - Stripe customers match HubSpot contacts by normalized email
    relationships:
      - from: stripe_customer.email
        to: hubspot_contact.email
        cardinality: many_to_one after HubSpot email deduplication
    evidence:
      matched_customers: 10
      unmatched_customers: 2
      revenue_coverage_percent: 98.4
```

For timezone-neutral business dates, mark the Cube member with
`meta.settra.semantic_type: business_date`. `query_cube` renders those values as
`YYYY-MM-DD` instead of timestamp strings so clients do not shift them into a
viewer-local timezone.

## Overlay Authoring Workflow

1. Identify the cross-app question, target domain, and source apps.
2. Read `semantic_overlays/README.md`, any relevant existing overlay, and the
   involved connector Cube YAML files under `connectors/*/semantics.yaml`.
3. Prefer live metadata before relying on assumptions. Use MCP tools
   (`list_cubes`, `get_cube`, `get_cube_meta`, `query_cube`) when available, or
   the HTTP API/Cube metadata endpoints otherwise.
4. Add one overlay YAML file per cross-app domain, using lower snake_case names
   such as `hubspot_stripe.yaml`, `googlesheets_stripe.yaml`, or
   `hubspot_stripe_pipeline_targets.yaml`.
5. Define new curated overlay cube names. Do not redefine connector-owned cube
   names from `connectors/*/semantics.yaml`.
6. Use explicit Cube `sql:` for overlay cubes. For Steampipe cross-plugin joins,
   materialize each app-side slice in a CTE before joining across apps.
7. Prefer deterministic identity bridges before exposing measures: normalized
   email, normalized domain, provider IDs, or another stable key with duplicate
   handling.
8. Declare a clear grain, primary key dimension, useful measures, grouping
   dimensions, segments, and practical caveats.
9. Keep YAML valid, keep SQL PostgreSQL-compatible for Steampipe/Cube, and avoid
   unrelated connector or admin changes.

## Overlay Rules

- Use Cube YAML directly with a top-level `cubes:` array.
- Use `sql_table` only for simple connector-local cubes. Overlay cubes should
  normally use explicit `sql:` with CTEs.
- Keep connector semantics app-local; put cross-app joins, bridges, and
  workspace-specific slices in overlays.
- Quote Steampipe schema/table names in SQL, for example
  `"stripe"."stripe_charge"` and `"hubspot"."hubspot_contact"`.
- If saved connection slugs differ from connector keys, update overlay SQL table
  references to the actual Steampipe schema names.
- For cross-source joins, select only the needed columns from each source before
  joining. This makes Cube SQL easier to inspect and reduces Steampipe planner
  surprises.
- For duplicate-prone identity bridges, rank candidates with `row_number()` and
  filter to one match before the final join to avoid measure fanout.
- Put normalized money, dates, booleans, and identity fields in dimensions so
  MCP clients can inspect and group results without guessing expressions.
- Use measure SQL that is safe at the declared grain. Avoid measures that double
  count because of one-to-many joins.
- Include high-signal descriptions. State when to use the cube, the grain, and
  caveats such as nullable matches, duplicate handling, custom properties, or
  portal-specific fields.

## Recommended Cube Pattern

```yaml
cubes:
- name: stripe_hubspot_charge
  title: Stripe Charges With HubSpot Contacts
  description: |
    Cross-app charge analysis enriched with the best matching HubSpot contact.

    charge_id (one row per Stripe charge)

    Use this cube for Stripe revenue and charge questions grouped by HubSpot
    contact attributes.

    Caveats: Matching uses lowercased Stripe customer email to lowercased
    HubSpot contact email. If multiple HubSpot contacts share an email, select
    one deterministic match before exposing revenue measures.
  sql: |
    WITH stripe_charge_customer AS MATERIALIZED (
      SELECT
        charge.id AS charge_id,
        charge.created AS charge_created,
        charge.amount AS amount,
        charge.amount_refunded AS amount_refunded,
        charge.currency AS currency,
        charge.status AS status,
        customer.email AS stripe_customer_email
      FROM "stripe"."stripe_charge" AS charge
      LEFT JOIN "stripe"."stripe_customer" AS customer
        ON coalesce(substring(charge.customer from 'ID:([^ ]+)'), charge.customer) = customer.id
    ),
    hubspot_contact_match AS MATERIALIZED (
      SELECT *
      FROM (
        SELECT
          contact.id AS hubspot_contact_id,
          contact.email AS hubspot_contact_email,
          contact.lifecyclestage AS hubspot_lifecycle_stage,
          row_number() OVER (
            PARTITION BY lower(contact.email)
            ORDER BY contact.updated_at DESC NULLS LAST, contact.created_at DESC NULLS LAST, contact.id
          ) AS email_match_rank
        FROM "hubspot"."hubspot_contact" AS contact
        WHERE contact.email IS NOT NULL
          AND contact.email <> ''
      ) AS ranked
      WHERE email_match_rank = 1
    )
    SELECT
      stripe_charge_customer.*,
      hubspot_contact_match.hubspot_contact_id,
      hubspot_contact_match.hubspot_contact_email,
      hubspot_contact_match.hubspot_lifecycle_stage
    FROM stripe_charge_customer
    LEFT JOIN hubspot_contact_match
      ON lower(stripe_charge_customer.stripe_customer_email) =
         lower(hubspot_contact_match.hubspot_contact_email)

  measures:
  - name: charges
    title: Charges
    description: Count of Stripe charges.
    type: count
  - name: net_charged_amount
    title: Net Charged Amount
    description: Charged amount minus refunded amount in major currency units.
    type: sum
    sql: (amount - coalesce(amount_refunded, 0)) / 100.0
    format: currency

  dimensions:
  - name: id
    title: Charge ID
    sql: charge_id
    type: string
    primary_key: true
    description: Stripe charge id; the grain of this overlay cube.
  - name: created
    title: Charge Date
    sql: charge_created
    type: time
    description: Charge creation timestamp.
  - name: hubspot_lifecycle_stage
    title: HubSpot Lifecycle Stage
    sql: hubspot_lifecycle_stage
    type: string
    description: Lifecycle stage for the deterministically matched HubSpot contact.

  segments:
  - name: succeeded_only
    title: Succeeded only
    sql: status = 'succeeded'
```

## Google Sheets Overlays

Use the same pattern for Google Sheets by treating the sheet-backed table as a
dimension or target table and joining it to connector records in a new overlay
file. Examples:

- `googlesheets_stripe.yaml`
- `hubspot_stripe_pipeline_targets.yaml`

Prefer explicit normalization in the CTEs, such as lowercased emails, trimmed
domains, casted dates, or numeric target values. If the sheet can contain
duplicates, rank or aggregate it before joining to revenue or count measures.

## Validation

After editing overlay YAML, parse Cube YAML files:

```bash
ruby -e "require 'yaml'; Dir['{connectors/*,semantic_overlays}/*.y*ml'].sort.each { |p| YAML.load_file(p) }; puts 'cube yaml ok'"
```

When Docker is available, verify the mounted Cube model view and Cube metadata:

```bash
docker compose exec app python -m app.init
```

For a new or changed overlay cube, also run a small Cube query through MCP
`query_cube` or `POST /api/query/`, such as a count measure with a low limit.
Fix Cube compile errors, missing columns, fanout, or schema-slug mismatches
before calling the overlay done.

For full MCP tool schemas, HTTP API paths, and environment variables, see
[`AGENTS.md`](../../../AGENTS.md) at the repository root.
