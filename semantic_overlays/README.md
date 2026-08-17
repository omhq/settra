# Sheet data semantic overlays

This directory contains workspace-specific Cube YAML for connected sheet data.
The packaged model under `connectors/googlesheets/semantics.yaml` describes the
current Google Sheets adapter; overlays describe what a particular worksheet
means to its users and to automated agents.

Use an overlay when an agent needs stable semantics for a worksheet, including:

- a clean model name for a real tab;
- explicit header-to-field mappings;
- one-row grain and primary-key rules;
- numeric, currency, boolean, or business-date conversions;
- measures such as counts, totals, averages, or target attainment;
- approved assumptions, caveats, and validation evidence.

Keep one YAML file per coherent spreadsheet domain. Use lower snake case names,
for example `sales_forecast.yaml` or `customer_health.yaml`.

Every cube or view should preserve its intent under `meta.settra`:

```yaml
meta:
  settra:
    purpose: Explain why agents need this model.
    requirement: Preserve the originating user request.
    grain: One row per account per month.
    assumptions:
      - Header row 1 contains unique field names.
    evidence:
      - source: sales_forecast.Forecast
```

Generated overlays created through MCP are stored beneath
`/cube/conf/model/overlays/generated`. They must be validated before creation or
replacement and require explicit user approval. Delete failed experiments from
the admin UI.

Do not put credentials, service-account JSON, private spreadsheet IDs, or
sampled sensitive values in an overlay.
