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

## Current Model

- Cube Core is the canonical semantic layer.
- Steampipe exposes saved app connections as PostgreSQL FDW schemas.
- Connector-owned Cube models live in `connectors/<connector-key>/semantics.yaml`
  and should stay focused on their own app.
- Overlay files live in `semantic_overlays/*.yaml` and define curated Cube YAML
  models across apps or workspace-specific domains.
- Do not create or edit `connection.yaml`, `.spc` credential files, or 
  `semantic_*` persistence for overlay work.

## Workflow

1. Identify the cross-app question, target domain, and source apps.
2. Read `semantic_overlays/README.md`, any relevant existing overlay, and the
   involved connector Cube YAML files under `connectors/*/semantics.yaml`.
3. Prefer live metadata before relying on assumptions. Use MCP tools
   (`list_cubes`, `get_cube`, `get_cube_meta`, `query_cube`) when available, or
   the HTTP API/Cube metadata endpoints otherwise.
4. Add one overlay YAML file per cross-app domain, using lower snake_case names
   such as `hubspot_stripe.yaml`, `googlesheets_stripe.yaml`, or
   `hubspot_stripe_pipeline_targets.yaml`, etc...
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
`query_cube` or `/api/query/`, such as a count measure with a low limit. Fix
Cube compile errors, missing columns, fanout, or schema-slug mismatches before
calling the overlay done.
