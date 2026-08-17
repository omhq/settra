---
name: semantic-file
description: Create, update, or review Cube semantic overlays for connected sheet data. Use for worksheet-specific header mappings, types, measures, business dates, grains, assumptions, evidence, and validation.
---

# Sheet data semantic files

Use this skill for workspace-specific models under `semantic_overlays/*.yaml`.
Settra models sheet data. Its current source adapter supports Google Sheets
only. Do not add semantics, connections, examples, or instructions for another
provider.

## Architecture boundary

- Cube Core is the only semantic layer.
- Steampipe provides read-only Google Sheets tables.
- Agents inspect metadata and run Cube REST query JSON, never arbitrary raw SQL.
- The packaged template is `connectors/googlesheets/semantics.yaml`.
- Active per-spreadsheet models are generated under
  `/cube/conf/model/generated/connections`.
- Workspace overlays are mounted at `/cube/conf/model/overlays`.
- Agent-generated files are restricted to
  `/cube/conf/model/overlays/generated`.

## Required workflow

1. Call `list_connections` to find the connected spreadsheet and slug.
2. Call `get_connection_metadata` to find sheets, virtual worksheet tables, and
   exact header-derived columns.
3. Sample and profile only the relevant worksheet tables.
4. Inspect compiled semantics with `list_cubes` and `get_cube`.
5. Inspect existing authored files with `list_semantic_overlays` and
   `get_semantic_overlay` before extending one.
6. Draft the smallest reusable Cube YAML model that answers the requirement.
7. Add `meta.settra` purpose, requirement, grain, assumptions, and evidence to
   every declared cube or view.
8. Validate the YAML with representative Cube REST test queries. Pass the
   existing generated path when validating a replacement.
9. Explain warnings and business decisions. Create or update only after the
   user explicitly approves the mutation.
10. Verify compilation and query results after writing.

## Modeling rules

- Treat row 1 as headers only when metadata confirms the mapping.
- Preserve the exact worksheet tab name and connected schema slug in evidence.
- Define a primary key only when uniqueness has been checked.
- Cast formatted cell text before numeric or date aggregation.
- Use `meta.settra.semantic_type: business_date` for timezone-neutral dates.
- Document blank cells, duplicate headers, duplicate rows, mixed types, and
  formula behavior when they affect interpretation.
- Never infer a business definition silently. Record approved assumptions.
- Never include service-account JSON, tokens, private keys, or sensitive sample
  values in YAML.

## Minimal manifest example

```yaml
cubes:
- name: sales_forecast
  title: Sales Forecast
  description: Governed forecast rows from the Forecast worksheet.
  sql_table: '"forecast_sheet"."Forecast"'
  meta:
    settra:
      purpose: Make forecast rows available to agents.
      requirement: Report forecast by owner and month.
      grain: One row per owner per month.
      assumptions:
        - Owner and month are unique together.
      evidence:
        - source: forecast_sheet.Forecast
  measures:
  - name: rows
    type: count
  dimensions:
  - name: owner
    sql: owner
    type: string
  - name: month
    sql: month
    type: time
    meta:
      settra:
        semantic_type: business_date
```

## Checks

```bash
ruby -e "require 'yaml'; Dir['{connectors/googlesheets,semantic_overlays}/*.y*ml'].sort.each { |p| YAML.load_file(p) }; puts 'cube yaml ok'"
docker compose exec app python -m app.init
git diff --check
```
