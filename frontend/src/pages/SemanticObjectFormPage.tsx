import { useEffect, useMemo, useState, type ReactNode } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { ArrowLeft } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { StateMessage } from "@/components/ui/state-message";
import {
  api,
  type Connection,
  type ConnectionSemantics,
  type SemanticColumn,
  type SemanticMetric,
  type SemanticRelationship,
  type SemanticTable,
} from "@/lib/api";
import {
  ColumnForm,
  ColumnMeaningForm,
  HideFieldForm,
  MetricForm,
  RelationshipForm,
  TableForm,
  TableNoteForm,
  type MetricFormPayload,
  type RelationshipFormPayload,
} from "@/pages/SemanticsPage";

export type NewSemanticKind =
  | "table-note"
  | "column-meaning"
  | "metric"
  | "relationship"
  | "hidden-field";

export type EditSemanticKind = "table" | "column" | "metric" | "relationship";

type ColumnSelection = {
  table: SemanticTable;
  column: SemanticColumn;
  connection?: Connection;
};

type SemanticWorkspace = {
  connections: Connection[];
  semantics: ConnectionSemantics[];
  relationships: SemanticRelationship[];
  tables: SemanticTable[];
  columns: ColumnSelection[];
  metrics: SemanticMetric[];
};

const createCopy: Record<
  NewSemanticKind,
  { title: string; description: string; loadingMessage: string }
> = {
  "table-note": {
    title: "Add table note",
    description: "Select a table and describe how it should be understood.",
    loadingMessage: "Loading tables",
  },
  "column-meaning": {
    title: "Add column meaning",
    description: "Select a column and define its label, meaning, and type.",
    loadingMessage: "Loading columns",
  },
  metric: {
    title: "Add metric",
    description: "Create a reusable SQL metric from a semantic table.",
    loadingMessage: "Loading tables",
  },
  relationship: {
    title: "Add relationship",
    description: "Select two columns and define how they join.",
    loadingMessage: "Loading columns",
  },
  "hidden-field": {
    title: "Hide field",
    description: "Select a field to hide from the semantic layer.",
    loadingMessage: "Loading fields",
  },
};

const editCopy: Record<
  EditSemanticKind,
  { title: string; description: string; loadingMessage: string }
> = {
  table: {
    title: "Edit table",
    description: "Update table label, type, grain, and primary date.",
    loadingMessage: "Loading table",
  },
  column: {
    title: "Edit column",
    description: "Update column label, meaning, type, transform, and unit.",
    loadingMessage: "Loading column",
  },
  metric: {
    title: "Edit metric",
    description: "Update the metric definition and display metadata.",
    loadingMessage: "Loading metric",
  },
  relationship: {
    title: "Edit relationship",
    description: "Update the relationship type, match type, and confidence.",
    loadingMessage: "Loading relationship",
  },
};

export function NewSemanticObjectPage({ kind }: { kind: NewSemanticKind }) {
  const navigate = useNavigate();
  const [workspace, setWorkspace] = useState<SemanticWorkspace | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const copy = createCopy[kind];

  useEffect(() => {
    let active = true;

    loadSemanticWorkspace()
      .then((data) => {
        if (active) setWorkspace(data);
      })
      .catch((err) => {
        if (active) setLoadError(errorMessage(err));
      })
      .finally(() => {
        if (active) setLoading(false);
      });

    return () => {
      active = false;
    };
  }, []);

  async function save(action: () => Promise<unknown>) {
    setSubmitError(null);

    try {
      await action();
      navigate("/semantics");
    } catch (err) {
      setSubmitError(errorMessage(err));
    }
  }

  if (loading) {
    return (
      <StateMessage
        state="loading"
        variant="panel"
        message={copy.loadingMessage}
      />
    );
  }

  if (loadError || !workspace) {
    return (
      <StateMessage
        state="error"
        variant="panel"
        message={loadError ?? "Semantic workspace could not be loaded"}
      />
    );
  }

  if (workspace.connections.length === 0) {
    return (
      <StateMessage
        state="empty"
        variant="panel"
        title="No connections yet"
        message="Add a connection before creating semantics."
        action={
          <Button to="/connections/new" variant="primary">
            Add connection
          </Button>
        }
      />
    );
  }

  return (
    <SemanticFormLayout
      title={copy.title}
      description={copy.description}
      backTo="/semantics/new"
      error={submitError}
    >
      {kind === "table-note" && (
        <TableNoteForm
          tables={workspace.tables}
          onCancel={() => navigate("/semantics/new")}
          onSubmit={(table, body) =>
            save(() => api.semantics.updateTable(table.id, body))
          }
        />
      )}
      {kind === "column-meaning" && (
        <ColumnMeaningForm
          columns={workspace.columns}
          onCancel={() => navigate("/semantics/new")}
          onSubmit={({ column }, body) =>
            save(() => api.semantics.updateColumn(column.id, body))
          }
        />
      )}
      {kind === "metric" && (
        <MetricForm
          tables={workspace.tables}
          onCancel={() => navigate("/semantics/new")}
          onSubmit={(body) =>
            save(() =>
              api.semantics.createMetric({
                connection_id: requireNumber(
                  body.connection_id,
                  "Choose a table before saving the metric.",
                ),
                semantic_table_id: requireNumber(
                  body.semantic_table_id,
                  "Choose a table before saving the metric.",
                ),
                name: requireText(body.name, "Metric name is required."),
                label: body.label,
                expression: requireText(
                  body.expression,
                  "Metric SQL is required.",
                ),
                filters: body.filters,
                time_column: body.time_column,
                unit: body.unit,
                status: "confirmed",
              }),
            )
          }
        />
      )}
      {kind === "relationship" && (
        <RelationshipForm
          columns={workspace.columns}
          onCancel={() => navigate("/semantics/new")}
          onSubmit={(body) => save(() => createRelationship(body))}
        />
      )}
      {kind === "hidden-field" && (
        <HideFieldForm
          columns={workspace.columns}
          onCancel={() => navigate("/semantics/new")}
          onSubmit={({ column }) =>
            save(() => api.semantics.updateColumn(column.id, { hidden: true }))
          }
        />
      )}
    </SemanticFormLayout>
  );
}

export function EditSemanticObjectPage({ kind }: { kind: EditSemanticKind }) {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const numericId = Number(id);
  const [workspace, setWorkspace] = useState<SemanticWorkspace | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [submitState, setSubmitState] = useState<
    "success" | "warning" | "error" | null
  >(null);
  const [submitMessage, setSubmitMessage] = useState<string | null>(null);
  const copy = editCopy[kind];

  useEffect(() => {
    let active = true;

    loadSemanticWorkspace()
      .then((data) => {
        if (active) setWorkspace(data);
      })
      .catch((err) => {
        if (active) setLoadError(errorMessage(err));
      })
      .finally(() => {
        if (active) setLoading(false);
      });

    return () => {
      active = false;
    };
  }, []);

  const selected = useMemo(() => {
    if (!workspace || !Number.isFinite(numericId)) return null;

    if (kind === "table") {
      return workspace.tables.find((item) => item.id === numericId) ?? null;
    }

    if (kind === "column") {
      return (
        workspace.columns.find((item) => item.column.id === numericId) ?? null
      );
    }

    if (kind === "metric") {
      return workspace.metrics.find((item) => item.id === numericId) ?? null;
    }

    return (
      workspace.relationships.find((item) => item.id === numericId) ?? null
    );
  }, [kind, numericId, workspace]);

  const connectionById = useMemo(
    () =>
      new Map(
        workspace?.connections.map((connection) => [
          connection.id,
          connection,
        ]) ?? [],
      ),
    [workspace?.connections],
  );

  const tableById = useMemo(
    () => new Map(workspace?.tables.map((table) => [table.id, table]) ?? []),
    [workspace?.tables],
  );

  const columnById = useMemo(
    () =>
      new Map(
        workspace?.columns.map(({ column }) => [column.id, column]) ?? [],
      ),
    [workspace?.columns],
  );

  async function save(action: () => Promise<unknown>) {
    setSubmitState(null);
    setSubmitMessage(null);

    try {
      const result = await action();
      const updated =
        typeof result === "object" &&
        result !== null &&
        "updated" in result &&
        typeof (result as { updated?: unknown }).updated === "boolean"
          ? (result as { updated: boolean }).updated
          : true;

      if (updated) {
        setSubmitState("success");
        setSubmitMessage(
          `${capitalize(copy.title.replace("Edit ", ""))} updated.`,
        );
      } else {
        setSubmitState("warning");
        setSubmitMessage("No changes were detected.");
      }

      const refreshed = await loadSemanticWorkspace();
      setWorkspace(refreshed);
    } catch (err) {
      const message = errorMessage(err);
      setSubmitState("error");
      setSubmitMessage(message);
    }
  }

  if (loading) {
    return (
      <StateMessage
        state="loading"
        variant="panel"
        message={copy.loadingMessage}
      />
    );
  }

  if (loadError || !workspace) {
    return (
      <StateMessage
        state="error"
        variant="panel"
        message={loadError ?? "Semantic workspace could not be loaded"}
      />
    );
  }

  if (!selected) {
    return (
      <StateMessage
        state="error"
        variant="panel"
        message={`${copy.title.replace("Edit ", "")} not found`}
        action={
          <Button to="/semantics" variant="outline">
            Back to semantics
          </Button>
        }
      />
    );
  }

  return (
    <SemanticFormLayout
      title={copy.title}
      description={copy.description}
      backTo="/semantics"
      error={null}
    >
      {submitState && submitMessage && (
        <StateMessage
          state={submitState}
          variant="banner"
          message={submitMessage}
        />
      )}

      {kind === "table" && (
        <ReadOnlyContext
          rows={[
            {
              label: "Connection",
              value:
                connectionById.get((selected as SemanticTable).connection_id)
                  ?.name ?? "Unknown connection",
            },
            {
              label: "Source",
              value: (selected as SemanticTable).source_name,
            },
            {
              label: "Schema",
              value: (selected as SemanticTable).schema_name,
            },
            {
              label: "Table",
              value: (selected as SemanticTable).table_name,
            },
          ]}
        />
      )}

      {kind === "column" && (
        <ReadOnlyContext
          rows={[
            {
              label: "Semantic table",
              value: `${(selected as ColumnSelection).table.source_name}.${
                (selected as ColumnSelection).table.schema_name
              }.${(selected as ColumnSelection).table.table_name}`,
            },
            {
              label: "Column",
              value: (selected as ColumnSelection).column.column_name,
            },
          ]}
        />
      )}

      {kind === "metric" && (
        <ReadOnlyContext
          rows={[
            {
              label: "Semantic table",
              value: (() => {
                const table = tableById.get(
                  (selected as SemanticMetric).semantic_table_id,
                );
                if (!table) {
                  return "Unknown table";
                }
                return `${table.source_name}.${table.schema_name}.${table.table_name}`;
              })(),
            },
            {
              label: "Metric name",
              value: (selected as SemanticMetric).name,
            },
          ]}
        />
      )}

      {kind === "relationship" && (
        <ReadOnlyContext
          rows={[
            {
              label: "Connections",
              value: `${
                connectionById.get(
                  (selected as SemanticRelationship).from_connection_id,
                )?.name ?? "Unknown"
              } -> ${
                connectionById.get(
                  (selected as SemanticRelationship).to_connection_id,
                )?.name ?? "Unknown"
              }`,
            },
            {
              label: "From",
              value: (() => {
                const relationship = selected as SemanticRelationship;
                const table = tableById.get(relationship.from_table_id);
                const column = columnById.get(relationship.from_column_id);
                const tableName = table
                  ? `${table.source_name}.${table.schema_name}.${table.table_name}`
                  : relationship.from_table;
                const columnName = column
                  ? column.column_name
                  : relationship.from_column;
                return `${tableName}.${columnName}`;
              })(),
            },
            {
              label: "To",
              value: (() => {
                const relationship = selected as SemanticRelationship;
                const table = tableById.get(relationship.to_table_id);
                const column = columnById.get(relationship.to_column_id);
                const tableName = table
                  ? `${table.source_name}.${table.schema_name}.${table.table_name}`
                  : relationship.to_table;
                const columnName = column
                  ? column.column_name
                  : relationship.to_column;
                return `${tableName}.${columnName}`;
              })(),
            },
          ]}
        />
      )}

      {kind === "table" && (
        <TableForm
          table={selected as SemanticTable}
          onCancel={() => navigate("/semantics")}
          onSubmit={(body) =>
            save(() =>
              api.semantics.updateTable((selected as SemanticTable).id, body),
            )
          }
        />
      )}
      {kind === "column" && (
        <ColumnForm
          column={(selected as ColumnSelection).column}
          onCancel={() => navigate("/semantics")}
          onSubmit={(body) =>
            save(() =>
              api.semantics.updateColumn(
                (selected as ColumnSelection).column.id,
                body,
              ),
            )
          }
        />
      )}
      {kind === "metric" && (
        <MetricForm
          metric={selected as SemanticMetric}
          tables={workspace.tables}
          onCancel={() => navigate("/semantics")}
          onSubmit={(body: MetricFormPayload) =>
            save(() =>
              api.semantics.updateMetric((selected as SemanticMetric).id, body),
            )
          }
        />
      )}
      {kind === "relationship" && (
        <RelationshipForm
          relationship={selected as SemanticRelationship}
          columns={workspace.columns}
          onCancel={() => navigate("/semantics")}
          onSubmit={(body: RelationshipFormPayload) =>
            save(() =>
              api.semantics.updateRelationship(
                (selected as SemanticRelationship).id,
                body,
              ),
            )
          }
        />
      )}
    </SemanticFormLayout>
  );
}

function ReadOnlyContext({
  rows,
}: {
  rows: Array<{ label: string; value: ReactNode }>;
}) {
  return (
    <section className="space-y-3">
      {rows.map((row) => (
        <div key={row.label} className="space-y-1.5">
          <Label>{row.label}</Label>
          <p className="break-words text-sm text-foreground">{row.value}</p>
        </div>
      ))}
    </section>
  );
}

function SemanticFormLayout({
  title,
  description,
  backTo,
  error,
  children,
}: {
  title: string;
  description: string;
  backTo: string;
  error?: string | null;
  children: ReactNode;
}) {
  return (
    <div className="max-w-xl space-y-6">
      <div>
        <Button
          to={backTo}
          variant="ghost"
          className="mb-4 -ml-2 text-muted-foreground hover:text-foreground"
        >
          <ArrowLeft className="size-4" /> Back
        </Button>
        <h1 className="text-2xl font-semibold">{title}</h1>
        <p className="mt-1 text-sm text-muted-foreground">{description}</p>
      </div>

      {error && <StateMessage state="error" variant="banner" message={error} />}

      {children}
    </div>
  );
}

async function loadSemanticWorkspace(): Promise<SemanticWorkspace> {
  const connections = await api.connections.list();
  const connectionIds = connections.map((connection) => connection.id);
  const [semantics, relationshipRows] = await Promise.all([
    Promise.all(connectionIds.map((id) => api.semantics.getConnection(id))),
    connectionIds.length
      ? api.semantics.listRelationships(connectionIds)
      : Promise.resolve({ relationships: [] }),
  ]);
  const connectionById = new Map(
    connections.map((connection) => [connection.id, connection]),
  );
  const tables = semantics.flatMap((entry) => entry.tables);
  const columns = tables.flatMap((table) =>
    table.columns.map((column) => ({
      table,
      column,
      connection: connectionById.get(table.connection_id),
    })),
  );
  const metrics = semantics.flatMap((entry) => entry.metrics);

  return {
    connections,
    semantics,
    relationships: relationshipRows.relationships,
    tables,
    columns,
    metrics,
  };
}

function createRelationship(body: RelationshipFormPayload) {
  return api.semantics.createRelationship({
    from_connection_id: requireNumber(
      body.from_connection_id,
      "Choose a from column before saving the relationship.",
    ),
    to_connection_id: requireNumber(
      body.to_connection_id,
      "Choose a to column before saving the relationship.",
    ),
    from_table_id: requireNumber(
      body.from_table_id,
      "Choose a from column before saving the relationship.",
    ),
    from_column_id: requireNumber(
      body.from_column_id,
      "Choose a from column before saving the relationship.",
    ),
    to_table_id: requireNumber(
      body.to_table_id,
      "Choose a to column before saving the relationship.",
    ),
    to_column_id: requireNumber(
      body.to_column_id,
      "Choose a to column before saving the relationship.",
    ),
    relationship_type: requireText(
      body.relationship_type,
      "Relationship type is required.",
    ),
    match_type: requireText(body.match_type, "Match type is required."),
    confidence: body.confidence ?? 1,
    status: "confirmed",
  });
}

function requireNumber(value: number | undefined, message: string) {
  if (value === undefined || value === null) throw new Error(message);
  return value;
}

function requireText(value: string | undefined | null, message: string) {
  const trimmed = value?.trim();
  if (!trimmed) throw new Error(message);
  return trimmed;
}

function errorMessage(err: unknown) {
  return err instanceof Error ? err.message : "Something went wrong";
}

function capitalize(value: string) {
  if (!value) return value;
  return value[0].toUpperCase() + value.slice(1);
}
