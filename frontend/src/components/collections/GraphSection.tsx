import {
  useCallback,
  useEffect,
  useMemo,
  useState,
  type DragEvent,
  type PointerEvent as ReactPointerEvent,
} from "react";
import {
  Controls,
  Handle,
  MiniMap,
  Position,
  ReactFlow,
  ReactFlowProvider,
  applyNodeChanges,
  useReactFlow,
  type Connection,
  type Edge,
  type EdgeChange,
  type Node,
  type NodeChange,
  type NodeProps,
  type Viewport,
} from "@xyflow/react";
import {
  Braces,
  Calculator,
  Database,
  FunctionSquare,
  Loader2,
  Plus,
  Save,
  Sigma,
  Table2,
  Trash2,
  Workflow,
  X,
} from "lucide-react";
import { parse, stringify } from "yaml";

import { GraphRunner } from "@/components/collections/CalculationRunner";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { SelectMenu } from "@/components/ui/select-menu";
import { StateMessage } from "@/components/ui/state-message";
import { notify } from "@/components/ui/global-toast";
import { StructuredDataEditor } from "@/components/ui/structured-data-editor";
import {
  api,
  type CollectionGraph,
  type CollectionGraphLayout,
  type CollectionModelCatalog,
  type CollectionTable,
  type DataCollection,
} from "@/lib/api";
import { cn } from "@/lib/utils";
import { useTheme } from "@/config/theme-provider";
import { useUnsavedChanges } from "@/hooks/use-unsaved-changes";

type ResultKind = "scalar" | "table";
type GraphNodeType =
  | "value"
  | "formula"
  | "cube_query"
  | "aggregate_query"
  | "calculation_output";

type DefinitionNode = {
  id: string;
  type: GraphNodeType;
  [key: string]: unknown;
};

type GraphDefinition = {
  version: 1;
  name: string;
  description?: string;
  parameters?: { id: string; member: string }[];
  nodes: DefinitionNode[];
  outputs: Record<string, string>;
};

type StepNodeData = {
  label: string;
  nodeType: GraphNodeType;
  detail: string;
  resultKind: ResultKind;
  outputs: string[];
};

type StepFlowNode = Node<StepNodeData, "step">;

const nodeTypes = { step: StepNode };
const EMPTY_LAYOUT: CollectionGraphLayout = { version: 1, nodes: {} };
const MIN_INSPECTOR_WIDTH = 320;
const MAX_INSPECTOR_WIDTH = 960;

export function GraphSection({ collectionId }: { collectionId: number }) {
  return (
    <ReactFlowProvider>
      <GraphEditor collectionId={collectionId} />
    </ReactFlowProvider>
  );
}

function GraphEditor({ collectionId }: { collectionId: number }) {
  const { screenToFlowPosition } = useReactFlow<StepFlowNode, Edge>();
  const { theme } = useTheme();
  const [graph, setGraph] = useState<CollectionGraph | null>(null);
  const [collection, setCollection] = useState<DataCollection | null>(null);
  const [models, setModels] = useState<CollectionModelCatalog | null>(null);
  const [definition, setDefinition] = useState<GraphDefinition | null>(null);
  const [content, setContent] = useState("");
  const [savedContent, setSavedContent] = useState("");
  const [layout, setLayout] = useState<CollectionGraphLayout>(EMPTY_LAYOUT);
  const [savedLayout, setSavedLayout] =
    useState<CollectionGraphLayout>(EMPTY_LAYOUT);
  const [nodes, setNodes] = useState<StepFlowNode[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [yamlOpen, setYamlOpen] = useState(false);
  const [yamlDraft, setYamlDraft] = useState("");
  const [yamlError, setYamlError] = useState<string | null>(null);
  const [inspectorWidth, setInspectorWidth] = useState(384);

  const edges = useMemo(
    () => (definition ? definitionEdges(definition) : []),
    [definition],
  );
  const selected = definition?.nodes.find((node) => node.id === selectedId);
  const dirty =
    graph !== null &&
    (!graph.persisted ||
      content !== savedContent ||
      JSON.stringify(layout) !== JSON.stringify(savedLayout));

  useUnsavedChanges({
    dirty,
    title: "Discard App graph changes?",
    message: "Your unsaved graph and layout changes will be lost.",
  });

  useEffect(() => {
    let active = true;
    setLoading(true);
    setError(null);

    async function load() {
      try {
        const [nextGraph, nextModels, nextCollection] = await Promise.all([
          api.collections.graph(collectionId),
          api.collections.models(collectionId),
          api.collections.get(collectionId),
        ]);
        if (!active) return;

        const nextDefinition = parseDefinition(nextGraph.content);
        const nextLayout = withDefaultPositions(
          nextGraph.layout ?? EMPTY_LAYOUT,
          nextDefinition,
        );
        setGraph(nextGraph);
        setModels(nextModels);
        setCollection(nextCollection);
        setDefinition(nextDefinition);
        setContent(nextGraph.content);
        setSavedContent(nextGraph.content);
        setLayout(nextLayout);
        setSavedLayout(nextGraph.layout ?? EMPTY_LAYOUT);
        setNodes(flowNodes(nextDefinition, nextLayout));
        setYamlDraft(nextGraph.content);
        setSelectedId(null);
      } catch (err: any) {
        if (active) setError(err.message);
      } finally {
        if (active) setLoading(false);
      }
    }

    void load();
    return () => {
      active = false;
    };
  }, [collectionId]);

  useEffect(() => {
    if (!definition) return;
    setNodes(flowNodes(definition, layout));
  }, [definition]);

  const mutateDefinition = useCallback(
    (mutate: (current: GraphDefinition) => GraphDefinition) => {
      setDefinition((current) => {
        if (!current) return current;
        const next = mutate(current);
        const nextContent = stringify(next, { lineWidth: 0 });
        setContent(nextContent);
        setYamlDraft(nextContent);
        return next;
      });
    },
    [],
  );

  function updateNode(
    nodeId: string,
    update: (node: DefinitionNode) => DefinitionNode,
  ) {
    mutateDefinition((current) => ({
      ...current,
      nodes: current.nodes.map((node) =>
        node.id === nodeId ? update(node) : node,
      ),
    }));
  }

  function createNode(type: GraphNodeType, position: { x: number; y: number }) {
    if (!definition || type === "calculation_output") return;
    const id = uniqueNodeId(type, definition.nodes);
    const node = starterNode(type, id, models, collection?.tables ?? []);
    setLayout((current) => ({
      ...current,
      version: 1,
      nodes: { ...current.nodes, [id]: position },
    }));
    mutateDefinition((current) => ({
      ...current,
      nodes: [...current.nodes, node],
    }));
    setSelectedId(id);
  }

  function removeNodes(nodeIds: string[]) {
    const removed = new Set(nodeIds);
    mutateDefinition((current) => ({
      ...current,
      nodes: current.nodes
        .filter((node) => !removed.has(node.id))
        .map((node) => {
          if (node.type !== "formula") return node;
          return {
            ...node,
            inputs: Object.fromEntries(
              Object.entries(asRecord(node.inputs)).filter(
                ([, source]) => !removed.has(String(source)),
              ),
            ),
          };
        }),
      outputs: Object.fromEntries(
        Object.entries(current.outputs).filter(
          ([, nodeId]) => !removed.has(nodeId),
        ),
      ),
    }));
    setLayout((current) => ({
      ...current,
      version: 1,
      nodes: Object.fromEntries(
        Object.entries(current.nodes).filter(([id]) => !removed.has(id)),
      ),
    }));
    if (selectedId && removed.has(selectedId)) setSelectedId(null);
  }

  function connect(connection: Connection) {
    if (!connection.source || !connection.target || !definition) return;
    const target = definition.nodes.find(
      (node) => node.id === connection.target,
    );
    const source = definition.nodes.find(
      (node) => node.id === connection.source,
    );
    if (!target || !source || target.type !== "formula") return;
    if (nodeResultKind(source) !== "scalar") {
      setError("Table results cannot be connected to formula inputs.");
      return;
    }

    updateNode(target.id, (node) => {
      const inputs = asStringRecord(node.inputs);
      const inputName = uniqueInputName(inputs);
      return { ...node, inputs: { ...inputs, [inputName]: source.id } };
    });
  }

  function removeEdges(edgesToRemove: Edge[]) {
    const byTarget = new Map<string, Set<string>>();
    for (const edge of edgesToRemove) {
      const input = String(edge.data?.input ?? "");
      if (!input) continue;
      const inputs = byTarget.get(edge.target) ?? new Set<string>();
      inputs.add(input);
      byTarget.set(edge.target, inputs);
    }
    mutateDefinition((current) => ({
      ...current,
      nodes: current.nodes.map((node) => {
        const removed = byTarget.get(node.id);
        if (!removed || node.type !== "formula") return node;
        return {
          ...node,
          inputs: Object.fromEntries(
            Object.entries(asRecord(node.inputs)).filter(
              ([name]) => !removed.has(name),
            ),
          ),
        };
      }),
    }));
  }

  function handleNodeChanges(changes: NodeChange<StepFlowNode>[]) {
    setNodes((current) => applyNodeChanges(changes, current));

    const positionChanges = changes.filter(
      (
        change,
      ): change is Extract<NodeChange<StepFlowNode>, { type: "position" }> =>
        change.type === "position" && Boolean(change.position),
    );
    if (positionChanges.length) {
      setLayout((current) => ({
        ...current,
        version: 1,
        nodes: {
          ...current.nodes,
          ...Object.fromEntries(
            positionChanges.map((change) => [change.id, change.position!]),
          ),
        },
      }));
    }

    const removed = changes
      .filter((change) => change.type === "remove")
      .map((change) => change.id);
    if (removed.length) removeNodes(removed);
  }

  async function save() {
    if (!graph) return;
    setSaving(true);
    setError(null);
    try {
      const saved = await api.collections.saveGraph(collectionId, {
        content,
        layout,
        expected_revision: graph.revision,
      });
      setGraph(saved);
      setContent(saved.content);
      setSavedContent(saved.content);
      setLayout(saved.layout);
      setSavedLayout(saved.layout);
      notify.success("Graph saved.");
    } catch (err: any) {
      setError(err.message);
      notify.error(err.message);
    } finally {
      setSaving(false);
    }
  }

  function applyYaml() {
    try {
      const next = parseDefinition(yamlDraft);
      setDefinition(next);
      setContent(yamlDraft.trimEnd() + "\n");
      const nextLayout = withDefaultPositions(layout, next);
      setLayout(nextLayout);
      setNodes(flowNodes(next, nextLayout));
      setSelectedId(null);
      setYamlError(null);
      notify.info("YAML applied to the graph draft.");
    } catch (err: any) {
      setYamlError(err.message);
    }
  }

  function handleDrop(event: DragEvent<HTMLDivElement>) {
    event.preventDefault();
    const type = event.dataTransfer.getData(
      "application/settra-graph-node",
    ) as GraphNodeType;
    if (!type) return;
    createNode(
      type,
      screenToFlowPosition({ x: event.clientX, y: event.clientY }),
    );
  }

  function closeInspector() {
    setSelectedId(null);
    setNodes((current) =>
      current.map((node) =>
        node.selected ? { ...node, selected: false } : node,
      ),
    );
  }

  function resizeInspector(event: ReactPointerEvent<HTMLDivElement>) {
    if (event.button !== 0) return;
    event.preventDefault();

    const startX = event.clientX;
    const startWidth = inspectorWidth;
    const previousCursor = document.body.style.cursor;
    const previousUserSelect = document.body.style.userSelect;
    document.body.style.cursor = "col-resize";
    document.body.style.userSelect = "none";

    const stop = () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", stop);
      window.removeEventListener("pointercancel", stop);
      window.removeEventListener("blur", stop);
      document.body.style.cursor = previousCursor;
      document.body.style.userSelect = previousUserSelect;
    };
    const move = (moveEvent: PointerEvent) => {
      setInspectorWidth(
        clampInspectorWidth(startWidth + startX - moveEvent.clientX),
      );
    };

    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", stop);
    window.addEventListener("pointercancel", stop);
    window.addEventListener("blur", stop);
  }

  if (loading) {
    return (
      <StateMessage state="loading" variant="panel" message="Loading graph" />
    );
  }
  if (!graph || !definition) {
    return (
      <StateMessage
        state="error"
        variant="panel"
        message={error ?? "The App graph could not be loaded"}
      />
    );
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex min-h-8 items-center gap-2">
          <Badge variant="outline">{definition.nodes.length} steps</Badge>
          <Badge variant="outline">
            {Object.keys(definition.outputs).length} outputs
          </Badge>
          {dirty && <Badge variant="secondary">Unsaved</Badge>}
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Button
            type="button"
            variant="outline"
            onClick={() => {
              if (yamlOpen) {
                setYamlOpen(false);
                return;
              }
              setYamlDraft(content);
              setYamlError(null);
              setYamlOpen(true);
            }}
          >
            {yamlOpen ? (
              <Workflow className="size-4" />
            ) : (
              <Braces className="size-4" />
            )}
            {yamlOpen ? "Graph" : "YAML"}
          </Button>
          <GraphRunner
            collectionId={collectionId}
            content={content}
            disabled={saving}
          />
          <Button
            type="button"
            disabled={!dirty || saving}
            onClick={() => void save()}
          >
            {saving ? (
              <Loader2 className="size-4 animate-spin" />
            ) : (
              <Save className="size-4" />
            )}
          </Button>
        </div>
      </div>

      {error && (
        <StateMessage
          state="error"
          variant="banner"
          message={error}
          onClose={() => setError(null)}
        />
      )}
      {graph.import_warnings.map((warning) => (
        <StateMessage
          key={warning}
          state="warning"
          variant="banner"
          message={warning}
        />
      ))}
      {!graph.persisted && graph.legacy_calculation_count > 1 && (
        <StateMessage
          state="info"
          variant="banner"
          message={`${graph.legacy_calculation_count} existing calculation drafts were combined into this App graph. Review and save it to complete the import.`}
        />
      )}

      {yamlOpen ? (
        <section className="min-h-[42rem] rounded-lg border bg-card p-4">
          <div className="mb-3 flex items-center justify-between gap-3">
            <div>
              <h3 className="text-sm font-medium">Advanced YAML</h3>
              <p className="mt-1 text-xs text-muted-foreground">
                Apply the document to update the draft, then use Graph to return
                to the canvas. Saving remains a separate action.
              </p>
            </div>
            <Button type="button" size="sm" onClick={applyYaml}>
              Apply YAML
            </Button>
          </div>
          <StructuredDataEditor
            className="h-[36rem]"
            ariaLabel="App graph YAML"
            path={`collections/${collectionId}/graph.yaml`}
            value={yamlDraft}
            onChange={setYamlDraft}
          />
          {yamlError && (
            <p className="mt-2 text-sm text-destructive">{yamlError}</p>
          )}
        </section>
      ) : (
        <div className="h-[42rem]">
          <section className="flex h-full min-w-0 flex-col">
            <NodePalette canAggregate={Boolean(collection?.tables?.length)} />
            <div
              className="relative min-h-0 flex-1"
              onDragOver={(event) => {
                event.preventDefault();
                event.dataTransfer.dropEffect = "move";
              }}
              onDrop={handleDrop}
            >
              <ReactFlow<StepFlowNode, Edge>
                nodes={nodes}
                edges={edges}
                nodeTypes={nodeTypes}
                onNodesChange={handleNodeChanges}
                onEdgesChange={(changes: EdgeChange[]) => {
                  const removed = changes
                    .filter((change) => change.type === "remove")
                    .map((change) =>
                      edges.find((edge) => edge.id === change.id),
                    )
                    .filter((edge): edge is Edge => Boolean(edge));
                  if (removed.length) removeEdges(removed);
                }}
                onConnect={connect}
                onSelectionChange={({ nodes: selectedNodes }) =>
                  setSelectedId(selectedNodes[0]?.id ?? null)
                }
                onMoveEnd={(_event, viewport: Viewport) =>
                  setLayout((current) => ({
                    ...current,
                    viewport,
                  }))
                }
                onPaneClick={closeInspector}
                deleteKeyCode={["Backspace", "Delete"]}
                colorMode={theme}
                className="settra-graph"
                defaultViewport={layout.viewport}
                fitView={!layout.viewport}
                fitViewOptions={{ padding: 0.2, maxZoom: 1 }}
                minZoom={0.2}
                maxZoom={1.75}
                aria-label="App calculation graph"
              >
                <Controls showInteractive={false} />
                <MiniMap pannable zoomable />
              </ReactFlow>

              {selected && (
                <GraphInspector
                  node={selected}
                  definition={definition}
                  collectionId={collectionId}
                  content={content}
                  disabled={saving}
                  width={inspectorWidth}
                  onResize={resizeInspector}
                  onResizeBy={(amount) =>
                    setInspectorWidth((current) =>
                      clampInspectorWidth(current + amount),
                    )
                  }
                  onClose={closeInspector}
                  onUpdate={updateNode}
                  onDelete={(nodeId) => removeNodes([nodeId])}
                  onPublish={(nodeId, outputName) =>
                    mutateDefinition((current) => ({
                      ...current,
                      outputs: { ...current.outputs, [outputName]: nodeId },
                    }))
                  }
                  onRemoveOutput={(outputName) =>
                    mutateDefinition((current) => ({
                      ...current,
                      outputs: Object.fromEntries(
                        Object.entries(current.outputs).filter(
                          ([name]) => name !== outputName,
                        ),
                      ),
                    }))
                  }
                />
              )}
            </div>
          </section>
        </div>
      )}
    </div>
  );
}

function NodePalette({ canAggregate }: { canAggregate: boolean }) {
  const items: {
    type: GraphNodeType;
    label: string;
    icon: typeof Calculator;
    disabled?: boolean;
  }[] = [
    { type: "value", label: "Value", icon: Calculator },
    { type: "formula", label: "Formula", icon: FunctionSquare },
    { type: "cube_query", label: "Semantic query", icon: Database },
    {
      type: "aggregate_query",
      label: "Snapshot aggregation",
      icon: Table2,
      disabled: !canAggregate,
    },
  ];

  return (
    <div className="flex flex-wrap items-center gap-2 border-b p-3">
      {items.map((item) => {
        const Icon = item.icon;
        return (
          <Button
            key={item.type}
            type="button"
            variant="outline"
            size="sm"
            className="cursor-grab active:cursor-grabbing"
            draggable={!item.disabled}
            disabled={item.disabled}
            title={
              item.disabled
                ? "Add a synchronized table to this App first"
                : `Drag ${item.label} onto the graph`
            }
            onDragStart={(event) => {
              event.dataTransfer.setData(
                "application/settra-graph-node",
                item.type,
              );
              event.dataTransfer.effectAllowed = "move";
            }}
          >
            <Icon className="size-3.5" /> {item.label}
          </Button>
        );
      })}
    </div>
  );
}

function StepNode({ data, selected }: NodeProps<StepFlowNode>) {
  const Icon = nodeIcon(data.nodeType);
  return (
    <div
      className={cn(
        "min-w-52 rounded-lg border bg-card px-3 py-2.5 text-card-foreground shadow-sm",
        selected && "border-primary ring-2 ring-primary/20",
      )}
    >
      {data.nodeType === "formula" && (
        <Handle
          type="target"
          position={Position.Left}
          className="!size-3 !border-2 !border-background !bg-primary"
          aria-label={`Connect an input to ${data.label}`}
        />
      )}
      <div className="flex items-start gap-2">
        <Icon className="mt-0.5 size-4 shrink-0 text-muted-foreground" />
        <div className="min-w-0 flex-1">
          <p className="truncate text-sm font-medium">{data.label}</p>
          <p className="mt-0.5 truncate text-xs text-muted-foreground">
            {data.detail}
          </p>
        </div>
        <Badge variant="outline" className="shrink-0">
          {data.resultKind}
        </Badge>
      </div>
      {data.outputs.length > 0 && (
        <div className="mt-2 flex flex-wrap gap-1">
          {data.outputs.map((output) => (
            <Badge key={output} variant="secondary">
              {output}
            </Badge>
          ))}
        </div>
      )}
      <Handle
        type="source"
        position={Position.Right}
        className="!size-3 !border-2 !border-background !bg-primary"
        aria-label={`${data.label} result`}
      />
    </div>
  );
}

function GraphInspector({
  node,
  definition,
  collectionId,
  content,
  disabled,
  width,
  onResize,
  onResizeBy,
  onClose,
  onUpdate,
  onDelete,
  onPublish,
  onRemoveOutput,
}: {
  node: DefinitionNode;
  definition: GraphDefinition;
  collectionId: number;
  content: string;
  disabled: boolean;
  width: number;
  onResize: (event: ReactPointerEvent<HTMLDivElement>) => void;
  onResizeBy: (amount: number) => void;
  onClose: () => void;
  onUpdate: (
    nodeId: string,
    update: (node: DefinitionNode) => DefinitionNode,
  ) => void;
  onDelete: (nodeId: string) => void;
  onPublish: (nodeId: string, outputName: string) => void;
  onRemoveOutput: (outputName: string) => void;
}) {
  const [outputName, setOutputName] = useState("");

  useEffect(() => setOutputName(""), [node.id]);

  const outputs = Object.entries(definition.outputs)
    .filter(([, nodeId]) => nodeId === node.id)
    .map(([name]) => name);

  return (
    <aside
      className="fixed inset-y-0 right-0 z-[60] flex min-w-0 flex-col overflow-hidden border-l-2 border-primary/70 bg-card shadow-2xl"
      style={{ width: `min(${width}px, calc(100vw - 1rem))` }}
      aria-label={`Details for ${node.id}`}
    >
      <div
        role="separator"
        aria-label="Resize node details"
        aria-orientation="vertical"
        aria-valuemin={MIN_INSPECTOR_WIDTH}
        aria-valuemax={MAX_INSPECTOR_WIDTH}
        aria-valuenow={width}
        tabIndex={0}
        className="group absolute inset-y-0 left-0 z-20 w-3 -translate-x-1/2 cursor-col-resize touch-none outline-none"
        onPointerDown={onResize}
        onDoubleClick={() => onResizeBy(384 - width)}
        onKeyDown={(event) => {
          if (event.key === "ArrowLeft") {
            event.preventDefault();
            onResizeBy(32);
          } else if (event.key === "ArrowRight") {
            event.preventDefault();
            onResizeBy(-32);
          }
        }}
      >
        <span className="absolute inset-y-0 left-1/2 w-0.5 -translate-x-1/2 bg-primary/70 transition-all group-hover:w-1 group-hover:bg-primary group-focus-visible:w-1 group-focus-visible:bg-primary" />
        <span className="absolute top-1/2 left-1/2 h-14 w-1 -translate-x-1/2 -translate-y-1/2 rounded-full bg-primary shadow-[0_0_0_4px_color-mix(in_oklch,var(--primary)_18%,transparent)]" />
      </div>

      <div className="flex shrink-0 items-start justify-between gap-3 border-b p-4">
        <div className="min-w-0">
          <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
            {nodeTypeLabel(node.type)}
          </p>
          <h3 className="mt-1 break-words text-base font-semibold">
            {node.id}
          </h3>
        </div>
        <div className="flex shrink-0 items-center gap-1">
          <GraphRunner
            collectionId={collectionId}
            content={content}
            disabled={disabled}
            targetNodeId={node.id}
            buttonLabel="Run"
          />
          <Button
            type="button"
            variant="destructive"
            size="icon"
            aria-label={`Delete ${node.id}`}
            onClick={() => onDelete(node.id)}
          >
            <Trash2 className="size-4" />
          </Button>
          <Button
            type="button"
            variant="ghost"
            size="icon"
            aria-label="Close node details"
            onClick={onClose}
          >
            <X className="size-4" />
          </Button>
        </div>
      </div>

      <div className="min-h-0 flex-1 space-y-5 overflow-y-auto p-4">
        {node.type === "value" && (
          <label className="block space-y-2 text-sm font-medium">
            <span>Numeric value</span>
            <Input
              type="number"
              value={String(node.value ?? 0)}
              onChange={(event) => {
                const value = Number(event.target.value);
                if (!Number.isFinite(value)) return;
                onUpdate(node.id, (current) => ({ ...current, value }));
              }}
            />
          </label>
        )}

        {node.type === "formula" && (
          <>
            <label className="block space-y-2 text-sm font-medium">
              <span>Expression</span>
              <textarea
                className="min-h-24 w-full resize-y rounded-lg border bg-background p-2.5 font-mono text-xs outline-none focus-visible:ring-2 focus-visible:ring-ring"
                value={String(node.expression ?? "")}
                onChange={(event) =>
                  onUpdate(node.id, (current) => ({
                    ...current,
                    expression: event.target.value,
                  }))
                }
              />
            </label>
            <div>
              <p className="text-sm font-medium">Inputs</p>
              <div className="mt-2 space-y-2">
                {Object.entries(asStringRecord(node.inputs)).map(
                  ([name, source]) => (
                    <div
                      key={name}
                      className="flex items-center justify-between gap-2 text-xs"
                    >
                      <span className="min-w-0 truncate font-mono">
                        {name} {"<-"} {source}
                      </span>
                      <Button
                        type="button"
                        variant="ghost"
                        size="icon"
                        aria-label={`Remove input ${name}`}
                        onClick={() =>
                          onUpdate(node.id, (current) => ({
                            ...current,
                            inputs: Object.fromEntries(
                              Object.entries(asRecord(current.inputs)).filter(
                                ([inputName]) => inputName !== name,
                              ),
                            ),
                          }))
                        }
                      >
                        <Trash2 className="size-3.5" />
                      </Button>
                    </div>
                  ),
                )}
                {!Object.keys(asRecord(node.inputs)).length && (
                  <p className="text-xs text-muted-foreground">
                    Connect a scalar step to create an input.
                  </p>
                )}
              </div>
            </div>
          </>
        )}

        {(node.type === "cube_query" || node.type === "aggregate_query") && (
          <StructuredNodeEditor
            collectionId={collectionId}
            node={node}
            onUpdate={onUpdate}
          />
        )}

        {node.type === "calculation_output" && (
          <StateMessage
            state="info"
            variant="panel"
            message="This legacy calculation reference remains editable in YAML. New App graphs connect steps directly."
          />
        )}

        <div className="border-t pt-4">
          <p className="text-sm font-medium">Published outputs</p>
          <div className="mt-2 flex flex-wrap gap-1.5">
            {outputs.map((output) => (
              <button
                key={output}
                type="button"
                className="cursor-pointer"
                aria-label={`Remove output ${output}`}
                onClick={() => onRemoveOutput(output)}
              >
                <Badge variant="secondary">
                  {output} <span aria-hidden="true">×</span>
                </Badge>
              </button>
            ))}
            {!outputs.length && (
              <p className="text-xs text-muted-foreground">
                This step is not exposed as an App result.
              </p>
            )}
          </div>
          <div className="mt-3 flex gap-2">
            <Input
              value={outputName}
              placeholder="output_name"
              onChange={(event) => setOutputName(event.target.value)}
            />
            <Button
              type="button"
              variant="outline"
              size="icon"
              aria-label="Publish output"
              disabled={
                !validIdentifier(outputName) || outputName in definition.outputs
              }
              onClick={() => {
                onPublish(node.id, outputName);
                setOutputName("");
              }}
            >
              <Plus className="size-4" />
            </Button>
          </div>
        </div>
      </div>
    </aside>
  );
}

function clampInspectorWidth(value: number): number {
  const viewportLimit =
    typeof window === "undefined"
      ? MAX_INSPECTOR_WIDTH
      : Math.max(0, window.innerWidth - 16);
  const maximum = Math.min(MAX_INSPECTOR_WIDTH, viewportLimit);
  const minimum = Math.min(MIN_INSPECTOR_WIDTH, maximum);
  return Math.min(maximum, Math.max(minimum, value));
}

function StructuredNodeEditor({
  collectionId,
  node,
  onUpdate,
}: {
  collectionId: number;
  node: DefinitionNode;
  onUpdate: (
    nodeId: string,
    update: (node: DefinitionNode) => DefinitionNode,
  ) => void;
}) {
  const editable = Object.fromEntries(
    Object.entries(node).filter(([key]) => !["id", "type"].includes(key)),
  );
  const [draft, setDraft] = useState(() => JSON.stringify(editable, null, 2));
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setDraft(JSON.stringify(editable, null, 2));
    setError(null);
  }, [node.id]);

  return (
    <div>
      <div className="flex items-center justify-between gap-2">
        <p className="text-sm font-medium">Configuration</p>
        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={() => {
            try {
              const parsed = JSON.parse(draft);
              if (
                !parsed ||
                typeof parsed !== "object" ||
                Array.isArray(parsed)
              ) {
                throw new Error("Configuration must be an object");
              }
              if ("id" in parsed || "type" in parsed) {
                throw new Error(
                  "Configuration cannot include the reserved id or type fields.",
                );
              }
              onUpdate(node.id, () => ({
                ...parsed,
                id: node.id,
                type: node.type,
              }));
              setError(null);
            } catch (err: any) {
              setError(err.message);
            }
          }}
        >
          Apply
        </Button>
      </div>
      <StructuredDataEditor
        className="mt-2 h-64"
        language="json"
        ariaLabel={`${nodeTypeLabel(node.type)} configuration JSON`}
        path={`collections/${collectionId}/graph-nodes/${node.id}.json`}
        value={draft}
        onChange={setDraft}
      />
      {error && <p className="mt-2 text-xs text-destructive">{error}</p>}
    </div>
  );
}

function parseDefinition(content: string): GraphDefinition {
  const value = parse(content);
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new Error("Graph YAML must contain an object");
  }
  const candidate = value as Partial<GraphDefinition>;
  if (!Array.isArray(candidate.nodes)) {
    throw new Error("Graph YAML must contain a nodes list");
  }
  if (!candidate.outputs || typeof candidate.outputs !== "object") {
    throw new Error("Graph YAML must contain an outputs object");
  }
  return {
    version: 1,
    name: String(candidate.name || "app_graph"),
    description: String(candidate.description || ""),
    parameters: Array.isArray(candidate.parameters) ? candidate.parameters : [],
    nodes: candidate.nodes as DefinitionNode[],
    outputs: candidate.outputs as Record<string, string>,
  };
}

function definitionEdges(definition: GraphDefinition): Edge[] {
  return definition.nodes.flatMap((node) => {
    if (node.type !== "formula") return [];
    return Object.entries(asStringRecord(node.inputs)).map(
      ([input, source]) => ({
        id: `${source}--${node.id}--${input}`,
        source,
        target: node.id,
        type: "smoothstep",
        data: { input },
        label: input,
        ariaLabel: `${source} supplies ${input} to ${node.id}`,
        deletable: true,
      }),
    );
  });
}

function flowNodes(
  definition: GraphDefinition,
  layout: CollectionGraphLayout,
): StepFlowNode[] {
  return definition.nodes.map((node) => ({
    id: node.id,
    type: "step",
    position: layout.nodes[node.id] ?? { x: 0, y: 0 },
    data: {
      label: node.id,
      nodeType: node.type,
      detail: nodeDetail(node),
      resultKind: nodeResultKind(node),
      outputs: Object.entries(definition.outputs)
        .filter(([, nodeId]) => nodeId === node.id)
        .map(([name]) => name),
    },
    ariaLabel: `${nodeTypeLabel(node.type)} ${node.id}`,
  }));
}

function withDefaultPositions(
  layout: CollectionGraphLayout,
  definition: GraphDefinition,
): CollectionGraphLayout {
  const positions = { ...(layout?.nodes ?? {}) };
  const depths = nodeDepths(definition);
  const perDepth = new Map<number, number>();

  for (const node of definition.nodes) {
    if (positions[node.id]) continue;
    const depth = depths.get(node.id) ?? 0;
    const row = perDepth.get(depth) ?? 0;
    positions[node.id] = { x: 60 + depth * 290, y: 60 + row * 145 };
    perDepth.set(depth, row + 1);
  }
  return { ...layout, version: 1, nodes: positions };
}

function nodeDepths(definition: GraphDefinition): Map<string, number> {
  const nodes = new Map(definition.nodes.map((node) => [node.id, node]));
  const result = new Map<string, number>();
  const visiting = new Set<string>();

  function depth(nodeId: string): number {
    if (result.has(nodeId)) return result.get(nodeId)!;
    if (visiting.has(nodeId)) return 0;
    visiting.add(nodeId);
    const node = nodes.get(nodeId);
    const dependencies =
      node?.type === "formula"
        ? Object.values(asStringRecord(node.inputs))
        : [];
    const value = dependencies.length
      ? 1 + Math.max(...dependencies.map(depth))
      : 0;
    visiting.delete(nodeId);
    result.set(nodeId, value);
    return value;
  }

  definition.nodes.forEach((node) => depth(node.id));
  return result;
}

function starterNode(
  type: GraphNodeType,
  id: string,
  models: CollectionModelCatalog | null,
  tables: CollectionTable[],
): DefinitionNode {
  if (type === "value") return { id, type, value: 0 };
  if (type === "formula") {
    return { id, type, inputs: {}, expression: "value" };
  }
  if (type === "aggregate_query") {
    const table = tables[0];
    return {
      id,
      type,
      source: {
        connection: table?.pipe_slug ?? "select_source",
        table: table?.table ?? "select_table",
      },
      measures: [{ name: "row_count", function: "count" }],
      group_by: [],
      filters: [],
      result: { kind: "scalar", member: "row_count" },
    };
  }

  const model = models?.models.find((candidate) => candidate.compile.compiled);
  const measure = model?.meta.measures?.[0]?.name;
  const dimension = model?.meta.dimensions?.[0]?.name;
  if (measure) {
    return {
      id,
      type: "cube_query",
      query: { measures: [measure] },
      result: { kind: "scalar", member: measure },
    };
  }
  return {
    id,
    type: "cube_query",
    query: { dimensions: dimension ? [dimension] : [] },
    result: { kind: "table" },
  };
}

function nodeResultKind(node: DefinitionNode): ResultKind {
  if (node.type === "value" || node.type === "formula") return "scalar";
  const result = asRecord(node.result);
  return result.kind === "scalar" ? "scalar" : "table";
}

function nodeDetail(node: DefinitionNode): string {
  if (node.type === "value") return `Value ${String(node.value ?? 0)}`;
  if (node.type === "formula") return String(node.expression || "Formula");
  if (node.type === "cube_query") {
    const query = asRecord(node.query);
    const selected = [
      ...(Array.isArray(query.measures) ? query.measures : []),
      ...(Array.isArray(query.dimensions) ? query.dimensions : []),
    ];
    return selected.length ? String(selected[0]) : "Configure query";
  }
  if (node.type === "aggregate_query") {
    const source = asRecord(node.source);
    return `${String(source.connection || "source")} · ${String(source.table || "table")}`;
  }
  return `${String(node.calculation || "calculation")} · ${String(node.output || "output")}`;
}

function nodeIcon(type: GraphNodeType) {
  if (type === "value") return Calculator;
  if (type === "formula") return FunctionSquare;
  if (type === "cube_query") return Database;
  if (type === "aggregate_query") return Table2;
  return Sigma;
}

function nodeTypeLabel(type: GraphNodeType): string {
  return {
    value: "Value",
    formula: "Formula",
    cube_query: "Semantic query",
    aggregate_query: "Snapshot aggregation",
    calculation_output: "Legacy calculation output",
  }[type];
}

function uniqueNodeId(type: GraphNodeType, nodes: DefinitionNode[]): string {
  const base = {
    value: "value",
    formula: "formula",
    cube_query: "semantic_query",
    aggregate_query: "snapshot_aggregation",
    calculation_output: "calculation_output",
  }[type];
  const used = new Set(nodes.map((node) => node.id));
  let index = 1;
  while (used.has(`${base}_${index}`)) index += 1;
  return `${base}_${index}`;
}

function uniqueInputName(inputs: Record<string, string>): string {
  if (!("value" in inputs)) return "value";
  let index = 2;
  while (`value_${index}` in inputs) index += 1;
  return `value_${index}`;
}

function validIdentifier(value: string): boolean {
  return /^[A-Za-z][A-Za-z0-9_-]{0,63}$/.test(value);
}

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
}

function asStringRecord(value: unknown): Record<string, string> {
  return Object.fromEntries(
    Object.entries(asRecord(value)).map(([key, item]) => [key, String(item)]),
  );
}
