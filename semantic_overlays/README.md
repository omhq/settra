# Semantic overlays

Files in this directory are mounted into Cube at `/cube/conf/model/overlays`.

Use overlays for workspace-specific cross-app semantics that do not live in
an individual connector model. Connector YAML files under `connectors/*` stay 
focused on their own app.

Recommended pattern:

- Add one YAML file per cross-app domain, such as `hubspot_stripe.yaml`.
- Define curated cross-app cubes with explicit SQL instead of redefining
  connector-owned cube names.
- For Steampipe cross-plugin joins, materialize each app-side slice in a CTE
  before joining across apps. This avoids planner issues and makes match logic
  easier to inspect.
- Prefer deterministic identity bridges, such as normalized email with
  duplicate handling, before exposing revenue or count measures.

Google Sheets overlays follow the same pattern by joining a sheet-backed
dimension table to connector records in a new file, for example
`googlesheets_stripe.yaml` or `hubspot_stripe_pipeline_targets.yaml`.
