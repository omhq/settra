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

export interface ConnectorField {
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
}

export interface Connector {
  key: string;
  name: string;
  plugin: string;
  logo?: string;
  description: string;
  docs?: string;
  test_table?: string;
  credential_groups?: { label: string; keys: string[] }[];
  fields: ConnectorField[];
}

export interface Connection {
  id: number;
  name: string;
  slug: string;
  plugin: string;
  status: "active" | "failed";
  created_at: string;
  credentials?: Record<string, string>;
  secret_fields?: string[];
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
  fdw_state?: string | null;
  fdw_error?: string | null;
  fdw_table_count?: number | null;
  fdw_column_count?: number | null;
  fdw_plugin?: string | null;
  fdw_plugin_instance?: string | null;
  fdw_config_file?: string | null;
  fdw_schema_mode?: string | null;
  fdw_schema_hash?: string | null;
  cache_cleared?: boolean;
}

export interface FdwHealthSummary {
  steampipe: "connected" | "disconnected";
  actions: {
    cache_refresh_supported: boolean;
    restart_supported: boolean;
  };
  connections: ConnectionRetryResult[];
}

export interface SteampipeHealth {
  steampipe: "connected" | "disconnected";
  actions: {
    restart_supported: boolean;
  };
}

export interface ConnectionCreate {
  name: string;
  plugin: string;
  credentials: Record<string, string>;
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

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(errorMessageFromDetail(err.detail, res.statusText));
  }
  return res.json();
}

export const api = {
  health: {
    steampipe: () => request<SteampipeHealth>("/health"),
    fdw: () => request<FdwHealthSummary>("/health/fdw"),
    refreshFdw: (id: number) =>
      request<ConnectionRetryResult & { ok: boolean }>(
        `/health/fdw/${id}/refresh`,
        {
          method: "POST",
        },
      ),
    restartSteampipe: () =>
      request<{ ok: boolean; restart_supported: boolean; output?: string }>(
        "/health/steampipe/restart",
        {
          method: "POST",
        },
      ),
  },
  connectors: {
    list: () => request<Connector[]>("/connectors"),
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
    update: (
      id: number,
      body: { name: string; credentials: Record<string, string> },
    ) =>
      request<Connection>(`/connections/${id}`, {
        method: "PUT",
        body: JSON.stringify(body),
      }),
    retry: (id: number) =>
      request<ConnectionRetryResult>(`/connections/${id}/retry`, {
        method: "POST",
      }),
    delete: (id: number) =>
      request<{ ok: boolean }>(`/connections/${id}`, { method: "DELETE" }),
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
