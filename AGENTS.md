# Settra — agent and developer reference

Settra is a self-hosted platform that turns useful AI answers into reusable data
artifacts. Users start with a business question, review the answer and its
definitions, then save an artifact they can rerun as the data changes, share,
and build on. Supported sources are native Google Sheets, CSV, Excel, and
Parquet files selected through Google Picker. dlt
performs complete loads into PostgreSQL, Cube Core is the canonical semantic
layer, and the MCP surface exposes bounded discovery, artifact authoring, and
Cube REST query execution.

A data artifact saves the sources, instructions, semantic models, relationships,
parameters, executable graph, and named results behind an answer. Data artifacts
can currently be built, tested, executed, and queried in Settra or through MCP
clients. Scheduled delivery to email, Slack, or other communication channels is
planned but not implemented;
product copy and API documentation must not present those channels as available
until the corresponding runtime behavior exists.

Use **data artifact** on first mention in user-facing copy and **artifact**
thereafter. Public product identifiers use `artifact`, including
`/api/artifacts`, `/data/artifacts`, `list_artifacts`, and `ArtifactSlug`.
Database tables and established internal service names retain `collection`.
Reserve **data app** for a future interactive experience powered by one or more
artifacts; do not use `app` for the current artifact domain object.

## Guardrails

- The application runtime is Python 3.12, pinned by the Docker image. Use its
  native annotation syntax and do not add `from __future__ import annotations`.
- Keep Google Drive as the only source provider. Supported tabular formats are
  Google Sheets, CSV, Excel, and Parquet. Do not add provider selection,
  third-party source plugins, or cross-provider examples.
- Keep MCP clients on the Cube semantic contract. Tools inspect Cube metadata or
  execute Cube REST query JSON; they do not accept raw PostgreSQL SQL.
- Keep Cube Core as the only semantic layer.
- Do not ship default Cube models or semantic overlay files. Every active model
  must come from a successful user-source sync or an explicitly authored
  user-specific overlay.
- Active source models are generated under
  `/cube/conf/model/generated/connections` from successful sync manifests.
- Source-specific semantic edits live at runtime under
  `/cube/conf/model/overlays`. Agent-generated overlays are restricted to
  `/cube/conf/model/overlays/generated`.
- `/api/query/` accepts Cube REST query JSON. It is not a SQL endpoint.
- A Settra-owned PostgreSQL schema stores users, organizations, memberships,
  hashed browser sessions, source connection metadata, sync-run summaries,
  collections, OAuth state, and privacy-safe MCP metrics.
  Google credentials and MCP payload contents are not stored there.
- Google OAuth secrets are encrypted with `SECRET_KEY` on the data volume and
  never written to source YAML or generated Cube YAML.
- Sources, destinations, and pipes are separate concepts. Each pipe references
  one registered destination and owns one fixed namespace within it. Sync YAML
  may describe that binding but may not redirect the pipe around its database
  `destination_id` or fixed destination schema.
- Keep artifacts centered on reusable answers to business questions. Human users
  provide the outcome and approve material business definitions; agents may
  inspect sources, draft semantics, validate assumptions, and compose executable
  graphs.
- Keep current and planned capabilities explicit. Do not add examples that imply
  scheduled email, Slack, WhatsApp, or other outbound delivery exists before a
  delivery runtime and its authorization model are implemented.

## Architecture

```text
Google Drive API + Google Sheets API
        |
        | file-specific OAuth via Google Picker
        v
FastAPI + dlt (:8000)
        |
        | full replace, insert-from-staging
        v
PostgreSQL (:5432)
        |
        v
Cube Core (:4000)
        |
        v
/mcp streamable HTTP -> automated agent / MCP client
```

The FastAPI process also owns the lean cron scheduler, Google OAuth flow,
per-source YAML validation, schema introspection, generated Cube models, MCP
metadata/sample/profile tools, and Cube REST proxy. No separate scheduler or
loader container is required.

Semantic behavior is organized by responsibility:

- `backend/app/semantic/catalog.py` owns semantic discovery, model provenance,
  dependency traversal, and organization-visible model selection.
  The collection inventory lists source-scoped cubes and views independently of
  whole-file authorization and compilation. Collection-owned overlays remain
  visible for repair when their sources disappear; this does not authorize queries
  against models with unavailable dependencies. Shared files expose only scoped
  definitions and remain read-only when not every model belongs to the collection.
- `backend/app/semantic/query.py` owns the shared Cube-query contract and model
  reference validation used by HTTP, MCP, artifacts, and artifact graphs.
- `backend/app/semantic/overlays.py` owns overlay paths, manifests, discovery,
  and Cube compile/removal polling. Overlay saves and reads must confirm the
  exact authored revision, using `backend/app/cube/revisions.py` and the
  fingerprint that `cube/cube.js` attaches to compiler input without changing
  persisted YAML; model names or a changed compiler ID alone are insufficient.
- `backend/app/semantic/relationships.py` owns collection relationship discovery,
  structural validation, Cube execution probes, and the authored-join read model.
  Author joins with semantic references such as `{CUBE.customer_id} = {Customers.id}`,
  never by assuming a public member name is a physical column. Snapshot key
  resolution follows dimension SQL and same-cube aliases; unresolved expressions
  must fail validation explicitly rather than substitute a guessed column.
- `backend/app/semantic/overlay_validation.py` owns the complete ephemeral
  overlay-validation workflow. `backend/app/semantic/validation_status.py`
  shares cleanup-failure detection with response projection. Cleanup must be
  confirmed on disk and in Cube; failure makes overall validity/readiness false
  while preserving candidate compile evidence and exposing diagnostics.
  MCP routes only authorize, invoke domain behavior, and project responses.
- `backend/app/collection_build_service.py` owns collection-scoped model
  authoring, relationship draft preparation, stale replacement checks, and the
  bounded query tester. The collection UI and MCP author the same Cube YAML;
  relationships are joins, never separate product database records.
- `backend/app/cube/model_repository.py` is the filesystem adapter for Cube YAML;
  `backend/app/cube/model_generation.py` generates connection models from sync
  manifests. Generated models retain stable public Cube names and use bounded,
  deterministic `sql_alias` values when Cube's PostgreSQL member aliases would
  exceed 63 characters. `backend/app/cube/model.py` is the shared repository and
  generation entry point.
- `backend/app/cube/identifiers.py` owns shared deterministic member shortening
  and SQL alias budgeting for source generation and relationship model copies.
  Alias budgets include dimensions and measures after Cube's name normalization
  and use PostgreSQL's UTF-8 byte limit. Keep public Cube model/member names stable.
- `backend/app/calculations/` owns the calculation schema, graph validation,
  dependency planning, safe formula evaluation, bounded Cube-backed execution,
  and structured `aggregate_query` compilation for synchronized PostgreSQL
  snapshots. Aggregate identifiers must resolve through organization-scoped
  connection metadata, filter values stay parameterized, and grouped results are
  aggregated in PostgreSQL before bounded result pagination.
- `backend/app/collection_graph_service.py` owns the one canonical execution
  graph per artifact, separate bounded layout metadata, and optimistic revisions.
- `backend/app/dependency_impact_service.py` owns read-only impact previews for
  model deletion, artifact source removal, source deletion, and potential source
  schema changes. It follows the existing semantic dependency graph and traces
  affected artifact graph steps through named results. Model deletion reports every
  artifact where a shared authored model is visible.

Keep Cube storage and generation adapters independent of collection services.
Routes should call reusable semantic/application services instead of owning
semantic behavior themselves; Cube model persistence must never import a route
or collection service.

Reusable semantic, Cube, collection, and calculation modules must remain
transport-neutral: raise errors from `backend/app/errors.py`, never FastAPI
`HTTPException`. HTTP adapters map those errors in
`backend/app/routers/error_handlers.py`; MCP adapters map them to tool errors at
their boundary. `CubeAPIError` belongs to the Cube client adapter and may cross
the reusable layer so each transport can preserve the upstream status and
retryability.

The signed-in workspace's **Data** area manages its Google account, tabular-file pipes,
sync state and configuration, synchronized schemas, and collections. It presents
the destination separately on every pipe. The only current choice is the default
managed PostgreSQL destination, configured by deployment environment variables.

## Google Drive tabular loading behavior

Each saved connection is a pipe from one Drive `file_id` to one registered
destination. The current managed PostgreSQL destination assigns a stable schema
initially named from the connection slug. A sync:

1. Decrypts the saved Google refresh token in process.
2. Constructs a dlt `GcpOAuthCredentials` object and refreshes access as needed.
3. Inspects Drive metadata and detects Google Sheets, CSV, Excel, or Parquet.
   User-authored YAML may override the detected format.
4. Reads native Sheets through the Sheets API and downloads blob files through
   the Drive API. CSV delimiter, encoding, and header row are detected initially
   and persisted to YAML unless explicitly configured. Excel uses one table per
   selected worksheet; Parquet uses its embedded schema.
5. Applies YAML table/column rules and loads every enabled table with
   `write_disposition: replace` and
   `replace_strategy: insert-from-staging`. Empty, headerless, and disabled
   tables are skipped.
6. Removes previously managed tables that are no longer selected.
7. Applies PostgreSQL table/column comments.
8. Writes a privacy-safe manifest, refreshes bounded metadata, and regenerates
   Cube YAML.

The adapter currently reads each selected table into memory. Downloaded blob
contents are transient and are not written to the data volume. Add disk-backed
staging only for a concrete large-file or replay requirement; PostgreSQL is the
durable copy.

Per-source config lives at `/data/connections/<storage-key>.yaml`. The storage
key is globally unique while the displayed slug is organization-local. Example:

```yaml
version: 1
source:
  type: google_drive
  file_id: 1AbC_example
  file_name: sales_forecast.csv
  mime_type: text/csv
  format: csv
  sheets: [Orders, "Forecast *"]
  parsing:
    delimiter: comma
    encoding: utf-8-sig
    header_row: 1
destination:
  key: built_in_postgres
  type: postgres
  schema: sales_forecast
load:
  write_disposition: replace
  replace_strategy: insert-from-staging
  schema_contract:
    tables: evolve
    columns: evolve
    data_type: evolve
  schedule:
    enabled: true
    cron: "0 * * * *"
    timezone: UTC
schema:
  tables:
    Orders:
      table_name: orders
      description: One row per order
      columns:
        Order ID:
          name: order_id
          data_type: bigint
          description: Stable order identifier
        Ordered On:
          data_type: date
          description: Timezone-neutral business date
```

Table and column rules also accept `enabled: false`. Columns accept
`nullable: false`. Supported dlt type overrides are `binary`, `text`, `bigint`,
`double`, `bool`, `timestamp`, `date`, `decimal`, and `json`.

Allowed `source.format` values are `auto`, `google_sheets`, `csv`, `excel`, and
`parquet`. Delimiter, encoding, and header row may remain `auto`; a per-table
`header_row` overrides the source default.

For timezone-neutral dates in Cube, set
`meta.settra.semantic_type: business_date`; `query_cube` renders those values as
`YYYY-MM-DD` so clients do not apply viewer-local timezone shifts.

## MCP surface

The server is mounted at `/mcp` using streamable HTTP; `/mcp` normalizes to
`/mcp/`. MCP access requires a user-bound OAuth bearer token carrying the active
organization. The provider publishes discovery under `/.well-known/*` and
endpoints under `/oauth/*`. The global MCP URL starts with artifact discovery.

OAuth authorization always presents the user's organization memberships and
pins the resulting grant to the organization they choose. Membership is checked
again on every MCP request. The `settra:write` scope is granted only to owners
and admins; member and viewer grants remain read-only.

Source creation and configuration are user-only workflows in the signed-in
browser under **Data > Sources**. MCP must not offer or imply source creation or
configuration. If asked, direct the user to that browser workflow. After the
source exists, MCP can list it globally or by artifact and describe its synchronized
schema globally or by artifact; artifact membership changes use `update_artifact`.

Available tools:

| Tool                               | Purpose                                                                                   |
| ---------------------------------- | ----------------------------------------------------------------------------------------- |
| `list_artifacts`                   | List compact artifacts.                                                                   |
| `get_artifact_context`             | Load one artifact's instructions, pipes, destination tables, and cubes.                   |
| `create_artifact`                  | Create an artifact with optional existing pipe membership.                                |
| `update_artifact`                  | Change an artifact's metadata, instructions or complete pipe membership.                  |
| `delete_artifact`                  | Delete an empty artifact while retaining source snapshots.                                |
| `list_cubes`                       | Search a bounded catalog of compiled cubes.                                               |
| `get_cube`                         | Fetch one compact semantic definition.                                                    |
| `query_cube`                       | Execute one bounded Cube REST query object.                                               |
| `get_cube_meta`                    | Search compact Cube `/v1/meta` detail.                                                    |
| `list_connections`                 | List all workspace pipes globally or only one artifact's pipes.                           |
| `get_connection_metadata`          | Describe bounded synchronized tables and columns globally or for one artifact.            |
| `sync_connection`                  | Refresh one artifact pipe and regenerate its source Cube model.                           |
| `sample_connection_table`          | Fetch compact positional PostgreSQL snapshot rows.                                        |
| `profile_connection_table`         | Return a bounded sample profile by column.                                                |
| `list_semantic_overlays`           | List authored and generated sheet overlays.                                               |
| `get_semantic_overlay`             | Read exact overlay YAML and compile status.                                               |
| `validate_semantic_overlay`        | Dry-run proposed Cube YAML and test queries.                                              |
| `create_semantic_overlay`          | Create an approved generated overlay.                                                     |
| `update_semantic_overlay`          | Replace an approved generated overlay.                                                    |
| `delete_semantic_overlay`          | Delete a writable semantic overlay owned by one artifact.                                 |
| `preview_dependency_impact`        | Preview affected models, joins and artifact graph results before model or source changes. |
| `list_relationships`               | List structurally inspected authored joins in one artifact.                               |
| `draft_relationship`               | Prepare complete Cube YAML to create, edit or remove one join.                            |
| `validate_relationships`           | Probe compiled joins and synchronized snapshot cardinality.                               |
| `get_artifact_graph`               | Read one artifact's canonical graph YAML, layout and revision.                            |
| `manage_artifact_graph`            | Replace an artifact graph and layout using optimistic revision protection.                |
| `validate_artifact_graph`          | Validate a saved or proposed complete artifact graph.                                     |
| `execute_artifact_graph`           | Execute all artifact outputs or one target dependency closure.                            |
| `list_artifact_graph_parameter_options` | Return bounded Cube-derived artifact graph parameter choices.                        |

Available resources:

| Resource                                                 | Purpose                                     |
| -------------------------------------------------------- | ------------------------------------------- |
| `settra://artifacts/{artifact}/semantics/meta`            | Compiled metadata filtered to one artifact. |
| `settra://artifacts/{artifact}/semantics/cubes`           | First artifact cube page.                   |
| `settra://artifacts/{artifact}/semantics/cubes/{name}`    | Compact artifact cube or view.              |
| `settra://artifacts/{artifact}/semantics/model/{path}`    | Artifact-bounded Cube YAML file.            |

For the model-file resource, percent-encode slashes inside nested `{path}`
values. For example, use
`generated%2Fconnections%2Fsales_forecast.yaml`, not
`generated/connections/sales_forecast.yaml`.

## HTTP API

Except for registration configuration, registration, login, the Google OAuth
callback, and product naming, `/api` routes require an HTTP-only browser session.
Unsafe session-authenticated methods also require the matching CSRF cookie/header.

| Method           | Path                                                  | Purpose                                                                                        |
| ---------------- | ----------------------------------------------------- | ---------------------------------------------------------------------------------------------- |
| `GET`            | `/api/auth/config`                                    | Return public registration availability.                                                       |
| `POST`           | `/api/auth/register`                                  | Create an account and private personal organization.                                           |
| `POST`           | `/api/auth/login`                                     | Create an HTTP-only browser session.                                                           |
| `GET`            | `/api/auth/google/start`                              | Start optional Google OpenID Connect account login.                                            |
| `GET`            | `/api/auth/google/callback`                           | Verify Google identity and create a browser session.                                           |
| `POST`           | `/api/auth/logout`                                    | Revoke the active browser session.                                                             |
| `GET`            | `/api/auth/me`                                        | Return the signed-in user and active organization.                                             |
| `POST`           | `/api/auth/active-organization`                       | Switch the browser session to another organization membership.                                 |
| `GET`            | `/api/organizations`                                  | List the signed-in user's organization memberships.                                            |
| `PUT`            | `/api/organizations/{id}`                             | Rename the active organization as an owner or admin.                                           |
| `GET`            | `/api/health`                                         | PostgreSQL destination connectivity.                                                           |
| `GET`            | `/api/destinations`                                   | List registered load destinations without secrets.                                             |
| `GET`            | `/api/health/data`                                    | Per-source loader diagnostics.                                                                 |
| `POST`           | `/api/health/data/{id}/refresh`                       | Perform a durable refresh.                                                                     |
| `GET`            | `/api/google-oauth/status`                            | Google app/account connection state.                                                           |
| `POST`           | `/api/google-oauth/start`                             | Start the Google OAuth authorization flow.                                                     |
| `GET`            | `/api/google-oauth/callback`                          | Exchange the Google authorization code.                                                        |
| `DELETE`         | `/api/google-oauth`                                   | Disconnect Google without deleting snapshots.                                                  |
| `POST`           | `/api/google-picker/session`                          | Issue short-lived Picker configuration and access.                                             |
| `POST`           | `/api/google-picker/worksheets`                       | Inspect a Picker-selected file and list Google Sheet tabs or Excel worksheets.                 |
| `GET`            | `/.well-known/oauth-protected-resource`               | Publish MCP protected-resource metadata.                                                       |
| `GET`            | `/.well-known/oauth-authorization-server`             | Publish OAuth authorization-server metadata.                                                   |
| `GET`            | `/.well-known/openid-configuration`                   | Publish compatible OAuth discovery metadata.                                                   |
| `POST`           | `/oauth/register`                                     | Dynamically register an MCP OAuth client.                                                      |
| `GET/POST`       | `/oauth/authorize`                                    | Render or submit user-bound MCP authorization.                                                 |
| `POST`           | `/oauth/token`                                        | Exchange authorization codes or refresh tokens.                                                |
| `GET/POST`       | `/api/artifacts`                                           | List or create artifacts.                                                                      |
| `GET/PUT/DELETE` | `/api/artifacts/{id}`                                      | Read, update, or remove one artifact.                                                          |
| `GET`            | `/api/artifacts/{id}/relationships`                        | List authored relationships with structural and Cube compilation status.                       |
| `POST`           | `/api/artifacts/{id}/relationships/validate`               | Probe relationship execution and validate declared cardinality against synchronized snapshots. |
| `POST`           | `/api/artifacts/{id}/relationships/draft`                  | Prepare a complete overlay draft to establish, edit, or remove one join without persisting it. |
| `GET`            | `/api/artifacts/{id}/models`                               | List artifact-visible model files and concrete table dimensions.                               |
| `GET`            | `/api/artifacts/{id}/impact/model/{path}`                  | Preview dependencies across every affected artifact before deleting one artifact model file.   |
| `GET`            | `/api/artifacts/{id}/impact/source/{pipe}`                 | Preview dependencies affected by removing one source from an artifact.                         |
| `GET`            | `/api/artifacts/{id}/models/{path}`                        | Read exact artifact-scoped Cube YAML.                                                          |
| `POST`           | `/api/artifacts/{id}/overlays/validate`                    | Dry-run artifact-scoped Cube YAML and optional test queries.                                   |
| `POST`           | `/api/artifacts/{id}/overlays`                             | Create or replace an authored overlay, with optional stale replacement protection.             |
| `DELETE`         | `/api/artifacts/{id}/overlays/{path}`                      | Remove one artifact-scoped authored overlay.                                                   |
| `POST`           | `/api/artifacts/{id}/query`                                | Execute one bounded, artifact-scoped Cube REST query.                                          |
| `GET/PUT`        | `/api/artifacts/{id}/graph`                                | Read or revision-safely replace the artifact's canonical graph and layout.                     |
| `POST`           | `/api/artifacts/{id}/graph/validate`                       | Validate the saved or submitted artifact graph without running it.                             |
| `POST`           | `/api/artifacts/{id}/graph/execute`                        | Execute all named results or one target step and its dependencies.                             |
| `POST`           | `/api/artifacts/{id}/graph/parameters/{parameter}/options` | Return bounded distinct Cube values for an artifact graph parameter.                           |
| `POST`           | `/api/artifacts/{id}/pipes/{pipe}/tables/{table}/sample`   | Inspect bounded snapshot rows using the MCP sample projection.                                 |
| `POST`           | `/api/artifacts/{id}/pipes/{pipe}/tables/{table}/profile`  | Inspect a bounded snapshot column profile using the MCP profile projection.                    |
| `GET`            | `/api/google-drive/config`                            | Google Drive tabular-source form configuration.                                                |
| `GET`            | `/api/google-drive/documentation`                     | Google Drive source setup guide.                                                               |
| `GET/POST`       | `/api/connections`                                    | List or create Drive tabular-file sources.                                                     |
| `GET/PUT/DELETE` | `/api/connections/{id}`                               | Read, update, or remove one source.                                                            |
| `POST`           | `/api/connections/{id}/retry`                         | Retry a failed or pending source sync.                                                         |
| `POST`           | `/api/connections/{id}/sync`                          | Run one complete dlt load.                                                                     |
| `GET`            | `/api/connections/{id}/sync-runs`                     | Read bounded sync history.                                                                     |
| `GET/PUT`        | `/api/connections/{id}/sync-config`                   | Read or validate/write source YAML.                                                            |
| `GET`            | `/api/connections/{id}/schema-impact`                 | Conservatively preview dependencies that a source schema change may affect.                    |
| `GET`            | `/api/connections/{id}/deletion-impact`               | Exactly preview artifact dependencies affected by deleting a source.                           |
| `POST`           | `/api/connections/{id}/metadata`                      | Refresh PostgreSQL schema metadata.                                                            |
| `POST`           | `/api/query/`                                         | Execute Cube REST query JSON.                                                                  |
| `GET`            | `/api/semantics/model`                                | Inspect the active model summary.                                                              |
| `POST`           | `/api/semantics/model/sync`                           | Regenerate connection models from successful manifests.                                        |
| `GET`            | `/api/semantics/model/files`                          | List allowed Cube YAML files.                                                                  |
| `GET/PUT/DELETE` | `/api/semantics/model/files/{path}`                   | Manage allowed Cube YAML files.                                                                |
| `GET`            | `/api/semantics/meta`                                 | Proxy Cube `/v1/meta`.                                                                         |
| `GET`            | `/api/requests`                                       | Privacy-safe MCP request metrics.                                                              |
| `GET`            | `/api/events`                                         | Organization-scoped server-sent workspace change notifications.                                |
| `GET`            | `/api/settings`                                       | Deployment and MCP OAuth settings.                                                             |
| `GET`            | `/api/settings/product`                               | Return the build-time product name without caching.                                            |

## Configuration

Defaults below distinguish a directly started application from this repository's
Docker Compose deployment. “Same” means Compose does not override the
application default. Blank `APP_DB_*` Compose values deliberately trigger the
documented inheritance.

| Variable                                 | Application default           | Compose default             | Purpose                                                                                                                              |
| ---------------------------------------- | ----------------------------- | --------------------------- | ------------------------------------------------------------------------------------------------------------------------------------ |
| `PRODUCT_NAME`                           | `Settra`                      | `Settra`                    | User-facing product name.                                                                                                            |
| `AI_CLIENT_DESCRIPTION`                  | unset                         | same                        | Description shown when configuring an MCP client.                                                                                    |
| `DEPLOYMENT_MODE`                        | `self_hosted`                 | `self_hosted`               | Settings presentation mode. Set to `managed` to hide deployment-specific MCP URLs and configuration.                                 |
| `CONFIG_DIR`                             | `/config`                     | same                        | Configuration root.                                                                                                                  |
| `CONNECTORS_DIR`                         | derived                       | `/config/connectors`        | Directory containing `googledrive/` config.                                                                                          |
| `DATA_DIR`                               | `/data`                       | `/data`                     | Encrypted secrets, configs, manifests, and dlt state.                                                                                |
| `CONNECTION_CONFIG_DIR`                  | `/data/connections`           | `/data/connections`         | Per-source YAML and manifest directory.                                                                                              |
| `DLT_PIPELINES_DIR`                      | `/data/dlt`                   | `/data/dlt`                 | dlt pipeline state directory.                                                                                                        |
| `STATIC_DIR`                             | unset                         | `/opt/static`               | Built admin UI directory.                                                                                                            |
| `LOG_LEVEL`                              | `INFO`                        | `INFO`                      | Backend logging threshold.                                                                                                           |
| `CORS_ALLOWED_ORIGINS`                   | `*`                           | same                        | Comma-separated browser CORS origins.                                                                                                |
| `POSTGRES_HOST`                          | `postgres`                    | `postgres`                  | Durable destination hostname.                                                                                                        |
| `POSTGRES_PORT`                          | `5432`                        | `5432`                      | Durable destination port.                                                                                                            |
| `POSTGRES_DATABASE`                      | `settra`                      | `settra`                    | Durable destination database.                                                                                                        |
| `POSTGRES_USER`                          | `settra`                      | `settra`                    | Loader and Cube database user.                                                                                                       |
| `POSTGRES_PASSWORD`                      | `settra`                      | `settra-dev-password`       | Loader and Cube database password.                                                                                                   |
| `APP_DB_HOST`                            | inherits `POSTGRES_HOST`      | inherits                    | Optional product database hostname.                                                                                                  |
| `APP_DB_PORT`                            | inherits `POSTGRES_PORT`      | inherits                    | Optional product database port.                                                                                                      |
| `APP_DB_DATABASE`                        | inherits `POSTGRES_DATABASE`  | inherits                    | Optional product database name.                                                                                                      |
| `APP_DB_USER`                            | inherits `POSTGRES_USER`      | inherits                    | Optional product database user.                                                                                                      |
| `APP_DB_PASSWORD`                        | inherits `POSTGRES_PASSWORD`  | inherits                    | Optional product database password.                                                                                                  |
| `APP_DB_SCHEMA`                          | `settra_app`                  | `settra_app`                | Product-owned PostgreSQL schema managed by Alembic.                                                                                  |
| `GOOGLE_OAUTH_CLIENT_ID`                 | unset                         | unset                       | Google Web OAuth client ID.                                                                                                          |
| `GOOGLE_OAUTH_CLIENT_SECRET`             | unset                         | unset                       | Google Web OAuth client secret.                                                                                                      |
| `GOOGLE_LOGIN_ENABLED`                   | `false`                       | `false`                     | Opt in to Google account login; Drive consent remains separate.                                                                      |
| `GOOGLE_OAUTH_REDIRECT_URI`              | request-derived               | request-derived             | Exact Google callback URI override.                                                                                                  |
| `GOOGLE_LOGIN_REDIRECT_URI`              | request-derived               | request-derived             | Exact Google account-login callback URI override.                                                                                    |
| `GOOGLE_CLOUD_PROJECT`                   | unset                         | unset                       | Optional Google Cloud project ID for dlt credentials.                                                                                |
| `GOOGLE_PICKER_API_KEY`                  | unset                         | unset                       | Browser-restricted key for Google Picker API.                                                                                        |
| `GOOGLE_PICKER_APP_ID`                   | unset                         | unset                       | Numeric Google Cloud project number used by Picker.                                                                                  |
| `FRONTEND_URL`                           | unset                         | unset                       | Optional separate browser UI origin, such as the Vite dev server.                                                                    |
| `GOOGLE_OAUTH_CREDENTIALS_DIR`           | `/data/secrets/organizations` | same                        | Organization-scoped encrypted Google credentials.                                                                                    |
| `CUBE_CONF_DIR`                          | `/cube/conf`                  | same                        | Cube configuration root.                                                                                                             |
| `CUBE_MODEL_DIR`                         | `/cube/conf/model`            | `/cube/conf/model`          | Active Cube models.                                                                                                                  |
| `CUBE_API_URL`                           | `http://cube:4000/cubejs-api` | same                        | Cube REST base URL.                                                                                                                  |
| `CUBE_API_SECRET`                        | unset                         | `cube-dev-secret-change-me` | Cube JWT secret.                                                                                                                     |
| `CUBE_API_TIMEOUT_SECONDS`               | `10`                          | same                        | Per-request Cube HTTP timeout.                                                                                                       |
| `CUBE_QUERY_CONTINUE_WAIT_ATTEMPTS`      | `8`                           | same                        | Maximum Cube continue-wait retries.                                                                                                  |
| `CUBE_QUERY_CONTINUE_WAIT_SLEEP_SECONDS` | `1`                           | same                        | Seconds between Cube continue-wait retries.                                                                                          |
| `PUBLIC_URL`                             | request-derived               | `http://localhost:8000`     | MCP OAuth issuer and Google callback origin.                                                                                         |
| `REGISTRATION_ENABLED`                   | `true`                        | `true`                      | Allow new account and personal-workspace registration.                                                                               |
| `APP_SESSION_TTL_SECONDS`                | `2592000`                     | `2592000`                   | Browser-session lifetime.                                                                                                            |
| `APP_SESSION_COOKIE_SECURE`              | inferred from `PUBLIC_URL`    | inferred                    | Require HTTPS for browser session and CSRF cookies.                                                                                  |
| `MCP_OAUTH_ENABLED`                      | `true`                        | `true`                      | Require user-bound OAuth for `/mcp`; disabling it disables MCP access rather than exposing tenants.                                  |
| `SETTRA_OAUTH_SCOPES`                    | `settra:read settra:write`    | same                        | Space- or comma-separated supported MCP OAuth scopes.                                                                                |
| `SETTRA_OAUTH_REDIRECT_HOSTS`            | empty list                    | same                        | Optional complete allowlist of dynamic-client redirect hosts. Empty accepts any valid HTTPS callback plus native loopback callbacks. |
| `SETTRA_OAUTH_RESOURCE`                  | `<public origin>/mcp`         | same                        | Optional OAuth protected-resource identifier.                                                                                        |
| `MCP_OAUTH_TOKEN_TTL_SECONDS`            | `3600`                        | `3600`                      | Access-token lifetime.                                                                                                               |
| `MCP_OAUTH_REFRESH_TOKEN_TTL_SECONDS`    | `2592000`                     | `2592000`                   | Refresh-token lifetime.                                                                                                              |
| `SETTRA_OAUTH_CODE_TTL_SECONDS`          | `300`                         | same                        | Authorization-code lifetime.                                                                                                         |
| `MCP_ALLOWED_HOSTS`                      | empty list                    | local loopback hosts        | Complete comma-separated MCP transport Host allowlist.                                                                               |
| `MCP_ALLOWED_ORIGINS`                    | empty list                    | local HTTP loopback origins | Complete comma-separated MCP transport Origin allowlist.                                                                             |
| `MCP_REQUEST_HISTORY_LIMIT`              | `10000`                       | same                        | Maximum retained privacy-safe MCP metric rows, with a minimum of 100.                                                                |
| `SEMANTIC_OVERLAY_COMPILE_ATTEMPTS`      | `10`                          | same                        | Maximum overlay compile-status checks.                                                                                               |
| `SEMANTIC_OVERLAY_COMPILE_SLEEP_SECONDS` | `0.5`                         | same                        | Seconds between overlay compile-status checks.                                                                                       |
| `SECRET_KEY`                             | `dev-secret-change-me`        | same                        | OAuth signing and Google secret encryption material.                                                                                 |

The Compose loopback allowlists are the exact values shown in `.env.example`:
`127.0.0.1,127.0.0.1:*,localhost,localhost:*,[::1],[::1]:*` for hosts and
`http://127.0.0.1,http://127.0.0.1:*,http://localhost,http://localhost:*,http://[::1],http://[::1]:*`
for origins. Setting either variable replaces its corresponding entire list;
the application does not append implicit defaults.

Compose image variables are `IMAGE`, `CUBE_IMAGE`, `POSTGRES_IMAGE`,
`LOCAL_PLATFORM`, `DEPLOY_PLATFORM`, and `PUBLISH_PLATFORMS`.

## Model files

The source form configuration lives at:

```text
connectors/googledrive/connection.yaml
```

No semantic YAML is packaged with Settra. After a successful load, Settra writes
`/data/connections/<storage-key>.manifest.yaml` and generates one Cube per synchronized
table in `/cube/conf/model/generated/connections/<storage-key>.yaml`. Generated metadata
records connection id/name/slug, Google source key, original tab, storage type,
and manifest time. Workspace overlays are created dynamically under
`/cube/conf/model/overlays/generated/organizations/<organization-id>` and persist
in the shared Cube runtime volume.

The UI presents collections as data artifacts and manages semantics inside each
artifact. Artifact-owned overlays live under
`overlays/generated/organizations/<organization-id>/collections/<collection-id>`.
Deleting an artifact with authored overlays is rejected so its models cannot be
stranded. Database tables and internal service names retain `collection`
terminology for the same product object. Public routes, MCP tools, resource URIs,
request fields, and response fields use `artifact`. Generic application-framework
identifiers and the `backend/app` Python package retain their conventional names.

The MCP router is a package at `backend/app/routers/mcp/`. Keep one public tool
per module, shared helpers in `common.py`, resources in `resources.py`, and
assembly in `server.py`. Compact response policies live in
`backend/app/cube/projection.py`.

## Product database

Alembic migrations live in `backend/alembic/versions`. Runtime product queries
use an asyncpg pool scoped to `APP_DB_SCHEMA`; dlt continues to own each pipe's
registered destination namespace. Startup upgrades the product schema before
loading Cube models.

- `destinations` stores stable destination identity, type, non-secret
  configuration mode, and built-in/default flags. The seeded
  `built_in_postgres` record resolves credentials from `POSTGRES_*` at runtime.
- `users`, `google_login_identities`, `organizations`,
  `organization_memberships`, and `user_sessions` establish the tenant boundary.
  Each signup creates one personal organization; Google-only users have no local
  password, and Google identities are keyed by the stable OpenID Connect `sub`.
  sessions retain an active organization so shared organizations can be added
  without changing object ownership. Organization display names may repeat;
  stable slugs and numeric IDs provide identity. New personal organizations use
  readable adjective-adjective-noun slugs with a secure random suffix; the
  database uniqueness constraint and collision retry remain authoritative.
- `connections` stores source names, slugs, the fixed `googledrive` source
  marker, organization ownership, a globally unique storage key, destination
  foreign key and fixed target schema, status, and latest sync status fields. A
  connection is the durable source-to-destination pipe.
- `sync_runs` stores trigger, timing, status, table/row counts, dlt load IDs, and
  errors, never sheet values or credentials.
- `collections` stores organization-local artifact names, slugs, descriptions, and agent
  instructions. `collection_pipes` stores only reusable pipe memberships;
  destination tables and cubes are always derived from each pipe.
- `collection_graphs` stores one canonical executable YAML graph per artifact plus
  separate JSON layout metadata and a monotonically increasing revision. A
  missing row is projected as a new empty graph.
  Artifact graph definitions expose named `outputs` that map public result names to
  step IDs. Full execution evaluates the dependency graph once, while an explicit
  target step supports isolated testing. Runs are bounded and are not persisted.
  Cube models, aggregate-query connections, and parameter options are restricted
  to the artifact's pipes. Artifact graph parameters declare a qualified Cube dimension and bind only to
  filters on that exact member. Their input type and supported operators come from
  compiled, organization-visible Cube metadata; execution values are supplied
  separately from YAML, type-checked, and converted to Cube filter values.
- `mcp_requests` stores request names, timing, status, sizes, and estimated token
  counts, never payload contents.
- MCP OAuth tables store registered clients plus user- and organization-bound
  short-lived codes and hashed rotating refresh tokens. Access tokens are signed
  and not stored.

Rows whose `plugin` is not `googledrive` are ignored by runtime APIs,
diagnostics, model generation, and MCP discovery.

## Development

```bash
cd frontend && npm install
cd ../backend && pip install -r requirements.txt
cd ..

make dev
```

`make dev` starts PostgreSQL, the backend, Cube, and the frontend development
server. Backend startup applies Alembic migrations and synchronizes the Cube
model automatically. The `make init` target uses `--no-deps`; use it only when
the PostgreSQL service is already running.

Other useful commands:

```bash
make run
make run-build
make test
make build
make down
docker compose logs -f app
docker compose logs -f cube
docker compose logs -f postgres
docker compose exec app python -m app.init
```

`make test` runs the complete backend unit suite in the Compose app image,
checks relationship SQL/aliases and authored model revisions with Cube's
in-memory compiler, checks frontend formatting, builds the frontend, and runs
`git diff --check`.
GitHub Actions runs the same checks for pushes and pull requests.
