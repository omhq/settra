const BASE = "/api";

function errorMessageFromDetail(detail: unknown, fallback: string): string {
  if (typeof detail === "string") return detail;

  if (Array.isArray(detail)) {
    return detail
      .map((item) => errorMessageFromDetail(item, ""))
      .filter(Boolean)
      .join(" ");
  }

  if (detail && typeof detail === "object") {
    const record = detail as Record<string, unknown>;
    const message =
      typeof record.message === "string" ? record.message : fallback;
    const operation =
      typeof record.operation === "string"
        ? `Operation: ${record.operation}.`
        : "";
    const error =
      typeof record.error === "string" ? `Exception: ${record.error}` : "";

    return [message, operation, error].filter(Boolean).join(" ");
  }

  return fallback;
}

export interface SheetField {
  key: string;
  label: string;
  type: "text" | "secret" | "number" | "textarea" | "boolean";
  placeholder?: string;
  help?: string;
  required?: boolean;
  default?: string | number;
  secret?: boolean;
  hcl_type?: "string" | "string_list";
  min?: number;
  max?: number;
  hidden?: boolean;
}

export interface GoogleDriveConfig {
  name: string;
  description: string;
  has_documentation?: boolean;
  fields: SheetField[];
}

export interface GoogleDriveDocumentation {
  name: string;
  content: string;
}

export interface Destination {
  id: number;
  name: string;
  slug: string;
  type: string;
  is_builtin: boolean;
  is_default: boolean;
  configuration_mode: string;
  configurable: boolean;
  schema?: string;
  location?: {
    host: string;
    port: number;
    database: string;
  };
}

export interface Connection {
  id: number;
  name: string;
  slug: string;
  plugin: string;
  status: "active" | "failed" | "pending" | "syncing";
  created_at: string;
  last_sync_started_at?: string | null;
  last_synced_at?: string | null;
  last_sync_error?: string | null;
  credentials?: Record<string, ConnectionCredentialValue>;
  row_keys?: Record<string, RowKeyDefinition>;
  secret_fields?: string[];
  destination_id: number;
  destination_schema: string;
  destination: Destination;
}

export interface ConnectionRetryResult {
  id: number;
  status: Connection["status"];
  name?: string;
  slug?: string;
  plugin?: string;
  detail?: string | null;
  error?: string | null;
  warnings?: string[];
  sync_state?: string | null;
  postgres_state?: string | null;
  postgres_error?: string | null;
  table_count?: number | null;
  column_count?: number | null;
  oauth_connected?: boolean;
  schedule?: SyncSchedule;
}

export interface SyncSchedule {
  enabled?: boolean;
  cron?: string;
  timezone?: string;
}

export interface SyncConfig {
  load?: {
    schedule?: SyncSchedule;
  };
}

export interface DataHealthSummary {
  postgres: "connected" | "disconnected";
  actions: {
    sync_supported: boolean;
  };
  connections: ConnectionRetryResult[];
}

export interface PostgresHealth {
  postgres: "connected" | "disconnected";
  version?: string;
  error?: string;
  destination: {
    host: string;
    port: number;
    database: string;
  };
}

export interface GoogleOAuthStatus {
  configured: boolean;
  connected: boolean;
  scope_ready: boolean;
  requires_reconnect: boolean;
  picker_configured: boolean;
  picker_ready: boolean;
  email?: string | null;
  name?: string | null;
  scopes: string[];
  connected_at?: number | null;
  redirect_uri: string;
  return_uri: string;
}

export interface GooglePickerSession {
  access_token: string;
  expires_at?: string | null;
  api_key: string;
  app_id: string;
}

export interface GoogleDriveWorksheetDiscovery {
  file_name: string;
  mime_type: string;
  format: "google_sheets" | "excel" | "csv" | "parquet";
  worksheets: string[];
  worksheet_schemas?: GoogleDriveWorksheetSchema[];
  worksheet_schema_truncated?: boolean;
}

export interface GoogleDriveWorksheetSchema {
  name: string;
  header_row?: number;
  columns: string[];
  columns_truncated?: boolean;
  error?: string;
}

export interface ConnectionMetadataColumn {
  name: string;
  type: string;
  nullable: boolean;
  description?: string;
}

export interface ConnectionMetadataTable {
  description?: string;
  columns: ConnectionMetadataColumn[];
  ddl?: string;
}

export interface ConnectionMetadata {
  generated_at: string;
  slug: string;
  tables: Record<string, ConnectionMetadataTable>;
}

export interface SyncResult {
  ok: boolean;
  run_id: number;
  connection_id: number;
  destination_id: number;
  schema: string;
  table_count: number;
  row_count: number;
  load_ids: string[];
  completed_at: string;
}

export interface SyncRun {
  id: number;
  connection_id: number;
  trigger: string;
  status: string;
  table_count?: number | null;
  row_count?: number | null;
  load_ids?: string | null;
  error?: string | null;
  started_at: string;
  finished_at?: string | null;
}

export type ConnectionCredentialValue = string | string[];

export interface RowKeyDefinition {
  columns: string[];
  format?: string;
}

export interface ConnectionCreate {
  name: string;
  credentials: Record<string, ConnectionCredentialValue>;
  destination_id?: number;
  row_keys?: Record<string, RowKeyDefinition>;
}

export interface CollectionPipe {
  id: number;
  name: string;
  slug: string;
  status: Connection["status"];
  last_synced_at?: string | null;
  destination_schema: string;
  destination_id?: number;
  destination_name?: string;
  destination_slug?: string;
  table_count: number;
  cube_count: number;
}

export interface CollectionTable {
  pipe_id: number;
  pipe_name: string;
  pipe_slug: string;
  schema: string;
  table: string;
  column_count: number;
  cube_name: string;
}

export interface DataCollection {
  id: number;
  name: string;
  slug: string;
  description: string;
  agent_instructions: string;
  created_at: string;
  updated_at: string;
  pipe_ids: number[];
  pipes: CollectionPipe[];
  pipe_count: number;
  table_count: number;
  cube_count: number;
  tables?: CollectionTable[];
  cube_names?: string[];
  mcp_path: string;
}

export interface DataCollectionInput {
  name: string;
  description: string;
  agent_instructions: string;
  pipe_ids: number[];
}

export interface SecretValues {
  secrets: Record<string, string>;
}

export interface CubeModelFileSummary {
  path: string;
  source_type:
    | "bundled_connector"
    | "generated_connection"
    | "overlay"
    | "generated_overlay"
    | string;
  size: number;
  updated_at: string;
  cube_count: number;
  view_count: number;
  cube_names: string[];
  view_names: string[];
}

export interface CubeModelFile extends CubeModelFileSummary {
  content: string;
}

export interface CubeMetaMember {
  name: string;
  title?: string;
  shortTitle?: string;
  description?: string;
  type?: string;
  aggType?: string;
  public?: boolean;
  isVisible?: boolean;
  meta?: Record<string, unknown>;
}

export interface CubeMetaCube {
  name: string;
  title?: string;
  type: "cube" | "view" | string;
  description?: string;
  measures: CubeMetaMember[];
  dimensions: CubeMetaMember[];
  segments: CubeMetaMember[];
  joins?: { name: string; relationship: string }[];
  meta?: Record<string, unknown>;
}

export interface CubeMetaResponse {
  cubes: CubeMetaCube[];
  compilerId?: string;
}

export interface CubeSourceMemberDefinition {
  sql?: string | null;
  filters?: { sql: string }[];
}

export interface CubeSourceDefinition {
  path: string;
  source_type:
    | "bundled_connector"
    | "generated_connection"
    | "overlay"
    | "generated_overlay"
    | string;
  sql?: string | null;
  sql_table?: string | null;
  measures: Record<string, CubeSourceMemberDefinition>;
  dimensions: Record<string, CubeSourceMemberDefinition>;
  segments: Record<string, CubeSourceMemberDefinition>;
}

export interface CubeModelSummary {
  model_dir: string;
  files: CubeModelFileSummary[];
  source_definitions?: {
    cubes: Record<string, CubeSourceDefinition>;
  };
  cube: {
    connected: boolean;
    cube_count: number;
    error: string | null;
    meta: CubeMetaResponse | null;
  };
}

export interface CubeModelSyncResult {
  ok: boolean;
  model_dir: string;
  files: CubeModelFileSummary[];
}

export interface MCPRequestRecord {
  id: number;
  request_id: string | null;
  client_id: string | null;
  kind: "tool" | "resource" | string;
  name: string;
  status: "success" | "error" | string;
  duration_ms: number;
  request_bytes: number;
  response_bytes: number;
  estimated_input_tokens: number;
  estimated_output_tokens: number;
  estimated_tokens: number;
  error_type: string | null;
  created_at: string;
}

export interface MCPRequestSummary {
  total_requests: number;
  successful_requests: number;
  failed_requests: number;
  estimated_input_tokens: number;
  estimated_output_tokens: number;
  estimated_tokens: number;
  average_duration_ms: number;
}

export interface MCPRequestPage {
  requests: MCPRequestRecord[];
  summary: MCPRequestSummary;
  next_cursor: number | null;
  tracking: {
    payloads_stored: boolean;
    token_estimate: string;
    history_limit: number;
  };
}

export type DeploymentMode = "self_hosted" | "managed";

export interface DeploymentSettings {
  product_name: string;
  deployment_mode: DeploymentMode;
  public_url: string;
  mcp_url: string;
  ai_client_description: string;
  oauth: {
    enabled: boolean;
    authorization_identity: string;
  };
  organization: {
    id: number;
    name: string;
    slug: string;
    role: AccountOrganization["role"];
  };
}

export interface ProductSettings {
  product_name: string;
  deployment_mode: DeploymentMode;
}

export interface AccountUser {
  id: number;
  email: string;
  display_name: string;
}

export interface AccountOrganization {
  id: number;
  name: string;
  slug: string;
  kind: "personal" | "team" | string;
  role: "owner" | "admin" | "member" | "viewer" | string;
  active?: boolean;
}

export interface AccountSession {
  user: AccountUser;
  organization: AccountOrganization;
}

export interface AuthConfig {
  registration_enabled: boolean;
  google_login_enabled: boolean;
}

function cookieValue(name: string): string {
  const prefix = `${encodeURIComponent(name)}=`;
  for (const item of document.cookie.split(";")) {
    const value = item.trim();
    if (value.startsWith(prefix))
      return decodeURIComponent(value.slice(prefix.length));
  }
  return "";
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const method = (init?.method ?? "GET").toUpperCase();
  const headers = new Headers(init?.headers);
  headers.set("Content-Type", "application/json");
  if (!["GET", "HEAD", "OPTIONS", "TRACE"].includes(method)) {
    const csrfToken = cookieValue("settra_csrf");
    if (csrfToken) headers.set("X-CSRF-Token", csrfToken);
  }
  const res = await fetch(`${BASE}${path}`, {
    ...init,
    credentials: "include",
    headers,
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    const error = new Error(errorMessageFromDetail(err.detail, res.statusText));
    if (res.status === 401 && !path.startsWith("/auth/")) {
      window.dispatchEvent(new Event("settra:unauthorized"));
    }
    throw error;
  }
  return res.json();
}

export const api = {
  auth: {
    config: () => request<AuthConfig>("/auth/config"),
    me: () => request<AccountSession>("/auth/me"),
    login: (body: { email: string; password: string }) =>
      request<AccountSession>("/auth/login", {
        method: "POST",
        body: JSON.stringify(body),
      }),
    register: (body: {
      email: string;
      display_name: string;
      password: string;
    }) =>
      request<AccountSession>("/auth/register", {
        method: "POST",
        body: JSON.stringify(body),
      }),
    logout: () => request<{ ok: boolean }>("/auth/logout", { method: "POST" }),
    switchOrganization: (organizationId: number) =>
      request<AccountSession>("/auth/active-organization", {
        method: "POST",
        body: JSON.stringify({ organization_id: organizationId }),
      }),
  },
  organizations: {
    list: () =>
      request<{ organizations: AccountOrganization[] }>("/organizations"),
    update: (id: number, name: string) =>
      request<AccountOrganization>(`/organizations/${id}`, {
        method: "PUT",
        body: JSON.stringify({ name }),
      }),
  },
  health: {
    postgres: () => request<PostgresHealth>("/health"),
    data: () => request<DataHealthSummary>("/health/data"),
    refreshData: (id: number) =>
      request<ConnectionRetryResult & { ok: boolean }>(
        `/health/data/${id}/refresh`,
        {
          method: "POST",
        },
      ),
  },
  googleDrive: {
    config: () => request<GoogleDriveConfig>("/google-drive/config"),
    documentation: () =>
      request<GoogleDriveDocumentation>("/google-drive/documentation"),
  },
  destinations: {
    list: () => request<Destination[]>("/destinations"),
  },
  googlePicker: {
    session: () =>
      request<GooglePickerSession>("/google-picker/session", {
        method: "POST",
      }),
    worksheets: (fileId: string) =>
      request<GoogleDriveWorksheetDiscovery>("/google-picker/worksheets", {
        method: "POST",
        body: JSON.stringify({ file_id: fileId }),
      }),
  },
  googleOAuth: {
    status: () => request<GoogleOAuthStatus>("/google-oauth/status"),
    start: () =>
      request<{ authorization_url: string }>("/google-oauth/start", {
        method: "POST",
      }),
    disconnect: () =>
      request<{ ok: boolean; disconnected: boolean; note: string }>(
        "/google-oauth",
        { method: "DELETE" },
      ),
  },
  connections: {
    list: () => request<Connection[]>("/connections"),
    get: (id: number) => request<Connection>(`/connections/${id}`),
    secrets: (id: number) =>
      request<SecretValues>(`/connections/${id}/secrets`),
    create: (body: ConnectionCreate) =>
      request<Connection>("/connections", {
        method: "POST",
        body: JSON.stringify(body),
      }),
    update: (id: number, body: ConnectionCreate) =>
      request<Connection>(`/connections/${id}`, {
        method: "PUT",
        body: JSON.stringify(body),
      }),
    retry: (id: number) =>
      request<ConnectionRetryResult>(`/connections/${id}/retry`, {
        method: "POST",
      }),
    sync: (id: number) =>
      request<SyncResult>(`/connections/${id}/sync`, { method: "POST" }),
    metadata: (id: number) =>
      request<ConnectionMetadata>(`/connections/${id}/metadata`, {
        method: "POST",
      }),
    syncRuns: (id: number) =>
      request<{ runs: SyncRun[] }>(`/connections/${id}/sync-runs`),
    syncConfig: (id: number) =>
      request<{ content: string }>(`/connections/${id}/sync-config`),
    updateSyncConfig: (id: number, content: string) =>
      request<{
        ok: boolean;
        content: string;
        config: SyncConfig;
        row_keys: Record<string, RowKeyDefinition>;
      }>(`/connections/${id}/sync-config`, {
        method: "PUT",
        body: JSON.stringify({ content }),
      }),
    delete: (id: number) =>
      request<{ ok: boolean }>(`/connections/${id}`, { method: "DELETE" }),
  },
  collections: {
    list: () => request<DataCollection[]>("/collections"),
    get: (id: number) => request<DataCollection>(`/collections/${id}`),
    create: (body: DataCollectionInput) =>
      request<DataCollection>("/collections", {
        method: "POST",
        body: JSON.stringify(body),
      }),
    update: (id: number, body: DataCollectionInput) =>
      request<DataCollection>(`/collections/${id}`, {
        method: "PUT",
        body: JSON.stringify(body),
      }),
    delete: (id: number) =>
      request<{ ok: boolean; data_retained: boolean }>(`/collections/${id}`, {
        method: "DELETE",
      }),
  },
  requests: {
    list: (cursor: number | null = null, limit = 50) => {
      const params = new URLSearchParams({ limit: String(limit) });
      if (cursor !== null) params.set("cursor", String(cursor));
      return request<MCPRequestPage>(`/requests?${params.toString()}`);
    },
  },
  settings: {
    get: () => request<DeploymentSettings>("/settings"),
    product: () => request<ProductSettings>("/settings/product"),
  },
  semantics: {
    model: () => request<CubeModelSummary>("/semantics/model"),
    syncModel: () =>
      request<CubeModelSyncResult>("/semantics/model/sync", {
        method: "POST",
      }),
    files: () =>
      request<{ files: CubeModelFileSummary[] }>("/semantics/model/files"),
    getFile: (path: string) =>
      request<CubeModelFile>(
        `/semantics/model/files/${encodeURIComponent(path).replace(/%2F/g, "/")}`,
      ),
    saveFile: (path: string, content: string) =>
      request<{ ok: boolean; file: CubeModelFileSummary }>(
        `/semantics/model/files/${encodeURIComponent(path).replace(/%2F/g, "/")}`,
        {
          method: "PUT",
          body: JSON.stringify({ content }),
        },
      ),
    deleteFile: (path: string) =>
      request<{ ok: boolean; deleted: CubeModelFileSummary }>(
        `/semantics/model/files/${encodeURIComponent(path).replace(/%2F/g, "/")}`,
        { method: "DELETE" },
      ),
    meta: () => request<CubeMetaResponse>("/semantics/meta"),
  },
};
