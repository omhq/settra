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
  detail?: string | null;
  error?: string | null;
  warnings?: string[];
  fdw_state?: string | null;
  fdw_error?: string | null;
  fdw_table_count?: number | null;
  fdw_plugin?: string | null;
  fdw_plugin_instance?: string | null;
  fdw_config_file?: string | null;
}

export interface ConnectionCreate {
  name: string;
  plugin: string;
  credentials: Record<string, string>;
}

export interface ChatResults {
  columns: string[];
  rows: Record<string, unknown>[];
  row_count: number;
  truncated?: boolean;
}

export interface ChatQueryStep extends ChatResults {
  attempt: number;
  max_attempts: number;
  name: string;
  purpose?: string;
  query_plan?: string;
  sql: string;
  used_tables?: string[];
  used_relationships?: string[];
  error?: string;
}

export interface ChatSemanticSearch {
  attempt: number;
  max_attempts: number;
  query: string;
  types: string[];
  connection_ids: number[];
  result_count: number;
  results: Record<string, unknown>[];
}

export interface ChatThread {
  id: number;
  title: string;
  connection_id: number;
  connection_ids: number[];
  connections: ChatThreadConnection[];
  model_config_id: number | null;
  status: "active" | "inactive";
  inactive_reason?: string | null;
  created_at: string;
  updated_at: string;
  connection_name?: string | null;
  connection_plugin?: string | null;
  model_name?: string | null;
  model?: string | null;
  last_message?: string | null;
}

export interface ChatThreadConnection {
  id: number;
  name?: string | null;
  plugin?: string | null;
  status?: Connection["status"] | "missing" | null;
}

export interface ChatMessageRecord {
  id: number;
  role: "user" | "assistant";
  content: string;
  request_id?: string | null;
  payload?: {
    answer?: string;
    sql?: string;
    results?: ChatResults;
    query_workspace?: ChatQueryStep[];
    semantic_workspace?: ChatSemanticSearch[];
    diagnostics?: Record<string, unknown>;
    query_attempts?: number;
    max_query_attempts?: number;
    error?: string;
    [key: string]: unknown;
  } | null;
  diagnostics?: Record<string, unknown> | null;
  created_at: string;
}

export interface ChatThreadDetail {
  thread: ChatThread & {
    connection_status?: Connection["status"] | null;
    model_status?: ModelConfig["status"] | null;
  };
  messages: ChatMessageRecord[];
  runs?: ChatRun[];
}

export interface ChatRun {
  id: number;
  request_id: string;
  thread_id: number;
  status: "pending" | "running" | "completed" | "failed";
  message?: string | null;
  created_at: string;
  updated_at: string;
}

export interface ModelProvider {
  key: string;
  name: string;
  description?: string;
  model_prefix?: string;
  fields: ConnectorField[];
}

export interface ModelConfig {
  id: number;
  name: string;
  provider: string;
  model: string;
  config: Record<string, unknown>;
  secret_fields: string[];
  status: "active" | "deleted";
  created_at: string;
  updated_at: string;
}

export interface MessagingProvider {
  key: string;
  name: string;
  description: string;
  delivery_modes: string[];
  fields: ConnectorField[];
}

export interface MessagingConfig {
  id: number;
  name: string;
  provider: string;
  config: Record<string, unknown>;
  secret_fields: string[];
  model_config_id: number;
  connection_ids: number[];
  status: "active" | "deleted";
  created_at: string;
  updated_at: string;
}

export interface MessagingConfigCreate {
  name: string;
  provider: string;
  config: Record<string, unknown>;
  model_config_id: number;
  connection_ids: number[];
}

export interface MessagingConfigUpdate {
  name: string;
  config: Record<string, unknown>;
  model_config_id: number;
  connection_ids: number[];
}

export interface RuntimeConfig {
  public_api_url: string;
}

export interface SecretValues {
  secrets: Record<string, string>;
}

export type SemanticStatus =
  | "draft"
  | "suggested"
  | "confirmed"
  | "published"
  | "ignored"
  | "disabled"
  | "hidden";

export interface SemanticColumn {
  id: number;
  semantic_table_id: number;
  column_name: string;
  label?: string | null;
  description?: string | null;
  data_type?: string | null;
  semantic_type?: string | null;
  expression?: string | null;
  unit?: string | null;
  is_dimension?: number | boolean;
  is_measure?: number | boolean;
  is_time?: number | boolean;
  is_id?: number | boolean;
  is_foreign_key?: number | boolean;
  hidden?: number | boolean;
  status: SemanticStatus;
}

export interface SemanticTable {
  id: number;
  connection_id: number;
  source_name: string;
  schema_name: string;
  table_name: string;
  label?: string | null;
  description?: string | null;
  table_type?: "fact" | "dimension" | "bridge" | string | null;
  grain?: string | null;
  primary_time_column?: string | null;
  metadata?: Record<string, unknown> | null;
  hidden?: number | boolean;
  status: SemanticStatus;
  columns: SemanticColumn[];
}

export interface SemanticRelationship {
  id: number;
  from_connection_id: number;
  to_connection_id: number;
  from_table_id: number;
  from_column_id: number;
  to_table_id: number;
  to_column_id: number;
  relationship_type: string;
  match_type: string;
  confidence: number;
  status: SemanticStatus;
  source?: string;
  validation_status?: string | null;
  validation_note?: string | null;
  evidence?: string | null;
  rationale?: string | null;
  from_source?: string;
  from_schema?: string;
  from_table: string;
  from_column: string;
  to_source?: string;
  to_schema?: string;
  to_table: string;
  to_column: string;
}

export interface SemanticMetric {
  id: number;
  connection_id: number;
  semantic_table_id: number;
  name: string;
  label?: string | null;
  expression: string;
  filters_json?: string | null;
  time_column?: string | null;
  unit?: string | null;
  status: SemanticStatus;
}

export interface ConnectionSemantics {
  connection_id: number;
  tables: SemanticTable[];
  relationships: SemanticRelationship[];
  metrics: SemanticMetric[];
}

export type AiIntrospectionFlow = "relationships" | "metrics";

export interface AiIntrospectionResult {
  ok: boolean;
  connection_ids: number[];
  semantic_table_ids: number[];
  flows: AiIntrospectionFlow[];
  run_id?: number;
  diagnostics?: Record<string, unknown>;
  run?: AiIntrospectionRun;
  relationship_candidates_returned: number;
  relationship_candidates_suggested: number;
  relationship_candidates_existing: number;
  relationship_candidates_with_notes: number;
  relationship_candidates_skipped?: number;
  relationship_candidates_pruned?: number;
  metric_candidates_returned: number;
  metric_candidates_suggested: number;
  metric_candidates_existing: number;
  metric_candidates_skipped?: number;
  skipped: { from?: string; to?: string; reason: string }[];
  metric_skipped?: { metric?: string; reason: string }[];
  warnings: string[];
}

export interface AiIntrospectionRun {
  id: number;
  status: "running" | "completed" | "failed";
  model_config_id: number | null;
  model_snapshot?: Record<string, unknown> | null;
  connection_ids: number[];
  semantic_table_ids: number[];
  flows: AiIntrospectionFlow[];
  result?: Record<string, unknown> | null;
  request?: Record<string, unknown> | null;
  token_usage?: Record<string, unknown> | null;
  diagnostics?: Record<string, unknown> | null;
  error?: string | null;
  started_at: string;
  finished_at?: string | null;
  duration_ms?: number | null;
  created_at: string;
  updated_at: string;
}

export type ChatStreamEvent =
  | { type: "thread"; thread_id: number }
  | { type: "step"; name: string; label: string }
  | {
      type: "result";
      thread_id: number;
      answer: string;
      sql: string;
      results: ChatResults;
      query_workspace?: ChatQueryStep[];
      semantic_workspace?: ChatSemanticSearch[];
      query_attempts?: number;
      max_query_attempts?: number;
      response_type: "table" | "chart" | "insight";
      error?: string | null;
      diagnostics?: Record<string, unknown>;
    }
  | {
      type: "error";
      thread_id?: number;
      message: string;
      diagnostics?: Record<string, unknown>;
    };

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

async function readChatEventStream(
  res: Response,
  onEvent: (event: ChatStreamEvent) => void,
) {
  if (!res.body) throw new Error("Chat stream did not start");

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { value, done } = await reader.read();
    buffer += decoder.decode(value, { stream: !done });

    let boundary = buffer.indexOf("\n\n");
    while (boundary !== -1) {
      const chunk = buffer.slice(0, boundary).trim();
      buffer = buffer.slice(boundary + 2);

      const data = chunk
        .split("\n")
        .find((line) => line.startsWith("data: "))
        ?.slice(6);

      if (data === "[DONE]") return;
      if (data) onEvent(JSON.parse(data) as ChatStreamEvent);

      boundary = buffer.indexOf("\n\n");
    }

    if (done) break;
  }
}

export const api = {
  config: {
    get: () => request<RuntimeConfig>("/config"),
  },
  health: {
    steampipe: () =>
      request<{ steampipe: "connected" | "disconnected" }>("/health"),
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
  modelProviders: {
    list: () => request<ModelProvider[]>("/model-providers"),
  },
  models: {
    list: () => request<ModelConfig[]>("/models"),
    get: (id: number) => request<ModelConfig>(`/models/${id}`),
    secrets: (id: number) => request<SecretValues>(`/models/${id}/secrets`),
    create: (body: {
      name: string;
      provider: string;
      config: Record<string, unknown>;
    }) =>
      request<ModelConfig>("/models", {
        method: "POST",
        body: JSON.stringify(body),
      }),
    update: (
      id: number,
      body: { name: string; config: Record<string, unknown> },
    ) =>
      request<ModelConfig>(`/models/${id}`, {
        method: "PUT",
        body: JSON.stringify(body),
      }),
    test: (id: number) =>
      request<{ ok: boolean; response: string }>(`/models/${id}/test`, {
        method: "POST",
      }),
    delete: (id: number) =>
      request<{ ok: boolean }>(`/models/${id}`, {
        method: "DELETE",
      }),
  },
  messaging: {
    providers: {
      list: () => request<MessagingProvider[]>("/messaging/providers"),
    },
    configs: {
      list: () => request<MessagingConfig[]>("/messaging/configs"),
      get: (id: number) => request<MessagingConfig>(`/messaging/configs/${id}`),
      secrets: (id: number) =>
        request<SecretValues>(`/messaging/configs/${id}/secrets`),
      create: (body: MessagingConfigCreate) =>
        request<MessagingConfig>("/messaging/configs", {
          method: "POST",
          body: JSON.stringify(body),
        }),
      update: (id: number, body: MessagingConfigUpdate) =>
        request<MessagingConfig>(`/messaging/configs/${id}`, {
          method: "PUT",
          body: JSON.stringify(body),
        }),
      delete: (id: number) =>
        request<{ ok: boolean }>(`/messaging/configs/${id}`, {
          method: "DELETE",
        }),
    },
  },
  semantics: {
    introspect: (connectionId: number) =>
      request<{
        ok: boolean;
        connection_id: number;
        schema_name: string;
        tables_seen: number;
        relationships_suggested: number;
      }>(`/semantics/connections/${connectionId}/introspect`, {
        method: "POST",
      }),
    aiIntrospect: (body: {
      connection_ids: number[];
      model_config_id: number;
      approved: true;
      semantic_table_ids?: number[];
      flows: AiIntrospectionFlow[];
    }) =>
      request<AiIntrospectionResult>("/semantics/ai-introspect", {
        method: "POST",
        body: JSON.stringify(body),
      }),
    listAiRuns: (limit = 20) =>
      request<{ runs: AiIntrospectionRun[] }>(
        `/semantics/ai-introspect/runs?limit=${encodeURIComponent(limit)}`,
      ),
    getAiRun: (runId: number) =>
      request<AiIntrospectionRun>(`/semantics/ai-introspect/runs/${runId}`),
    getConnection: (connectionId: number) =>
      request<ConnectionSemantics>(`/semantics/connections/${connectionId}`),
    listRelationships: (connectionIds: number[]) => {
      const query = connectionIds.length
        ? `?connection_ids=${encodeURIComponent(connectionIds.join(","))}`
        : "";
      return request<{ relationships: SemanticRelationship[] }>(
        `/semantics/relationships${query}`,
      );
    },
    updateTable: (
      id: number,
      body: Partial<
        Pick<
          SemanticTable,
          | "label"
          | "description"
          | "table_type"
          | "grain"
          | "primary_time_column"
          | "metadata"
          | "hidden"
          | "status"
        >
      >,
    ) =>
      request<{ ok: boolean; updated: boolean }>(`/semantics/tables/${id}`, {
        method: "PATCH",
        body: JSON.stringify(body),
      }),
    deleteTable: (id: number) =>
      request<{ ok: boolean; table_id: number; deleted: boolean }>(
        `/semantics/tables/${id}`,
        {
          method: "DELETE",
        },
      ),
    updateColumn: (
      id: number,
      body: Partial<
        Pick<
          SemanticColumn,
          | "label"
          | "description"
          | "semantic_type"
          | "expression"
          | "unit"
          | "is_dimension"
          | "is_measure"
          | "is_time"
          | "is_id"
          | "is_foreign_key"
          | "hidden"
          | "status"
        >
      >,
    ) =>
      request<{ ok: boolean; updated: boolean }>(`/semantics/columns/${id}`, {
        method: "PATCH",
        body: JSON.stringify(body),
      }),
    deleteColumn: (id: number) =>
      request<{ ok: boolean; column_id: number; deleted: boolean }>(
        `/semantics/columns/${id}`,
        {
          method: "DELETE",
        },
      ),
    createMetric: (body: {
      connection_id: number;
      semantic_table_id: number;
      name: string;
      label?: string | null;
      expression: string;
      filters?: string[];
      time_column?: string | null;
      unit?: string | null;
      status?: "draft" | "confirmed" | "published";
    }) =>
      request<{ ok: boolean; metric_id: number }>("/semantics/metrics", {
        method: "POST",
        body: JSON.stringify(body),
      }),
    updateMetric: (
      id: number,
      body: Partial<
        Pick<
          SemanticMetric,
          "label" | "expression" | "time_column" | "unit" | "status"
        >
      > & { filters?: string[] },
    ) =>
      request<{ ok: boolean; updated: boolean }>(`/semantics/metrics/${id}`, {
        method: "PATCH",
        body: JSON.stringify(body),
      }),
    deleteMetric: (id: number) =>
      request<{ ok: boolean; metric_id: number; deleted: boolean }>(
        `/semantics/metrics/${id}`,
        {
          method: "DELETE",
        },
      ),
    createRelationship: (body: {
      from_connection_id: number;
      to_connection_id: number;
      from_table_id: number;
      from_column_id: number;
      to_table_id: number;
      to_column_id: number;
      relationship_type: string;
      match_type: string;
      confidence: number;
      status?: "suggested" | "confirmed" | "ignored" | "disabled" | "hidden";
    }) =>
      request<{ ok: boolean; relationship_id: number }>(
        "/semantics/relationships",
        {
          method: "POST",
          body: JSON.stringify(body),
        },
      ),
    updateRelationship: (
      id: number,
      body: Partial<
        Pick<
          SemanticRelationship,
          "relationship_type" | "match_type" | "confidence" | "status"
        >
      >,
    ) =>
      request<{ ok: boolean; updated: boolean }>(
        `/semantics/relationships/${id}`,
        {
          method: "PATCH",
          body: JSON.stringify(body),
        },
      ),
    deleteRelationship: (id: number) =>
      request<{ ok: boolean; relationship_id: number; deleted: boolean }>(
        `/semantics/relationships/${id}`,
        {
          method: "DELETE",
        },
      ),
  },
  chat: {
    threads: {
      list: () => request<ChatThread[]>("/chat/threads"),
      get: (id: number) => request<ChatThreadDetail>(`/chat/threads/${id}`),
      delete: (id: number) =>
        request<{ ok: boolean }>(`/chat/threads/${id}`, {
          method: "DELETE",
        }),
      clear: (id: number) =>
        request<{ ok: boolean; thread_id: number; deleted_messages: number }>(
          `/chat/threads/${id}/clear`,
          {
            method: "POST",
          },
        ),
    },
    stream: async (
      body: {
        connection_id?: number;
        connection_ids?: number[];
        model_config_id?: number | null;
        message: string;
        thread_id?: number | null;
        request_id?: string;
      },
      onEvent: (event: ChatStreamEvent) => void,
    ) => {
      const res = await fetch(`${BASE}/chat/`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });

      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: res.statusText }));
        throw new Error(errorMessageFromDetail(err.detail, res.statusText));
      }
      await readChatEventStream(res, onEvent);
    },
    events: async (
      requestId: string,
      onEvent: (event: ChatStreamEvent) => void,
    ) => {
      const res = await fetch(
        `${BASE}/chat/requests/${encodeURIComponent(requestId)}/events`,
      );

      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: res.statusText }));
        throw new Error(errorMessageFromDetail(err.detail, res.statusText));
      }

      await readChatEventStream(res, onEvent);
    },
  },
};
