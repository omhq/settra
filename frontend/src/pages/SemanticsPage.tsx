import {
  useEffect,
  useMemo,
  useState,
  type ComponentProps,
  type FormEvent,
  type ReactNode,
} from "react";
import { useNavigate } from "react-router-dom";
import { Loader2, Plus, RefreshCw, Search, Sparkles } from "lucide-react";

import {
  api,
  type AiIntrospectionFlow,
  type Connection,
  type ConnectionSemantics,
  type ModelConfig,
  type SemanticColumn,
  type SemanticMetric,
  type SemanticRelationship,
  type SemanticStatus,
  type SemanticTable,
} from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { PillButtonGroup } from "@/components/ui/pill-button-group";
import { SelectMenu, type SelectMenuOption } from "@/components/ui/select-menu";
import { StateMessage } from "@/components/ui/state-message";
import { useModal } from "@/components/ui/global-modal";
import { RowActions } from "@/components/ui/row-actions";
import {
  BlockActions,
  SemanticBlock,
  SemanticSection,
  isApprovedStatus,
} from "@/components/semantic-item";
import { cn } from "@/lib/utils";

type FilterKey = "all" | "review" | "approved" | "ignored" | "hidden";
type SemanticKind = "table" | "column" | "metric" | "relationship" | "warning";
type SemanticSectionKey =
  | "tables"
  | "columns"
  | "metrics"
  | "relationships"
  | "warnings";

type TableItem = {
  kind: "table";
  table: SemanticTable;
  connection: Connection;
};
type ColumnItem = {
  kind: "column";
  table: SemanticTable;
  column: SemanticColumn;
  connection: Connection;
};
type MetricItem = {
  kind: "metric";
  metric: SemanticMetric;
  table?: SemanticTable;
  connection: Connection;
};
type RelationshipItem = {
  kind: "relationship";
  relationship: SemanticRelationship;
};
type WarningItem = {
  kind: "warning";
  id: string;
  message: string;
  hidden?: boolean;
};
type SemanticItem =
  | TableItem
  | ColumnItem
  | MetricItem
  | RelationshipItem
  | WarningItem;

const filters: { key: FilterKey; label: string }[] = [
  { key: "all", label: "All" },
  { key: "review", label: "Needs Review" },
  { key: "approved", label: "Approved" },
  { key: "ignored", label: "Ignored" },
  { key: "hidden", label: "Hidden" },
];

const aiFlowOptions: { key: AiIntrospectionFlow; label: string }[] = [
  { key: "relationships", label: "Relationships" },
  { key: "metrics", label: "Metrics" },
];

const defaultOpenSemanticSections: Record<SemanticSectionKey, boolean> = {
  tables: true,
  columns: true,
  metrics: true,
  relationships: true,
  warnings: true,
};

const textAreaClassName =
  "min-h-24 w-full rounded-lg border border-input bg-background px-2.5 py-2 text-sm outline-none transition-colors placeholder:text-muted-foreground focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50";

function isGoogleSheetsWorksheetTable(table: SemanticTable) {
  return (
    table.source_name === "googlesheets" &&
    ![
      "googlesheets_cell",
      "googlesheets_sheet",
      "googlesheets_spreadsheet",
    ].includes(table.table_name)
  );
}

function parseHeaderRow(value: string) {
  const parsed = Number(value);
  return Number.isInteger(parsed) && parsed > 0 ? parsed : null;
}

function getSemanticTableHeaderRow(table: SemanticTable) {
  return parseHeaderRow(String(table.metadata?.header_row ?? ""));
}

function metadataWithHeaderRow(table: SemanticTable, headerRow: number | null) {
  const metadata = { ...(table.metadata ?? {}) };

  if (headerRow) metadata.header_row = headerRow;
  else delete metadata.header_row;

  return metadata;
}

export default function SemanticsPage() {
  const { openModal } = useModal();
  const navigate = useNavigate();
  const [connections, setConnections] = useState<Connection[]>([]);
  const [models, setModels] = useState<ModelConfig[]>([]);
  const [selectedConnectionIds, setSelectedConnectionIds] = useState<
    Set<number>
  >(new Set());
  const [selectedModelId, setSelectedModelId] = useState<number | null>(null);
  const [semantics, setSemantics] = useState<ConnectionSemantics[]>([]);
  const [relationships, setRelationships] = useState<SemanticRelationship[]>(
    [],
  );
  const [filter, setFilter] = useState<FilterKey>("all");
  const [searchQuery, setSearchQuery] = useState("");
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [aiRunning, setAiRunning] = useState(false);
  const [mutating, setMutating] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [aiWarnings, setAiWarnings] = useState<
    { id: string; message: string; hidden?: boolean }[]
  >([]);
  const [openSemanticSections, setOpenSemanticSections] = useState(() => ({
    ...defaultOpenSemanticSections,
  }));

  async function load() {
    setError(null);
    try {
      const [connectionRows, modelRows] = await Promise.all([
        api.connections.list(),
        api.models.list(),
      ]);
      setConnections(connectionRows);
      setModels(modelRows);
      setSelectedModelId((current) =>
        current && modelRows.some((model) => model.id === current)
          ? current
          : (modelRows[0]?.id ?? null),
      );
      setSelectedConnectionIds((current) =>
        current.size
          ? new Set(
              [...current].filter((id) =>
                connectionRows.some((connection) => connection.id === id),
              ),
            )
          : new Set(connectionRows.map((connection) => connection.id)),
      );

      const ids = connectionRows.map((connection) => connection.id);
      const [semanticRows, relationshipRows] = await Promise.all([
        Promise.all(ids.map((id) => api.semantics.getConnection(id))),
        ids.length
          ? api.semantics.listRelationships(ids)
          : Promise.resolve({ relationships: [] }),
      ]);

      setSemantics(semanticRows);
      setRelationships(relationshipRows.relationships);
    } catch (err: any) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void load();
  }, []);

  const selectedIds = useMemo(
    () =>
      selectedConnectionIds.size
        ? selectedConnectionIds
        : new Set(connections.map((connection) => connection.id)),
    [connections, selectedConnectionIds],
  );

  const connectionById = useMemo(
    () => new Map(connections.map((connection) => [connection.id, connection])),
    [connections],
  );

  const tables = useMemo(
    () =>
      semantics
        .flatMap((entry) => entry.tables)
        .filter((table) => selectedIds.has(table.connection_id)),
    [semantics, selectedIds],
  );

  const aiTables = useMemo(
    () =>
      tables
        .map((table) => {
          const connection = connectionById.get(table.connection_id);
          return connection ? { table, connection } : null;
        })
        .filter(Boolean) as { table: SemanticTable; connection: Connection }[],
    [connectionById, tables],
  );

  const tableById = useMemo(
    () => new Map(tables.map((table) => [table.id, table])),
    [tables],
  );

  const allColumns = useMemo(
    () =>
      tables.flatMap((table) =>
        table.columns.map((column) => ({
          table,
          column,
          connection: connectionById.get(table.connection_id),
        })),
      ),
    [connectionById, tables],
  );

  const allMetrics = useMemo(
    () =>
      semantics
        .flatMap((entry) => entry.metrics)
        .filter((metric) => selectedIds.has(metric.connection_id)),
    [semantics, selectedIds],
  );

  const selectedRelationships = useMemo(
    () =>
      relationships.filter(
        (relationship) =>
          selectedIds.has(relationship.from_connection_id) ||
          selectedIds.has(relationship.to_connection_id),
      ),
    [relationships, selectedIds],
  );

  const items = useMemo<SemanticItem[]>(() => {
    const tableItems: SemanticItem[] = tables
      .map((table) => {
        const connection = connectionById.get(table.connection_id);
        return connection
          ? { kind: "table" as const, table, connection }
          : null;
      })
      .filter(Boolean) as SemanticItem[];

    const columnItems: SemanticItem[] = allColumns
      .map(({ table, column, connection }) =>
        connection
          ? { kind: "column" as const, table, column, connection }
          : null,
      )
      .filter(Boolean) as SemanticItem[];

    const metricItems: SemanticItem[] = allMetrics
      .map((metric) => {
        const connection = connectionById.get(metric.connection_id);
        return connection
          ? {
              kind: "metric" as const,
              metric,
              table: tableById.get(metric.semantic_table_id),
              connection,
            }
          : null;
      })
      .filter(Boolean) as SemanticItem[];

    return [
      ...tableItems,
      ...columnItems,
      ...metricItems,
      ...selectedRelationships.map((relationship) => ({
        kind: "relationship" as const,
        relationship,
      })),
      ...aiWarnings.map((warning) => ({
        kind: "warning" as const,
        ...warning,
      })),
    ];
  }, [
    aiWarnings,
    allColumns,
    allMetrics,
    connectionById,
    selectedRelationships,
    tableById,
    tables,
  ]);

  const filteredItems = useMemo(
    () => items.filter((item) => itemMatchesFilter(item, filter)),
    [filter, items],
  );

  const searchFilteredItems = useMemo(
    () => filteredItems.filter((item) => itemMatchesSearch(item, searchQuery)),
    [filteredItems, searchQuery],
  );

  const grouped = useMemo(
    () => ({
      table: searchFilteredItems.filter(
        (item) => item.kind === "table",
      ) as TableItem[],
      column: searchFilteredItems.filter(
        (item) => item.kind === "column",
      ) as ColumnItem[],
      metric: searchFilteredItems.filter(
        (item) => item.kind === "metric",
      ) as MetricItem[],
      relationship: searchFilteredItems.filter(
        (item) => item.kind === "relationship",
      ) as RelationshipItem[],
      warning: searchFilteredItems.filter(
        (item) => item.kind === "warning",
      ) as WarningItem[],
    }),
    [searchFilteredItems],
  );

  const counts = useMemo(
    () =>
      Object.fromEntries(
        filters.map((item) => [
          item.key,
          items.filter((semanticItem) =>
            itemMatchesFilter(semanticItem, item.key),
          ).length,
        ]),
      ) as Record<FilterKey, number>,
    [items],
  );

  const modelOptions = useMemo<SelectMenuOption[]>(
    () =>
      models.map((model) => ({
        value: String(model.id),
        label: model.name,
        description: model.model,
        disabled: model.status !== "active",
      })),
    [models],
  );

  async function reloadAfterMutation(message?: string) {
    await load();
    if (message) setNotice(message);
  }

  async function perform(action: () => Promise<unknown>, message?: string) {
    setMutating(true);
    setError(null);
    setNotice(null);
    try {
      await action();
      await reloadAfterMutation(message);
    } catch (err: any) {
      setError(err.message);
    } finally {
      setMutating(false);
    }
  }

  async function refreshDrafts() {
    const ids = [...selectedIds];
    if (!ids.length) return;

    setRefreshing(true);
    setError(null);
    setNotice(null);
    try {
      await Promise.all(ids.map((id) => api.semantics.introspect(id)));
      await reloadAfterMutation("Semantics refreshed");
    } catch (err: any) {
      setError(err.message);
    } finally {
      setRefreshing(false);
    }
  }

  async function runAiIntrospection(
    modelId: number,
    semanticTableIds: number[],
    flows: AiIntrospectionFlow[],
    headerRowsByTableId: Record<number, number>,
  ) {
    const ids = [...selectedIds];
    if (!ids.length) return;

    setAiRunning(true);
    setError(null);
    setNotice(null);
    try {
      const headerRowUpdates = Object.entries(headerRowsByTableId);
      if (headerRowUpdates.length) {
        await Promise.all(
          headerRowUpdates.map(([tableId, headerRow]) => {
            const table = tableById.get(Number(tableId));
            return api.semantics.updateTable(Number(tableId), {
              metadata: table
                ? metadataWithHeaderRow(table, headerRow)
                : { header_row: headerRow },
            });
          }),
        );
      }

      const result = await api.semantics.aiIntrospect({
        connection_ids: ids,
        model_config_id: modelId,
        semantic_table_ids: semanticTableIds,
        flows,
        approved: true,
      });
      setAiWarnings(
        result.warnings.map((message, index) => ({
          id: `ai-${Date.now()}-${index}`,
          message,
        })),
      );
      await load();
      setFilter("review");

      const noticeParts: string[] = [];

      if (flows.includes("relationships")) {
        const returned = result.relationship_candidates_returned;
        const saved = result.relationship_candidates_suggested;
        const existing = result.relationship_candidates_existing;
        const withNotes = result.relationship_candidates_with_notes;
        const pruned = result.relationship_candidates_pruned ?? 0;
        const notSaved = result.skipped.length
          ? ` ${result.skipped.length} not saved.`
          : "";
        const alreadyPresent = existing ? ` ${existing} already existed.` : "";
        const stalePruned = pruned ? ` ${pruned} stale removed.` : "";
        const validationNotes = withNotes
          ? ` ${withNotes} need validation review.`
          : "";
        noticeParts.push(
          `Relationships: ${returned} returned, ${saved} saved.${alreadyPresent}${stalePruned}${validationNotes}${notSaved}`,
        );
      }

      if (flows.includes("metrics")) {
        const returned = result.metric_candidates_returned;
        const saved = result.metric_candidates_suggested;
        const existing = result.metric_candidates_existing;
        const skipped = result.metric_candidates_skipped ?? 0;
        const alreadyPresent = existing ? ` ${existing} already existed.` : "";
        const notSaved = skipped ? ` ${skipped} not saved.` : "";
        noticeParts.push(
          `Metrics: ${returned} returned, ${saved} saved.${alreadyPresent}${notSaved}`,
        );
      }

      const warnings = result.warnings.length
        ? ` ${result.warnings.length} warning${result.warnings.length === 1 ? "" : "s"} returned.`
        : "";
      setNotice(`${noticeParts.join(" ")}${warnings}`);
    } catch (err: any) {
      setError(err.message);
    } finally {
      setAiRunning(false);
    }
  }

  function openAiIntrospectionApproval() {
    if (!modelOptions.length) {
      setError("Add an active model before running AI introspection.");
      return;
    }

    const modelId = selectedModelId ?? Number(modelOptions[0].value);

    openModal({
      title: "AI Introspection",
      closeOnBackdrop: false,
      body: ({ close }) => (
        <AiIntrospectionApproval
          modelOptions={modelOptions}
          initialModelId={modelId}
          connectionCount={selectedIds.size}
          tables={aiTables}
          onCancel={close}
          onRun={(
            nextModelId,
            semanticTableIds,
            flows,
            headerRowsByTableId,
          ) => {
            setSelectedModelId(nextModelId);
            close();
            void runAiIntrospection(
              nextModelId,
              semanticTableIds,
              flows,
              headerRowsByTableId,
            );
          }}
        />
      ),
    });
  }

  function toggleConnection(id: number) {
    setSelectedConnectionIds((current) => {
      const next = new Set(current);
      if (next.has(id)) {
        if (next.size === 1) return current;
        next.delete(id);
      } else {
        next.add(id);
      }
      return next;
    });
  }

  function toggleSemanticSection(section: SemanticSectionKey) {
    setOpenSemanticSections((current) => ({
      ...current,
      [section]: !current[section],
    }));
  }

  function openReviewExamples(relationship: SemanticRelationship) {
    openModal({
      title: "Review link",
      body: (
        <div className="space-y-3">
          <KeyValue
            label="Link"
            value={`${relationship.from_table}.${relationship.from_column} = ${relationship.to_table}.${relationship.to_column}`}
          />
          <KeyValue
            label="Match"
            value={humanize(relationship.match_type || "manual")}
          />
          <KeyValue
            label="Confidence"
            value={confidenceLabel(relationship.confidence)}
          />
          <KeyValue label="Coverage" value="Not measured" />
        </div>
      ),
      actions: ({ close }) => (
        <Button type="button" variant="outline" onClick={close}>
          Close
        </Button>
      ),
    });
  }

  function openAddRule() {
    openModal({
      title: "Add Semantic Rule",
      body: ({ close }) => (
        <div className="grid gap-2">
          <RuleChoice
            label="Add Table Note"
            onClick={() => {
              close();
              openTableNoteForm();
            }}
          />
          <RuleChoice
            label="Add Column Meaning"
            onClick={() => {
              close();
              openColumnMeaningForm();
            }}
          />
          <RuleChoice
            label="Add Metric"
            onClick={() => {
              close();
              openMetricForm();
            }}
          />
          <RuleChoice
            label="Add Relationship"
            onClick={() => {
              close();
              openRelationshipForm();
            }}
          />
          <RuleChoice
            label="Hide Field"
            onClick={() => {
              close();
              openHideFieldForm();
            }}
          />
        </div>
      ),
    });
  }

  function openTableEditor(table: SemanticTable) {
    openModal({
      title: "Edit Table",
      body: ({ close }) => (
        <TableForm
          table={table}
          onCancel={close}
          onSubmit={(body) =>
            perform(
              () => api.semantics.updateTable(table.id, body),
              "Table updated",
            ).then(close)
          }
        />
      ),
    });
  }

  function openTableNoteForm() {
    openModal({
      title: "Add Table Note",
      body: ({ close }) => (
        <TableNoteForm
          tables={tables}
          onCancel={close}
          onSubmit={(table, body) =>
            perform(
              () => api.semantics.updateTable(table.id, body),
              "Table note saved",
            ).then(close)
          }
        />
      ),
    });
  }

  function openColumnEditor(table: SemanticTable, column: SemanticColumn) {
    openModal({
      title: "Edit Column",
      body: ({ close }) => (
        <ColumnForm
          column={column}
          onCancel={close}
          onSubmit={(body) =>
            perform(
              () => api.semantics.updateColumn(column.id, body),
              "Column updated",
            ).then(close)
          }
        />
      ),
    });
  }

  function openColumnMeaningForm() {
    openModal({
      title: "Add Column Meaning",
      body: ({ close }) => (
        <ColumnMeaningForm
          columns={allColumns}
          onCancel={close}
          onSubmit={({ column }, body) =>
            perform(
              () => api.semantics.updateColumn(column.id, body),
              "Column meaning saved",
            ).then(close)
          }
        />
      ),
    });
  }

  function openMetricEditor(metric: SemanticMetric) {
    openModal({
      title: "Edit Metric",
      body: ({ close }) => (
        <MetricForm
          metric={metric}
          tables={tables}
          onCancel={close}
          onSubmit={(body) =>
            perform(
              () => api.semantics.updateMetric(metric.id, body),
              "Metric updated",
            ).then(close)
          }
        />
      ),
    });
  }

  function openMetricForm() {
    openModal({
      title: "Add Metric",
      body: ({ close }) => (
        <MetricForm
          tables={tables}
          onCancel={close}
          onSubmit={(body) =>
            perform(
              () =>
                api.semantics.createMetric({
                  connection_id: body.connection_id!,
                  semantic_table_id: body.semantic_table_id!,
                  name: body.name!,
                  label: body.label,
                  expression: body.expression!,
                  filters: body.filters,
                  time_column: body.time_column,
                  unit: body.unit,
                  status: "confirmed",
                }),
              "Metric added",
            ).then(close)
          }
        />
      ),
    });
  }

  function openRelationshipEditor(relationship: SemanticRelationship) {
    openModal({
      title: "Edit Relationship",
      body: ({ close }) => (
        <RelationshipForm
          relationship={relationship}
          columns={allColumns}
          onCancel={close}
          onSubmit={(body) =>
            perform(
              () => api.semantics.updateRelationship(relationship.id, body),
              "Relationship updated",
            ).then(close)
          }
        />
      ),
    });
  }

  function openRelationshipForm() {
    openModal({
      title: "Add Relationship",
      body: ({ close }) => (
        <RelationshipForm
          columns={allColumns}
          onCancel={close}
          onSubmit={(body) =>
            perform(
              () =>
                api.semantics.createRelationship({
                  from_connection_id: body.from_connection_id!,
                  to_connection_id: body.to_connection_id!,
                  from_table_id: body.from_table_id!,
                  from_column_id: body.from_column_id!,
                  to_table_id: body.to_table_id!,
                  to_column_id: body.to_column_id!,
                  relationship_type: body.relationship_type!,
                  match_type: body.match_type!,
                  confidence: body.confidence!,
                  status: "confirmed",
                }),
              "Relationship added",
            ).then(close)
          }
        />
      ),
    });
  }

  function openHideFieldForm() {
    openModal({
      title: "Hide Field",
      body: ({ close }) => (
        <HideFieldForm
          columns={allColumns}
          onCancel={close}
          onSubmit={({ column }) =>
            perform(
              () => api.semantics.updateColumn(column.id, { hidden: true }),
              "Field hidden",
            ).then(close)
          }
        />
      ),
    });
  }

  function confirmDeleteSemanticObject({
    kind,
    name,
    detail,
    onDelete,
    message,
  }: {
    kind: "table" | "column" | "metric" | "relationship";
    name: string;
    detail: ReactNode;
    onDelete: () => Promise<unknown>;
    message: string;
  }) {
    openModal({
      title: `Delete ${kind}?`,
      body: (
        <p>
          This deletes{" "}
          <span className="font-medium text-foreground">{name}</span>. {detail}
        </p>
      ),
      actions: ({ close }) => (
        <>
          <Button type="button" variant="outline" onClick={close}>
            Cancel
          </Button>
          <Button
            type="button"
            variant="destructive"
            onClick={() => {
              close();
              void perform(onDelete, message);
            }}
          >
            Delete {kind}
          </Button>
        </>
      ),
    });
  }

  if (loading) {
    return (
      <StateMessage
        state="loading"
        variant="panel"
        message="Loading semantics"
      />
    );
  }

  if (!loading && connections.length === 0) {
    return (
      <StateMessage
        state="empty"
        variant="panel"
        title="No connections yet"
        message="Add a connection before reviewing semantics."
        action={
          <Button to="/connections/new" variant="primary">
            <Plus className="size-3" />
            Add connection
          </Button>
        }
      />
    );
  }

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="sticky top-0 z-10 shrink-0 space-y-6 bg-background pb-4">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
          <div>
            <h1 className="text-2xl font-semibold">Semantics</h1>
          </div>
          <div className="flex flex-wrap gap-2">
            <Button
              type="button"
              variant="outline"
              disabled={
                refreshing || aiRunning || mutating || selectedIds.size === 0
              }
              onClick={() => void refreshDrafts()}
            >
              {refreshing ? (
                <Loader2 className="size-3 animate-spin" />
              ) : (
                <RefreshCw className="size-3" />
              )}
              Refresh
            </Button>
            <Button
              type="button"
              variant="outline"
              disabled={
                refreshing || aiRunning || mutating || selectedIds.size === 0
              }
              onClick={openAiIntrospectionApproval}
            >
              {aiRunning ? (
                <Loader2 className="size-3 animate-spin" />
              ) : (
                <Sparkles className="size-3" />
              )}
              AI Introspection
            </Button>
            <Button
              to="/semantics/new"
              variant="primary"
              aria-label="Add semantic"
            >
              <Plus className="size-3" />
            </Button>
          </div>
        </div>

        <PillButtonGroup
          ariaLabel="Semantic status filters"
          items={filters.map((item) => ({
            id: item.key,
            label: item.label,
            count: counts[item.key],
            active: filter === item.key,
            onClick: () => setFilter(item.key),
          }))}
        />

        <div className="relative">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 size-3.5 -translate-y-1/2 text-muted-foreground" />
          <Input
            value={searchQuery}
            onChange={(event) => setSearchQuery(event.target.value)}
            className="h-8 pl-8"
            placeholder="Search semantic objects"
            aria-label="Search semantic objects"
          />
        </div>

        <PillButtonGroup
          label="Connections"
          ariaLabel="Connection filters"
          listClassName="gap-2"
          items={connections.map((connection) => ({
            id: connection.id,
            label: connection.name,
            detail: connection.plugin,
            active: selectedIds.has(connection.id),
            onClick: () => toggleConnection(connection.id),
          }))}
        />

        {error && (
          <StateMessage state="error" variant="banner" message={error} />
        )}
        {notice && (
          <StateMessage state="success" variant="banner" message={notice} />
        )}
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto pr-1 pt-2">
        <div className="space-y-6 pb-6">
          <SemanticSection
            title="Tables"
            count={grouped.table.length}
            open={openSemanticSections.tables}
            onToggle={() => toggleSemanticSection("tables")}
          >
            {grouped.table.map((item) => (
              <SemanticBlock
                key={`table-${item.table.id}`}
                title={item.table.table_name}
                status={item.table.status}
                hidden={isHidden(item.table)}
                meta={
                  <>
                    <Badge variant="secondary">{item.connection.name}</Badge>
                    <Badge variant="outline">{item.table.source_name}</Badge>
                  </>
                }
                rows={[
                  [
                    "Suggested label",
                    item.table.label || humanize(item.table.table_name),
                  ],
                  ["Type", tableTypeLabel(item.table.table_type)],
                  ["Grain", item.table.grain || "Not set"],
                  ["Primary date", item.table.primary_time_column || "Not set"],
                  ...(isGoogleSheetsWorksheetTable(item.table)
                    ? ([
                        [
                          "Header row",
                          getSemanticTableHeaderRow(item.table)
                            ? String(getSemanticTableHeaderRow(item.table))
                            : "Not set",
                        ],
                      ] as [string, string][])
                    : []),
                ]}
                actions={
                  <BlockActions
                    reviewLabel="Approve"
                    item={item.table}
                    hidden={isHidden(item.table)}
                    onApprove={() =>
                      perform(
                        () =>
                          api.semantics.updateTable(item.table.id, {
                            status: "confirmed",
                            hidden: false,
                          }),
                        "Table approved",
                      )
                    }
                    onEdit={() =>
                      navigate(`/semantics/tables/${item.table.id}/edit`)
                    }
                    onReject={() =>
                      perform(
                        () =>
                          api.semantics.updateTable(item.table.id, {
                            status: "disabled",
                          }),
                        "Table rejected",
                      )
                    }
                    onHide={() =>
                      perform(
                        () =>
                          api.semantics.updateTable(item.table.id, {
                            hidden: true,
                          }),
                        "Table hidden",
                      )
                    }
                    onDisable={() =>
                      perform(
                        () =>
                          api.semantics.updateTable(item.table.id, {
                            status: "disabled",
                          }),
                        "Table disabled",
                      )
                    }
                    onReset={() =>
                      perform(
                        () =>
                          api.semantics.updateTable(item.table.id, {
                            status: "draft",
                            hidden: false,
                          }),
                        "Table reset",
                      )
                    }
                    deleteLabel="Delete table"
                    onDelete={() =>
                      confirmDeleteSemanticObject({
                        kind: "table",
                        name: item.table.table_name,
                        detail:
                          "Its columns, metrics, and relationships will be removed too.",
                        onDelete: () =>
                          api.semantics.deleteTable(item.table.id),
                        message: "Table deleted",
                      })
                    }
                  />
                }
              />
            ))}
          </SemanticSection>

          <SemanticSection
            title="Columns"
            count={grouped.column.length}
            open={openSemanticSections.columns}
            onToggle={() => toggleSemanticSection("columns")}
          >
            {grouped.column.map((item) => (
              <SemanticBlock
                key={`column-${item.column.id}`}
                title={`${item.table.table_name}.${item.column.column_name}`}
                status={item.column.status}
                hidden={isHidden(item.column)}
                meta={
                  <>
                    <Badge variant="secondary">{item.connection.name}</Badge>
                    <Badge variant="outline">
                      {item.column.data_type || "unknown"}
                    </Badge>
                  </>
                }
                rows={[
                  [
                    "Suggested meaning",
                    item.column.description ||
                      item.column.label ||
                      humanize(item.column.column_name),
                  ],
                  [
                    "Type",
                    [humanize(item.column.semantic_type || "text")]
                      .filter(Boolean)
                      .join(", "),
                  ],
                  ["Transform", item.column.expression || "None"],
                  ["Unit", item.column.unit || "None"],
                ]}
                actions={
                  <BlockActions
                    item={item.column}
                    hidden={isHidden(item.column)}
                    onApprove={() =>
                      perform(
                        () =>
                          api.semantics.updateColumn(item.column.id, {
                            status: "confirmed",
                            hidden: false,
                          }),
                        "Column approved",
                      )
                    }
                    onEdit={() =>
                      navigate(`/semantics/columns/${item.column.id}/edit`)
                    }
                    onReject={() =>
                      perform(
                        () =>
                          api.semantics.updateColumn(item.column.id, {
                            status: "disabled",
                          }),
                        "Column rejected",
                      )
                    }
                    onHide={() =>
                      perform(
                        () =>
                          api.semantics.updateColumn(item.column.id, {
                            hidden: true,
                          }),
                        "Column hidden",
                      )
                    }
                    onDisable={() =>
                      perform(
                        () =>
                          api.semantics.updateColumn(item.column.id, {
                            status: "disabled",
                          }),
                        "Column disabled",
                      )
                    }
                    onReset={() =>
                      perform(
                        () =>
                          api.semantics.updateColumn(item.column.id, {
                            status: "draft",
                            hidden: false,
                          }),
                        "Column reset",
                      )
                    }
                    deleteLabel="Delete column"
                    onDelete={() =>
                      confirmDeleteSemanticObject({
                        kind: "column",
                        name: `${item.table.table_name}.${item.column.column_name}`,
                        detail:
                          "Relationships that use this column will be removed too.",
                        onDelete: () =>
                          api.semantics.deleteColumn(item.column.id),
                        message: "Column deleted",
                      })
                    }
                  />
                }
              />
            ))}
          </SemanticSection>

          <SemanticSection
            title="Metrics"
            count={grouped.metric.length}
            open={openSemanticSections.metrics}
            onToggle={() => toggleSemanticSection("metrics")}
          >
            {grouped.metric.map((item) => (
              <SemanticBlock
                key={`metric-${item.metric.id}`}
                title={item.metric.label || humanize(item.metric.name)}
                status={item.metric.status}
                hidden={item.metric.status === "hidden"}
                meta={
                  <>
                    <Badge variant="secondary">{item.connection.name}</Badge>
                    {item.table && (
                      <Badge variant="outline">{item.table.table_name}</Badge>
                    )}
                  </>
                }
                rows={[
                  [
                    "Definition",
                    item.metric.label || humanize(item.metric.name),
                  ],
                  ["SQL", item.metric.expression],
                  ["Time column", item.metric.time_column || "Not set"],
                  ["Unit", item.metric.unit || "None"],
                ]}
                actions={
                  <BlockActions
                    item={item.metric}
                    hidden={item.metric.status === "hidden"}
                    onApprove={() =>
                      perform(
                        () =>
                          api.semantics.updateMetric(item.metric.id, {
                            status: "confirmed",
                          }),
                        "Metric approved",
                      )
                    }
                    onEdit={() =>
                      navigate(`/semantics/metrics/${item.metric.id}/edit`)
                    }
                    onReject={() =>
                      perform(
                        () =>
                          api.semantics.updateMetric(item.metric.id, {
                            status: "disabled",
                          }),
                        "Metric rejected",
                      )
                    }
                    onHide={() =>
                      perform(
                        () =>
                          api.semantics.updateMetric(item.metric.id, {
                            status: "hidden",
                          }),
                        "Metric hidden",
                      )
                    }
                    onDisable={() =>
                      perform(
                        () =>
                          api.semantics.updateMetric(item.metric.id, {
                            status: "disabled",
                          }),
                        "Metric disabled",
                      )
                    }
                    onReset={() =>
                      perform(
                        () =>
                          api.semantics.updateMetric(item.metric.id, {
                            status: "draft",
                          }),
                        "Metric reset",
                      )
                    }
                    deleteLabel="Delete metric"
                    onDelete={() =>
                      confirmDeleteSemanticObject({
                        kind: "metric",
                        name: item.metric.label || humanize(item.metric.name),
                        detail: "The metric definition will be removed.",
                        onDelete: () =>
                          api.semantics.deleteMetric(item.metric.id),
                        message: "Metric deleted",
                      })
                    }
                  />
                }
              />
            ))}
          </SemanticSection>

          <SemanticSection
            title="Relationships"
            count={grouped.relationship.length}
            open={openSemanticSections.relationships}
            onToggle={() => toggleSemanticSection("relationships")}
          >
            {grouped.relationship.map((item) => {
              const relationship = item.relationship;

              return (
                <SemanticBlock
                  key={`relationship-${relationship.id}`}
                  title="Suggested link"
                  status={relationship.status}
                  hidden={relationship.status === "hidden"}
                  meta={
                    <>
                      <Badge variant="secondary">
                        {sourceLabel(relationship.from_source)}
                      </Badge>
                      <Badge variant="secondary">
                        {sourceLabel(relationship.to_source)}
                      </Badge>
                    </>
                  }
                  rows={[
                    [
                      "Tables",
                      `${humanize(relationship.from_table)} ↔ ${humanize(
                        relationship.to_table,
                      )}`,
                    ],
                    [
                      "Match using",
                      `${relationship.from_column} = ${relationship.to_column}`,
                    ],
                    ["Confidence", confidenceLabel(relationship.confidence)],
                    ["Coverage", "Not measured"],
                    ...(relationship.validation_note
                      ? ([
                          ["Validation note", relationship.validation_note],
                        ] as [string, ReactNode][])
                      : []),
                    ...(relationship.evidence
                      ? ([["Evidence", relationship.evidence]] as [
                          string,
                          ReactNode,
                        ][])
                      : []),
                  ]}
                  actions={
                    <BlockActions
                      reviewLabel="Approve Link"
                      item={relationship}
                      hidden={relationship.status === "hidden"}
                      onReview={() => openReviewExamples(relationship)}
                      onApprove={() =>
                        perform(
                          () =>
                            api.semantics.updateRelationship(relationship.id, {
                              status: "confirmed",
                            }),
                          "Relationship approved",
                        )
                      }
                      onEdit={() =>
                        navigate(
                          `/semantics/relationships/${relationship.id}/edit`,
                        )
                      }
                      onReject={() =>
                        perform(
                          () =>
                            api.semantics.updateRelationship(relationship.id, {
                              status: "ignored",
                            }),
                          "Relationship rejected",
                        )
                      }
                      onHide={() =>
                        perform(
                          () =>
                            api.semantics.updateRelationship(relationship.id, {
                              status: "hidden",
                            }),
                          "Relationship hidden",
                        )
                      }
                      onDisable={() =>
                        perform(
                          () =>
                            api.semantics.updateRelationship(relationship.id, {
                              status: "disabled",
                            }),
                          "Relationship disabled",
                        )
                      }
                      onReset={() =>
                        perform(
                          () =>
                            api.semantics.updateRelationship(relationship.id, {
                              status: "suggested",
                            }),
                          "Relationship reset",
                        )
                      }
                      deleteLabel="Delete relationship"
                      onDelete={() =>
                        confirmDeleteSemanticObject({
                          kind: "relationship",
                          name: `${relationship.from_table}.${relationship.from_column} = ${relationship.to_table}.${relationship.to_column}`,
                          detail: "Only this table link will be removed.",
                          onDelete: () =>
                            api.semantics.deleteRelationship(relationship.id),
                          message: "Relationship deleted",
                        })
                      }
                    />
                  }
                />
              );
            })}
          </SemanticSection>

          <SemanticSection
            title="Warnings"
            count={grouped.warning.length}
            open={openSemanticSections.warnings}
            onToggle={() => toggleSemanticSection("warnings")}
          >
            {grouped.warning.length ? (
              grouped.warning.map((item) => (
                <SemanticBlock
                  key={item.id}
                  title="Warning"
                  status="suggested"
                  hidden={item.hidden}
                  rows={[["Message", item.message]]}
                  actions={
                    <RowActions
                      actions={[
                        item.hidden
                          ? {
                              key: "reset",
                              title: "Reset warning",
                              onClick: () =>
                                setAiWarnings((current) =>
                                  current.map((warning) =>
                                    warning.id === item.id
                                      ? { ...warning, hidden: false }
                                      : warning,
                                  ),
                                ),
                            }
                          : {
                              key: "hide",
                              title: "Hide warning",
                              onClick: () =>
                                setAiWarnings((current) =>
                                  current.map((warning) =>
                                    warning.id === item.id
                                      ? { ...warning, hidden: true }
                                      : warning,
                                  ),
                                ),
                            },
                        {
                          key: "dismiss",
                          title: "Dismiss warning",
                          onClick: () =>
                            setAiWarnings((current) =>
                              current.filter(
                                (warning) => warning.id !== item.id,
                              ),
                            ),
                        },
                      ]}
                    />
                  }
                />
              ))
            ) : (
              <StateMessage
                state="empty"
                variant="inline"
                message="No warnings in the current review set."
              />
            )}
          </SemanticSection>
        </div>
      </div>
    </div>
  );
}

function AiIntrospectionApproval({
  modelOptions,
  initialModelId,
  connectionCount,
  tables,
  onCancel,
  onRun,
}: {
  modelOptions: SelectMenuOption[];
  initialModelId: number;
  connectionCount: number;
  tables: { table: SemanticTable; connection: Connection }[];
  onCancel: () => void;
  onRun: (
    modelId: number,
    semanticTableIds: number[],
    flows: AiIntrospectionFlow[],
    headerRowsByTableId: Record<number, number>,
  ) => void;
}) {
  const [modelId, setModelId] = useState(String(initialModelId || ""));
  const [approved, setApproved] = useState(false);
  const [tableQuery, setTableQuery] = useState("");
  const [headerRows, setHeaderRows] = useState<Record<number, string>>({});
  const [selectedFlows, setSelectedFlows] = useState<Set<AiIntrospectionFlow>>(
    () => new Set(["relationships"]),
  );
  const [selectedTableIds, setSelectedTableIds] = useState<Set<number>>(
    () => new Set(),
  );
  const selectedModel = modelOptions.find((option) => option.value === modelId);
  const selectedTableCount = selectedTableIds.size;
  const selectedFlowList = useMemo(
    () =>
      aiFlowOptions
        .map((option) => option.key)
        .filter((flow) => selectedFlows.has(flow)),
    [selectedFlows],
  );
  const selectedWorksheetTables = useMemo(
    () =>
      tables.filter(
        ({ table }) =>
          selectedTableIds.has(table.id) && isGoogleSheetsWorksheetTable(table),
      ),
    [selectedTableIds, tables],
  );
  const missingHeaderRows = selectedWorksheetTables.filter(({ table }) => {
    const value =
      headerRows[table.id] ?? String(getSemanticTableHeaderRow(table) || "");
    return !parseHeaderRow(value);
  });
  const canRun = Boolean(
    approved &&
    selectedModel &&
    !selectedModel.disabled &&
    selectedTableCount > 0 &&
    selectedFlowList.length > 0 &&
    missingHeaderRows.length === 0,
  );
  const filteredTables = useMemo(() => {
    const query = tableQuery.trim().toLowerCase();
    if (!query) return tables;

    return tables.filter(({ table, connection }) =>
      [
        table.table_name,
        table.label,
        table.description,
        connection.name,
        connection.plugin,
      ]
        .filter(Boolean)
        .some((value) => String(value).toLowerCase().includes(query)),
    );
  }, [tableQuery, tables]);

  function toggleTable(tableId: number) {
    setSelectedTableIds((current) => {
      const next = new Set(current);
      if (next.has(tableId)) next.delete(tableId);
      else next.add(tableId);
      return next;
    });
  }

  function toggleFlow(flow: AiIntrospectionFlow) {
    setSelectedFlows((current) => {
      const next = new Set(current);
      if (next.has(flow)) next.delete(flow);
      else next.add(flow);
      return next;
    });
  }

  function setHeaderRow(tableId: number, value: string) {
    setHeaderRows((current) => ({ ...current, [tableId]: value }));
  }

  function run() {
    const pendingHeaderRows: Record<number, number> = {};

    for (const { table } of selectedWorksheetTables) {
      const rawValue =
        headerRows[table.id] ?? String(getSemanticTableHeaderRow(table) || "");
      const headerRow = parseHeaderRow(rawValue);
      if (!headerRow) return;

      if (headerRow !== getSemanticTableHeaderRow(table)) {
        pendingHeaderRows[table.id] = headerRow;
      }
    }

    onRun(
      Number(modelId),
      [...selectedTableIds],
      selectedFlowList,
      pendingHeaderRows,
    );
  }

  return (
    <div className="space-y-4 text-foreground">
      <div className="space-y-1.5">
        <Label>Model</Label>
        <SelectMenu
          value={modelId || null}
          onChange={setModelId}
          options={modelOptions}
          placeholder="Select model"
          triggerClassName="min-w-0"
        />
      </div>

      <div className="space-y-2">
        <Label>Flows</Label>
        <div className="grid gap-2 sm:grid-cols-2">
          {aiFlowOptions.map((flow) => {
            const checked = selectedFlows.has(flow.key);

            return (
              <label
                key={flow.key}
                className={cn(
                  "flex cursor-pointer items-center gap-2 rounded-lg border bg-background p-3 text-sm transition-colors hover:bg-muted",
                  checked && "bg-muted/60",
                )}
              >
                <input
                  type="checkbox"
                  className="size-4 rounded border-input"
                  checked={checked}
                  onChange={() => toggleFlow(flow.key)}
                />
                <span className="font-medium">{flow.label}</span>
              </label>
            );
          })}
        </div>
      </div>

      <div className="space-y-2">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <Label>Tables</Label>
          <Badge variant="secondary">
            {selectedTableIds.size}/{tables.length}
          </Badge>
        </div>
        <div className="relative">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 size-3.5 -translate-y-1/2 text-muted-foreground" />
          <Input
            value={tableQuery}
            onChange={(event) => setTableQuery(event.target.value)}
            className="h-8 pl-8"
            placeholder="Search tables"
          />
        </div>
        <div className="max-h-64 overflow-y-auto rounded-lg border bg-background p-1">
          {filteredTables.map(({ table, connection }) => {
            const checked = selectedTableIds.has(table.id);

            return (
              <label
                key={table.id}
                className={cn(
                  "flex cursor-pointer items-start gap-2 rounded-md px-2 py-2 text-sm transition-colors hover:bg-muted",
                  checked && "bg-muted/60",
                )}
              >
                <input
                  type="checkbox"
                  className="mt-0.5 size-4 rounded border-input"
                  checked={checked}
                  onChange={() => toggleTable(table.id)}
                />
                <span className="min-w-0 flex-1">
                  <span className="block truncate font-medium">
                    {table.label || table.table_name}
                  </span>
                  <span className="mt-0.5 block truncate text-xs text-muted-foreground">
                    {connection.name} - {table.table_name}
                  </span>
                </span>
              </label>
            );
          })}
          {!filteredTables.length && (
            <div className="px-2 py-6 text-center text-sm text-muted-foreground">
              No tables match
            </div>
          )}
        </div>
        <div className="flex flex-wrap gap-2">
          <Button
            type="button"
            variant="outline"
            onClick={() =>
              setSelectedTableIds(new Set(tables.map(({ table }) => table.id)))
            }
          >
            Select All
          </Button>
          <Button
            type="button"
            variant="outline"
            onClick={() => setSelectedTableIds(new Set())}
          >
            Clear
          </Button>
        </div>
      </div>

      {selectedWorksheetTables.length > 0 && (
        <div className="space-y-2 rounded-lg border bg-background p-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <Label>Google Sheets Header Rows</Label>
            <Badge
              variant={missingHeaderRows.length ? "destructive" : "secondary"}
            >
              {selectedWorksheetTables.length - missingHeaderRows.length}/
              {selectedWorksheetTables.length}
            </Badge>
          </div>
          <div className="space-y-2">
            {selectedWorksheetTables.map(({ table, connection }) => {
              const value =
                headerRows[table.id] ??
                String(getSemanticTableHeaderRow(table) || "");
              const valid = Boolean(parseHeaderRow(value));

              return (
                <div
                  key={table.id}
                  className="grid gap-2 rounded-md border border-border/70 p-2 sm:grid-cols-[minmax(0,1fr)_8rem]"
                >
                  <div className="min-w-0">
                    <div className="truncate text-sm font-medium">
                      {table.label || table.table_name}
                    </div>
                    <div className="truncate text-xs text-muted-foreground">
                      {connection.name} - {table.table_name}
                    </div>
                  </div>
                  <Input
                    type="number"
                    min={1}
                    step={1}
                    value={value}
                    aria-label={`Header row for ${table.table_name}`}
                    aria-invalid={!valid}
                    onChange={(event) =>
                      setHeaderRow(table.id, event.target.value)
                    }
                  />
                </div>
              );
            })}
          </div>
        </div>
      )}

      <label className="flex items-start gap-2 rounded-lg border bg-background p-3 text-sm">
        <input
          type="checkbox"
          className="mt-0.5 size-4 rounded border-input"
          checked={approved}
          onChange={(event) => setApproved(event.target.checked)}
        />
        <span>
          Approve AI introspection for {selectedTableCount} selected table
          {selectedTableCount === 1 ? "" : "s"} across {connectionCount}{" "}
          selected connection{connectionCount === 1 ? "" : "s"} and{" "}
          {selectedFlowList.length} selected flow
          {selectedFlowList.length === 1 ? "" : "s"}. Suggestions will stay in
          review.
        </span>
      </label>

      <div className="flex justify-end gap-2 pt-1">
        <Button type="button" variant="outline" onClick={onCancel}>
          Cancel
        </Button>
        <Button
          type="button"
          variant="primary"
          disabled={!canRun}
          onClick={run}
        >
          <Sparkles className="size-3.5" />
          Run AI Pass
        </Button>
      </div>
    </div>
  );
}

export function TableForm({
  table,
  onCancel,
  onSubmit,
}: {
  table: SemanticTable;
  onCancel: () => void;
  onSubmit: (
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
      >
    >,
  ) => Promise<void>;
}) {
  const [label, setLabel] = useState(table.label || "");
  const [description, setDescription] = useState(table.description || "");
  const [tableType, setTableType] = useState(table.table_type || "dimension");
  const [grain, setGrain] = useState(table.grain || "");
  const [primaryDate, setPrimaryDate] = useState(
    table.primary_time_column || "",
  );
  const [headerRow, setHeaderRow] = useState(
    String(getSemanticTableHeaderRow(table) || ""),
  );
  const isWorksheetTable = isGoogleSheetsWorksheetTable(table);

  async function submit(event: FormEvent) {
    event.preventDefault();
    const body: Partial<
      Pick<
        SemanticTable,
        | "label"
        | "description"
        | "table_type"
        | "grain"
        | "primary_time_column"
        | "metadata"
        | "hidden"
      >
    > = {
      label,
      description,
      table_type: tableType,
      grain,
      primary_time_column: primaryDate || null,
      hidden: false,
    };

    if (isWorksheetTable) {
      body.metadata = metadataWithHeaderRow(table, parseHeaderRow(headerRow));
    }

    await onSubmit(body);
  }

  return (
    <form className="space-y-3" onSubmit={submit}>
      <TextField label="Label" value={label} onChange={setLabel} />
      <TextAreaField
        label="Description"
        value={description}
        onChange={setDescription}
      />
      <SelectField
        label="Type"
        value={tableType}
        onChange={setTableType}
        options={[
          { value: "fact", label: "Fact table" },
          { value: "dimension", label: "Dimension table" },
          { value: "bridge", label: "Bridge table" },
        ]}
      />
      <TextField label="Grain" value={grain} onChange={setGrain} />
      <TextField
        label="Primary date"
        value={primaryDate}
        onChange={setPrimaryDate}
      />
      {isWorksheetTable && (
        <TextField
          label="Header row"
          type="number"
          min={1}
          step={1}
          value={headerRow}
          onChange={setHeaderRow}
        />
      )}
      <FormActions onCancel={onCancel} submitLabel="Save" />
    </form>
  );
}

export function TableNoteForm({
  tables,
  onCancel,
  onSubmit,
}: {
  tables: SemanticTable[];
  onCancel: () => void;
  onSubmit: (
    table: SemanticTable,
    body: Partial<Pick<SemanticTable, "label" | "description" | "status">>,
  ) => Promise<void>;
}) {
  const [tableId, setTableId] = useState(String(tables[0]?.id || ""));
  const table = tables.find((item) => String(item.id) === tableId);
  const [label, setLabel] = useState(table?.label || "");
  const [description, setDescription] = useState(table?.description || "");

  useEffect(() => {
    if (!table) return;
    setLabel(table.label || "");
    setDescription(table.description || "");
  }, [table?.id]);

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!table) return;
    await onSubmit(table, { label, description, status: "confirmed" });
  }

  return (
    <form className="space-y-3" onSubmit={submit}>
      <SelectField
        label="Table"
        value={tableId}
        onChange={setTableId}
        options={tables.map((item) => ({
          value: String(item.id),
          label: item.table_name,
        }))}
      />
      <TextField label="Label" value={label} onChange={setLabel} />
      <TextAreaField
        label="Description"
        value={description}
        onChange={setDescription}
      />
      <FormActions onCancel={onCancel} submitLabel="Save" disabled={!table} />
    </form>
  );
}

export function ColumnForm({
  column,
  onCancel,
  onSubmit,
}: {
  column: SemanticColumn;
  onCancel: () => void;
  onSubmit: (
    body: Partial<
      Pick<
        SemanticColumn,
        | "label"
        | "description"
        | "semantic_type"
        | "expression"
        | "unit"
        | "hidden"
      >
    >,
  ) => Promise<void>;
}) {
  const [label, setLabel] = useState(column.label || "");
  const [description, setDescription] = useState(column.description || "");
  const [semanticType, setSemanticType] = useState(
    column.semantic_type || "text",
  );
  const [expression, setExpression] = useState(column.expression || "");
  const [unit, setUnit] = useState(column.unit || "");

  async function submit(event: FormEvent) {
    event.preventDefault();
    await onSubmit({
      label,
      description,
      semantic_type: semanticType,
      expression: expression || null,
      unit: unit || null,
      hidden: false,
    });
  }

  return (
    <form className="space-y-3" onSubmit={submit}>
      <TextField label="Label" value={label} onChange={setLabel} />
      <TextAreaField
        label="Meaning"
        value={description}
        onChange={setDescription}
      />
      <TextField label="Type" value={semanticType} onChange={setSemanticType} />
      <TextField
        label="Transform"
        value={expression}
        onChange={setExpression}
      />
      <TextField label="Unit" value={unit} onChange={setUnit} />
      <FormActions onCancel={onCancel} submitLabel="Save" />
    </form>
  );
}

export function ColumnMeaningForm({
  columns,
  onCancel,
  onSubmit,
}: {
  columns: {
    table: SemanticTable;
    column: SemanticColumn;
    connection?: Connection;
  }[];
  onCancel: () => void;
  onSubmit: (
    selection: { table: SemanticTable; column: SemanticColumn },
    body: Partial<
      Pick<SemanticColumn, "label" | "description" | "semantic_type" | "status">
    >,
  ) => Promise<void>;
}) {
  const [columnId, setColumnId] = useState(String(columns[0]?.column.id || ""));
  const selection = columns.find((item) => String(item.column.id) === columnId);
  const [label, setLabel] = useState(selection?.column.label || "");
  const [description, setDescription] = useState(
    selection?.column.description || "",
  );
  const [semanticType, setSemanticType] = useState(
    selection?.column.semantic_type || "text",
  );

  useEffect(() => {
    if (!selection) return;
    setLabel(selection.column.label || "");
    setDescription(selection.column.description || "");
    setSemanticType(selection.column.semantic_type || "text");
  }, [selection?.column.id]);

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!selection) return;
    await onSubmit(selection, {
      label,
      description,
      semantic_type: semanticType,
      status: "confirmed",
    });
  }

  return (
    <form className="space-y-3" onSubmit={submit}>
      <SelectField
        label="Column"
        value={columnId}
        onChange={setColumnId}
        options={columns.map((item) => ({
          value: String(item.column.id),
          label: `${item.table.table_name}.${item.column.column_name}`,
          description: item.connection?.name,
        }))}
      />
      <TextField label="Label" value={label} onChange={setLabel} />
      <TextAreaField
        label="Meaning"
        value={description}
        onChange={setDescription}
      />
      <TextField label="Type" value={semanticType} onChange={setSemanticType} />
      <FormActions
        onCancel={onCancel}
        submitLabel="Save"
        disabled={!selection}
      />
    </form>
  );
}

export type MetricFormPayload = {
  connection_id?: number;
  semantic_table_id?: number;
  name?: string;
  label?: string | null;
  expression?: string;
  filters?: string[];
  time_column?: string | null;
  unit?: string | null;
};

export function MetricForm({
  metric,
  tables,
  onCancel,
  onSubmit,
}: {
  metric?: SemanticMetric;
  tables: SemanticTable[];
  onCancel: () => void;
  onSubmit: (body: MetricFormPayload) => Promise<void>;
}) {
  const [tableId, setTableId] = useState(
    String(metric?.semantic_table_id || tables[0]?.id || ""),
  );
  const table = tables.find((item) => String(item.id) === tableId);
  const [name, setName] = useState(metric?.name || "");
  const [label, setLabel] = useState(metric?.label || "");
  const [expression, setExpression] = useState(metric?.expression || "");
  const [timeColumn, setTimeColumn] = useState(metric?.time_column || "");
  const [unit, setUnit] = useState(metric?.unit || "");
  const [filters, setFilters] = useState(parseFilters(metric?.filters_json));

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!table && !metric) return;

    await onSubmit({
      connection_id: metric?.connection_id || table?.connection_id,
      semantic_table_id: metric?.semantic_table_id || table?.id,
      name,
      label,
      expression,
      filters: filters
        .split("\n")
        .map((line) => line.trim())
        .filter(Boolean),
      time_column: timeColumn || null,
      unit: unit || null,
    });
  }

  return (
    <form className="space-y-3" onSubmit={submit}>
      {!metric && (
        <SelectField
          label="Table"
          value={tableId}
          onChange={setTableId}
          options={tables.map((item) => ({
            value: String(item.id),
            label: item.table_name,
          }))}
        />
      )}
      {!metric && (
        <TextField label="Name" value={name} onChange={setName} required />
      )}
      <TextField label="Label" value={label} onChange={setLabel} />
      <TextAreaField
        label="SQL"
        value={expression}
        onChange={setExpression}
        required
      />
      <TextField
        label="Time column"
        value={timeColumn}
        onChange={setTimeColumn}
      />
      <TextField label="Unit" value={unit} onChange={setUnit} />
      <TextAreaField label="Filters" value={filters} onChange={setFilters} />
      <FormActions
        onCancel={onCancel}
        submitLabel="Save"
        disabled={!metric && !table}
      />
    </form>
  );
}

export type RelationshipFormPayload = {
  from_connection_id?: number;
  to_connection_id?: number;
  from_table_id?: number;
  from_column_id?: number;
  to_table_id?: number;
  to_column_id?: number;
  relationship_type?: string;
  match_type?: string;
  confidence?: number;
};

export function RelationshipForm({
  relationship,
  columns,
  onCancel,
  onSubmit,
}: {
  relationship?: SemanticRelationship;
  columns: {
    table: SemanticTable;
    column: SemanticColumn;
    connection?: Connection;
  }[];
  onCancel: () => void;
  onSubmit: (body: RelationshipFormPayload) => Promise<void>;
}) {
  const [fromColumnId, setFromColumnId] = useState(
    String(columns[0]?.column.id || ""),
  );
  const [toColumnId, setToColumnId] = useState(
    String(columns[1]?.column.id || ""),
  );
  const [relationshipType, setRelationshipType] = useState(
    relationship?.relationship_type || "many_to_one",
  );
  const [matchType, setMatchType] = useState(
    relationship?.match_type || "manual",
  );
  const [confidence, setConfidence] = useState(
    String(relationship?.confidence ?? 1),
  );

  const fromSelection = columns.find(
    (item) => String(item.column.id) === fromColumnId,
  );
  const toSelection = columns.find(
    (item) => String(item.column.id) === toColumnId,
  );

  async function submit(event: FormEvent) {
    event.preventDefault();
    const parsedConfidence = Number.parseFloat(confidence);

    if (relationship) {
      await onSubmit({
        relationship_type: relationshipType,
        match_type: matchType,
        confidence: Number.isFinite(parsedConfidence) ? parsedConfidence : 1,
      });
      return;
    }

    if (!fromSelection || !toSelection) return;

    await onSubmit({
      from_connection_id: fromSelection.table.connection_id,
      to_connection_id: toSelection.table.connection_id,
      from_table_id: fromSelection.table.id,
      from_column_id: fromSelection.column.id,
      to_table_id: toSelection.table.id,
      to_column_id: toSelection.column.id,
      relationship_type: relationshipType,
      match_type: matchType,
      confidence: Number.isFinite(parsedConfidence) ? parsedConfidence : 1,
    });
  }

  return (
    <form className="space-y-3" onSubmit={submit}>
      {!relationship && (
        <>
          <SelectField
            label="From column"
            value={fromColumnId}
            onChange={setFromColumnId}
            options={columns.map((item) => ({
              value: String(item.column.id),
              label: `${item.table.table_name}.${item.column.column_name}`,
              description: item.connection?.name,
            }))}
          />
          <SelectField
            label="To column"
            value={toColumnId}
            onChange={setToColumnId}
            options={columns.map((item) => ({
              value: String(item.column.id),
              label: `${item.table.table_name}.${item.column.column_name}`,
              description: item.connection?.name,
            }))}
          />
        </>
      )}
      <SelectField
        label="Relationship type"
        value={relationshipType}
        onChange={setRelationshipType}
        options={[
          { value: "one_to_one", label: "One to one" },
          { value: "many_to_one", label: "Many to one" },
          { value: "one_to_many", label: "One to many" },
          { value: "many_to_many", label: "Many to many" },
        ]}
      />
      <TextField label="Match type" value={matchType} onChange={setMatchType} />
      <TextField
        label="Confidence"
        type="number"
        step="0.01"
        min="0"
        max="1"
        value={confidence}
        onChange={setConfidence}
      />
      <FormActions
        onCancel={onCancel}
        submitLabel="Save"
        disabled={!relationship && (!fromSelection || !toSelection)}
      />
    </form>
  );
}

export function HideFieldForm({
  columns,
  onCancel,
  onSubmit,
}: {
  columns: {
    table: SemanticTable;
    column: SemanticColumn;
    connection?: Connection;
  }[];
  onCancel: () => void;
  onSubmit: (selection: {
    table: SemanticTable;
    column: SemanticColumn;
  }) => Promise<void>;
}) {
  const [columnId, setColumnId] = useState(String(columns[0]?.column.id || ""));
  const selection = columns.find((item) => String(item.column.id) === columnId);

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!selection) return;
    await onSubmit(selection);
  }

  return (
    <form className="space-y-3" onSubmit={submit}>
      <SelectField
        label="Field"
        value={columnId}
        onChange={setColumnId}
        options={columns.map((item) => ({
          value: String(item.column.id),
          label: `${item.table.table_name}.${item.column.column_name}`,
          description: item.connection?.name,
        }))}
      />
      <FormActions
        onCancel={onCancel}
        submitLabel="Hide"
        disabled={!selection}
      />
    </form>
  );
}

function RuleChoice({
  label,
  onClick,
}: {
  label: string;
  onClick: () => void;
}) {
  return (
    <Button
      type="button"
      variant="outline"
      className="w-full justify-start"
      onClick={onClick}
    >
      {label}
    </Button>
  );
}

function TextField({
  label,
  value,
  onChange,
  type = "text",
  required,
  disabled,
  ...inputProps
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  type?: string;
  required?: boolean;
  disabled?: boolean;
} & Omit<ComponentProps<"input">, "onChange" | "value">) {
  const id = `field-${label.replace(/\W+/g, "-").toLowerCase()}`;

  return (
    <div className="space-y-1.5">
      <Label htmlFor={id}>{label}</Label>
      <Input
        id={id}
        type={type}
        value={value}
        required={required}
        disabled={disabled}
        onChange={(event) => onChange(event.target.value)}
        {...inputProps}
      />
    </div>
  );
}

function TextAreaField({
  label,
  value,
  onChange,
  required,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  required?: boolean;
}) {
  const id = `field-${label.replace(/\W+/g, "-").toLowerCase()}`;

  return (
    <div className="space-y-1.5">
      <Label htmlFor={id}>{label}</Label>
      <textarea
        id={id}
        value={value}
        required={required}
        className={textAreaClassName}
        onChange={(event) => onChange(event.target.value)}
      />
    </div>
  );
}

function SelectField({
  label,
  value,
  onChange,
  options,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  options: { value: string; label: string; description?: string }[];
}) {
  return (
    <div className="space-y-1.5">
      <Label>{label}</Label>
      <SelectMenu
        value={value || null}
        onChange={onChange}
        options={options}
        disabled={!options.length}
        placeholder={options.length ? "Select" : "No options"}
        triggerClassName="min-w-0"
      />
    </div>
  );
}

function FormActions({
  onCancel,
  submitLabel,
  disabled,
}: {
  onCancel: () => void;
  submitLabel: string;
  disabled?: boolean;
}) {
  return (
    <div className="flex justify-end gap-2 pt-2">
      <Button type="button" variant="outline" onClick={onCancel}>
        Cancel
      </Button>
      <Button type="submit" variant="primary" disabled={disabled}>
        {submitLabel}
      </Button>
    </div>
  );
}

function KeyValue({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div>
      <p className="text-xs font-medium text-muted-foreground">{label}</p>
      <p className="mt-0.5 break-words text-foreground">{value}</p>
    </div>
  );
}

function itemMatchesFilter(item: SemanticItem, filter: FilterKey) {
  if (filter === "all") return true;
  if (filter === "hidden") return itemHidden(item);
  if (itemHidden(item)) return false;

  const status = itemStatus(item);

  if (filter === "review") return status === "draft" || status === "suggested";
  if (filter === "approved") return isApprovedStatus(status);
  if (filter === "ignored")
    return status === "ignored" || status === "disabled";

  return true;
}

function itemMatchesSearch(item: SemanticItem, query: string) {
  const normalizedQuery = query.trim().toLowerCase();
  if (!normalizedQuery) return true;

  if (item.kind === "table") {
    return includesQuery(
      normalizedQuery,
      item.table.table_name,
      item.table.label,
      item.table.description,
      item.connection.name,
      item.connection.plugin,
    );
  }

  if (item.kind === "column") {
    return includesQuery(
      normalizedQuery,
      item.table.table_name,
      item.column.column_name,
      item.column.label,
      item.column.description,
      item.connection.name,
      item.connection.plugin,
    );
  }

  if (item.kind === "metric") {
    return includesQuery(
      normalizedQuery,
      item.metric.name,
      item.metric.label,
      item.table?.table_name,
      item.connection.name,
      item.connection.plugin,
    );
  }

  if (item.kind === "relationship") {
    return includesQuery(
      normalizedQuery,
      item.relationship.from_source,
      item.relationship.to_source,
      item.relationship.from_table,
      item.relationship.to_table,
      item.relationship.from_column,
      item.relationship.to_column,
      item.relationship.relationship_type,
      item.relationship.match_type,
      item.relationship.validation_note,
      item.relationship.evidence,
      item.relationship.rationale,
    );
  }

  return includesQuery(normalizedQuery, item.message);
}

function includesQuery(
  query: string,
  ...values: Array<string | null | undefined>
) {
  return values
    .filter(Boolean)
    .some((value) => String(value).toLowerCase().includes(query));
}

function itemStatus(item: SemanticItem): SemanticStatus {
  if (item.kind === "table") return item.table.status;
  if (item.kind === "column") return item.column.status;
  if (item.kind === "metric") return item.metric.status;
  if (item.kind === "relationship") return item.relationship.status;
  return "suggested";
}

function itemHidden(item: SemanticItem) {
  if (item.kind === "table") return isHidden(item.table);
  if (item.kind === "column") return isHidden(item.column);
  if (item.kind === "metric") return item.metric.status === "hidden";
  if (item.kind === "relationship")
    return item.relationship.status === "hidden";
  return Boolean(item.hidden);
}

function isHidden(item: {
  hidden?: boolean | number;
  status?: SemanticStatus;
}) {
  return Boolean(item.hidden) || item.status === "hidden";
}

function humanize(value: string | null | undefined) {
  if (!value) return "Not set";
  return value
    .replace(/[_-]+/g, " ")
    .replace(/\b\w/g, (char) => char.toUpperCase());
}

function tableTypeLabel(value: string | null | undefined) {
  if (value === "fact") return "Fact table";
  if (value === "dimension") return "Dimension table";
  if (value === "bridge") return "Bridge table";
  return humanize(value || "Not set");
}

function confidenceLabel(value: number | null | undefined) {
  const confidence = Number(value || 0);
  if (confidence >= 0.85) return "High";
  if (confidence >= 0.65) return "Medium";
  if (confidence > 0) return "Low";
  return "Not scored";
}

function sourceLabel(value: string | null | undefined) {
  return humanize(value || "source");
}

function parseFilters(value: string | null | undefined) {
  if (!value) return "";

  try {
    const parsed = JSON.parse(value);
    if (Array.isArray(parsed)) return parsed.join("\n");
  } catch {
    return value;
  }

  return value;
}
