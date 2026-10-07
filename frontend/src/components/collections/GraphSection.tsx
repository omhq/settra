import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type DragEvent,
  type PointerEvent as ReactPointerEvent,
} from "react";
import {
  Background,
  BackgroundVariant,
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

import { GraphRunner } from "@/components/collections/GraphRunner";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { SelectMenu } from "@/components/ui/select-menu";
import { StateMessage } from "@/components/ui/state-message";
import { notify } from "@/components/ui/global-toast";
import { useModal } from "@/components/ui/global-modal";
import { StructuredDataEditor } from "@/components/ui/structured-data-editor";
import {
  api,
  type CollectionGraph,
  type CollectionGraphLayout,
  type CollectionModelCatalog,
  type CollectionSemanticModel,
  type CollectionTable,
  type CubeMetaMember,
  type CubeSourceDefinition,
  type CubeSourceMemberDefinition,
  type DataCollection,
} from "@/lib/api";
import { cn } from "@/lib/utils";
import { useTheme } from "@/config/theme-provider";
import { useUnsavedChanges } from "@/hooks/use-unsaved-changes";
import { useWorkspaceChange } from "@/realtime/workspace-events";

type ResultKind = "scalar" | "table";
type GraphNodeType = "value" | "formula" | "cube_query" | "aggregate_query";

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
  const { openModal } = useModal();
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
  const [reloadVersion, setReloadVersion] = useState(0);
  const [reconcileVersion, setReconcileVersion] = useState(0);
  const [supportReloadVersion, setSupportReloadVersion] = useState(0);
  const [remoteChange, setRemoteChange] = useState(false);

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
  const liveGraphState = useRef({ graph, dirty, saving });
  liveGraphState.current = { graph, dirty, saving };

  const applyGraph = useCallback((nextGraph: CollectionGraph) => {
    const nextDefinition = parseDefinition(nextGraph.content);
    const nextLayout = withDefaultPositions(
      nextGraph.layout ?? EMPTY_LAYOUT,
      nextDefinition,
    );
    setGraph(nextGraph);
    setDefinition(nextDefinition);
    setContent(nextGraph.content);
    setSavedContent(nextGraph.content);
    setLayout(nextLayout);
    setSavedLayout(nextGraph.layout ?? EMPTY_LAYOUT);
    setNodes(flowNodes(nextDefinition, nextLayout));
    setYamlDraft(nextGraph.content);
    setSelectedId(null);
    setRemoteChange(false);
  }, []);

  useUnsavedChanges({
    dirty,
    title: "Discard analysis changes?",
    message: "Your unsaved analysis steps and layout changes will be lost.",
  });

  useWorkspaceChange(
    ["artifact_graphs", "artifacts", "connections", "semantic_models"],
    (event) => {
      if (event.artifact_id !== null && event.artifact_id !== collectionId) {
        return;
      }
      if (event.action === "transport_ready") {
        setSupportReloadVersion((current) => current + 1);
        if (graph !== null && !dirty && !saving) {
          setReconcileVersion((current) => current + 1);
        }
        return;
      }
      if (event.action === "resync") {
        setSupportReloadVersion((current) => current + 1);
        if (dirty || saving) {
          setRemoteChange(true);
        } else {
          setReloadVersion((current) => current + 1);
        }
        return;
      }
      if (!event.resources.includes("artifact_graphs")) {
        setSupportReloadVersion((current) => current + 1);
        return;
      }
      if (
        event.revision !== null &&
        graph !== null &&
        event.revision <= graph.revision
      ) {
        return;
      }
      if (dirty || saving) {
        setRemoteChange(true);
        return;
      }
      setReloadVersion((current) => current + 1);
    },
  );

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

        setModels(nextModels);
        setCollection(nextCollection);
        applyGraph(nextGraph);
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
  }, [applyGraph, collectionId, reloadVersion]);

  useEffect(() => {
    if (reconcileVersion === 0) return;
    let active = true;

    api.collections
      .graph(collectionId)
      .then((nextGraph) => {
        if (!active) return;
        const current = liveGraphState.current;
        if (
          current.graph === null ||
          nextGraph.revision <= current.graph.revision
        ) {
          return;
        }
        if (current.dirty || current.saving) {
          setRemoteChange(true);
          return;
        }
        applyGraph(nextGraph);
      })
      .catch(() => undefined);

    return () => {
      active = false;
    };
  }, [applyGraph, collectionId, reconcileVersion]);

  useEffect(() => {
    if (supportReloadVersion === 0) return;
    let active = true;

    Promise.all([
      api.collections.models(collectionId),
      api.collections.get(collectionId),
    ])
      .then(([nextModels, nextCollection]) => {
        if (!active) return;
        setModels(nextModels);
        setCollection(nextCollection);
      })
      .catch((err) => {
        if (active) setError(err.message);
      });

    return () => {
      active = false;
    };
  }, [collectionId, supportReloadVersion]);

  useEffect(() => {
    if (!definition) return;
    setNodes(flowNodes(definition, layout, models));
  }, [definition, models]);

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

  function renameNode(nodeId: string, requestedId: string) {
    const nextId = requestedId.trim();
    if (
      !definition ||
      nextId === nodeId ||
      !validIdentifier(nextId) ||
      definition.nodes.some((node) => node.id === nextId)
    ) {
      return;
    }

    mutateDefinition((current) => ({
      ...current,
      nodes: current.nodes.map((node) => {
        const renamed = node.id === nodeId ? { ...node, id: nextId } : node;
        if (renamed.type !== "formula") return renamed;
        return {
          ...renamed,
          inputs: Object.fromEntries(
            Object.entries(asStringRecord(renamed.inputs)).map(
              ([name, source]) => [name, source === nodeId ? nextId : source],
            ),
          ),
        };
      }),
      outputs: Object.fromEntries(
        Object.entries(current.outputs).map(([name, target]) => [
          name,
          target === nodeId ? nextId : target,
        ]),
      ),
    }));
    setLayout((current) => {
      if (!current.nodes[nodeId]) return current;
      return {
        ...current,
        version: 1,
        nodes: Object.fromEntries(
          Object.entries(current.nodes).map(([id, position]) => [
            id === nodeId ? nextId : id,
            position,
          ]),
        ),
      };
    });
    setSelectedId(nextId);
  }

  function createNode(type: GraphNodeType, position: { x: number; y: number }) {
    if (!definition) return;
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
      setRemoteChange(false);
      notify.success("Analysis saved.");
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
      notify.info("Definition applied to the analysis draft.");
    } catch (err: any) {
      setYamlError(err.message);
    }
  }

  function confirmReload() {
    if (!dirty) {
      setReloadVersion((current) => current + 1);
      return;
    }
    openModal({
      title: "Load the latest analysis?",
      body: (
        <p>Your unsaved analysis steps and layout changes will be discarded.</p>
      ),
      actions: ({ close }) => (
        <>
          <Button variant="outline" onClick={close}>
            Keep editing
          </Button>
          <Button
            variant="destructive"
            onClick={() => {
              close();
              setReloadVersion((current) => current + 1);
            }}
          >
            Discard and load
          </Button>
        </>
      ),
    });
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
      <StateMessage
        state="loading"
        variant="panel"
        message="Loading analysis"
      />
    );
  }
  if (!graph || !definition) {
    return (
      <StateMessage
        state="error"
        variant="panel"
        message={error ?? "The artifact analysis could not be loaded"}
      />
    );
  }

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0 max-w-3xl">
          <div className="flex flex-wrap items-center gap-2">
            <h2 className="text-xl font-semibold tracking-[-0.02em]">
              {analysisTitle(definition, collection)}
            </h2>
            {dirty && <Badge variant="secondary">Unsaved</Badge>}
          </div>
          <p className="mt-1.5 text-sm leading-6 text-muted-foreground">
            {definition.description ||
              "Define the inputs, steps, and results that make this artifact reusable."}
          </p>
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
            {yamlOpen ? "Canvas" : "Definition"}
          </Button>
          <GraphRunner
            collectionId={collectionId}
            content={content}
            disabled={saving}
            buttonLabel="Run analysis"
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
            Save
          </Button>
        </div>
      </div>

      <div className="grid overflow-hidden border-y md:grid-cols-3 md:divide-x">
        <AnalysisSummary
          label="Inputs"
          values={(definition.parameters ?? []).map((parameter) =>
            humanizeIdentifier(parameter.id),
          )}
          empty="No inputs"
        />
        <AnalysisSummary
          label="Steps"
          values={definition.nodes.map((node) => humanizeIdentifier(node.id))}
          empty="No steps"
        />
        <AnalysisSummary
          label="Results"
          values={Object.keys(definition.outputs).map(humanizeIdentifier)}
          empty="No published results"
        />
      </div>

      {error && (
        <StateMessage
          state="error"
          variant="banner"
          message={error}
          onClose={() => setError(null)}
        />
      )}
      {remoteChange && (
        <StateMessage
          state="warning"
          variant="banner"
          message="This analysis changed elsewhere. Your draft is preserved; load the latest version before continuing."
          action={
            <Button type="button" variant="outline" onClick={confirmReload}>
              Load latest
            </Button>
          }
        />
      )}
      {yamlOpen ? (
        <section className="min-h-[42rem] rounded-lg border bg-card p-4">
          <div className="mb-3 flex items-center justify-between gap-3">
            <div>
              <h3 className="text-sm font-medium">Advanced YAML</h3>
              <p className="mt-1 text-xs text-muted-foreground">
                Apply the document to update the draft, then return to the
                canvas. Saving remains a separate action.
              </p>
            </div>
            <Button type="button" size="sm" onClick={applyYaml}>
              Apply YAML
            </Button>
          </div>
          <StructuredDataEditor
            className="h-[36rem]"
            ariaLabel="Artifact analysis definition YAML"
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
                aria-label="Artifact analysis steps"
              >
                <Background
                  variant={BackgroundVariant.Dots}
                  gap={24}
                  size={1.5}
                  color="color-mix(in oklch, var(--foreground) 24%, transparent)"
                />
                <Controls showInteractive={false} />
                <MiniMap pannable zoomable />
              </ReactFlow>

              {selected && (
                <GraphInspector
                  node={selected}
                  definition={definition}
                  models={models}
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
                  onRename={renameNode}
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

function AnalysisSummary({
  label,
  values,
  empty,
}: {
  label: string;
  values: string[];
  empty: string;
}) {
  return (
    <div className="min-w-0 border-b px-4 py-3 last:border-b-0 md:border-b-0">
      <div className="flex items-center justify-between gap-3">
        <p className="text-sm font-medium">{label}</p>
        <span className="text-xs tabular-nums text-muted-foreground">
          {values.length}
        </span>
      </div>
      <p className="mt-1 truncate text-xs text-muted-foreground">
        {values.length ? values.join(" · ") : empty}
      </p>
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
    <div className="space-y-2 border-b p-3">
      <div className="flex flex-wrap items-center gap-2">
        {items.map((item) => {
          const Icon = item.icon;
          return (
            <Button
              key={item.type}
              type="button"
              variant="outline"
              size="sm"
              className="!cursor-grab active:!cursor-grabbing"
              draggable={!item.disabled}
              disabled={item.disabled}
              title={
                item.disabled
                  ? "Add a synchronized table to this artifact first"
                  : `Drag ${item.label} onto the analysis canvas`
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
      <p className="text-xs text-muted-foreground">
        Drag a step onto the analysis. Table is a result shape, not a separate
        step: use Semantic query or Snapshot aggregation, then set{" "}
        <code>result.kind</code> to table in Configuration.
      </p>
    </div>
  );
}

function StepNode({ data, selected }: NodeProps<StepFlowNode>) {
  const Icon = nodeIcon(data.nodeType);
  const typeLabel = nodeTypeLabel(data.nodeType);
  return (
    <div
      className={cn(
        "min-w-52 rounded-2xl border-[2.5px] bg-card px-3 py-2.5 text-card-foreground shadow-sm",
        selected && "border-[3px] border-primary ring-2 ring-primary/20",
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
          <p className="mt-1 text-[11px] text-muted-foreground">
            {data.resultKind === "table" ? "Table" : "Scalar"} result
          </p>
        </div>
        <Badge variant="outline" className="shrink-0">
          {typeLabel}
        </Badge>
      </div>
      {data.outputs.length > 0 && (
        <div className="mt-2 flex flex-wrap gap-1">
          {data.outputs.map((output) => (
            <Badge key={output} variant="secondary">
              {humanizeIdentifier(output)}
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
  models,
  collectionId,
  content,
  disabled,
  width,
  onResize,
  onResizeBy,
  onClose,
  onUpdate,
  onRename,
  onDelete,
  onPublish,
  onRemoveOutput,
}: {
  node: DefinitionNode;
  definition: GraphDefinition;
  models: CollectionModelCatalog | null;
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
  onRename: (nodeId: string, nextId: string) => void;
  onDelete: (nodeId: string) => void;
  onPublish: (nodeId: string, outputName: string) => void;
  onRemoveOutput: (outputName: string) => void;
}) {
  const [outputName, setOutputName] = useState("");
  const [nodeName, setNodeName] = useState(node.id);
  const [editingName, setEditingName] = useState(false);

  useEffect(() => {
    setOutputName("");
    setNodeName(node.id);
    setEditingName(false);
  }, [node.id]);

  const normalizedNodeName = nodeName.trim();
  const nodeNameError =
    normalizedNodeName === node.id
      ? null
      : !validIdentifier(normalizedNodeName)
        ? "Start with a letter and use at most 64 letters, numbers, underscores, or hyphens."
        : definition.nodes.some(
              (candidate) => candidate.id === normalizedNodeName,
            )
          ? "Another step already uses this name."
          : null;

  function commitNodeName() {
    if (nodeNameError) return;
    if (normalizedNodeName !== node.id) {
      onRename(node.id, normalizedNodeName);
    }
    setEditingName(false);
  }

  function startEditingName() {
    if (disabled) return;
    setNodeName(node.id);
    setEditingName(true);
  }

  const outputs = Object.entries(definition.outputs)
    .filter(([, nodeId]) => nodeId === node.id)
    .map(([name]) => name);

  return (
    <aside
      className="fixed inset-y-0 right-0 z-[60] flex min-w-0 flex-col overflow-hidden border-l-2 border-primary/70 bg-card shadow-2xl"
      style={{ width: `min(${width}px, calc(100vw - 1rem))` }}
      aria-label={`Details for ${humanizeIdentifier(node.id)}`}
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

      <div className="flex shrink-0 items-center justify-between gap-3 border-b p-4">
        <div className="min-w-0 flex-1">
          {editingName ? (
            <>
              <Input
                autoFocus
                value={nodeName}
                aria-label="Step name"
                aria-invalid={nodeNameError ? true : undefined}
                aria-describedby={
                  nodeNameError ? "graph-step-name-error" : undefined
                }
                disabled={disabled}
                className="h-8 font-semibold"
                onFocus={(event) => event.currentTarget.select()}
                onChange={(event) => setNodeName(event.target.value)}
                onBlur={() => {
                  if (!nodeNameError) commitNodeName();
                }}
                onKeyDown={(event) => {
                  if (event.key === "Enter") {
                    event.preventDefault();
                    commitNodeName();
                  } else if (event.key === "Escape") {
                    setNodeName(node.id);
                    setEditingName(false);
                  }
                }}
              />
              {nodeNameError && (
                <p
                  id="graph-step-name-error"
                  role="alert"
                  className="mt-1.5 text-xs text-destructive"
                >
                  {nodeNameError}
                </p>
              )}
            </>
          ) : (
            <h3 className="break-words text-base font-semibold">
              <button
                type="button"
                className="cursor-text rounded-sm text-left outline-none hover:underline hover:underline-offset-4 focus-visible:ring-2 focus-visible:ring-ring"
                title="Double-click to rename"
                aria-label={`Rename step ${humanizeIdentifier(node.id)}`}
                disabled={disabled}
                onDoubleClick={startEditingName}
                onKeyDown={(event) => {
                  if (event.key === "Enter" || event.key === "F2") {
                    event.preventDefault();
                    startEditingName();
                  }
                }}
              >
                {humanizeIdentifier(node.id)}
              </button>
            </h3>
          )}
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
            aria-label={`Delete ${humanizeIdentifier(node.id)}`}
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

        {node.type === "cube_query" && (
          <SemanticDefinitions node={node} models={models} />
        )}

        {(node.type === "cube_query" || node.type === "aggregate_query") && (
          <StructuredNodeEditor
            collectionId={collectionId}
            node={node}
            onUpdate={onUpdate}
          />
        )}

        <div className="border-t pt-4">
          <p className="text-sm font-medium">Results</p>
          <div className="mt-2 flex flex-wrap gap-1.5">
            {outputs.map((output) => (
              <button
                key={output}
                type="button"
                className="cursor-pointer"
                aria-label={`Remove result ${output}`}
                onClick={() => onRemoveOutput(output)}
              >
                <Badge variant="secondary">
                  {humanizeIdentifier(output)} <span aria-hidden="true">×</span>
                </Badge>
              </button>
            ))}
            {!outputs.length && (
              <p className="text-xs text-muted-foreground">
                This step is not published as an artifact result.
              </p>
            )}
          </div>
          <div className="mt-3 flex gap-2">
            <Input
              value={outputName}
              placeholder="result_name"
              onChange={(event) => setOutputName(event.target.value)}
            />
            <Button
              type="button"
              variant="outline"
              size="icon"
              aria-label="Publish result"
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

type SemanticMemberKind = "measure" | "dimension" | "segment";

type SemanticMemberReference = {
  key: string;
  title: string;
  description?: string;
  kind: SemanticMemberKind;
  localName: string;
  sql?: string | null;
  aggregation?: string;
  modelTitle: string;
  purpose?: string;
};

function SemanticDefinitions({
  node,
  models,
}: {
  node: DefinitionNode;
  models: CollectionModelCatalog | null;
}) {
  const references = semanticQueryMembers(node, models);
  const query = asRecord(node.query);
  const maximumRows =
    typeof query.limit === "number" && Number.isFinite(query.limit)
      ? query.limit
      : null;

  if (!references.length) return null;

  return (
    <section>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="text-sm font-medium">Business definitions</p>
          <p className="mt-1 text-xs leading-5 text-muted-foreground">
            The saved semantic rules this step executes.
          </p>
          {maximumRows !== null && (
            <p className="mt-1 text-xs leading-5 text-muted-foreground">
              This step returns up to {maximumRows} rows to keep reusable runs
              bounded.
            </p>
          )}
        </div>
        {maximumRows !== null && (
          <Badge variant="outline">Maximum {maximumRows} rows</Badge>
        )}
      </div>
      <div className="mt-3 border-y">
        {references.map((reference) => {
          const formula = semanticFormula(reference);

          return (
            <article
              key={reference.key}
              className="border-b py-4 last:border-b-0"
            >
              <div className="flex flex-wrap items-start justify-between gap-2">
                <div className="min-w-0">
                  <p className="break-words text-sm font-medium">
                    {reference.title}
                  </p>
                  {reference.description && (
                    <p className="mt-1 text-xs leading-5 text-muted-foreground">
                      {reference.description}
                    </p>
                  )}
                </div>
                <Badge variant="secondary">
                  {humanizeIdentifier(reference.kind)}
                </Badge>
              </div>
              {formula && (
                <div className="mt-3">
                  <p className="text-xs font-medium text-muted-foreground">
                    Formula
                  </p>
                  <pre className="mt-1 max-h-52 overflow-auto whitespace-pre-wrap border-l pl-3 font-mono text-[11px] leading-5 text-foreground">
                    {formula}
                  </pre>
                </div>
              )}
              <dl className="mt-3 grid gap-x-3 gap-y-1 text-xs sm:grid-cols-[auto_1fr]">
                <dt className="text-muted-foreground">Semantic model</dt>
                <dd>{reference.modelTitle}</dd>
                {reference.purpose && (
                  <>
                    <dt className="text-muted-foreground">Purpose</dt>
                    <dd>{reference.purpose}</dd>
                  </>
                )}
              </dl>
            </article>
          );
        })}
      </div>
    </section>
  );
}

function semanticQueryMembers(
  node: DefinitionNode,
  models: CollectionModelCatalog | null,
): SemanticMemberReference[] {
  if (!models || node.type !== "cube_query") return [];

  const query = asRecord(node.query);
  const requested: { name: string; kind?: SemanticMemberKind }[] = [];

  for (const [field, kind] of [
    ["measures", "measure"],
    ["dimensions", "dimension"],
    ["segments", "segment"],
  ] as const) {
    const values = query[field];

    if (!Array.isArray(values)) continue;

    for (const value of values) {
      if (typeof value === "string") requested.push({ name: value, kind });
    }
  }

  if (Array.isArray(query.filters)) {
    for (const filter of query.filters) {
      const member = asRecord(filter).member;

      if (typeof member === "string") requested.push({ name: member });
    }
  }

  const resolved = new Map<string, SemanticMemberReference>();

  for (const item of requested) {
    const reference = semanticMember(item.name, models, item.kind);

    if (reference) resolved.set(reference.key, reference);
  }

  return [...resolved.values()];
}

function semanticMember(
  name: string,
  models: CollectionModelCatalog | null,
  preferredKind?: SemanticMemberKind,
): SemanticMemberReference | null {
  if (!models) return null;

  const model = [...models.models]
    .sort((left, right) => right.name.length - left.name.length)
    .find((candidate) => name.startsWith(`${candidate.name}.`));

  if (!model) return null;

  const localName = name.slice(model.name.length + 1);
  const kinds: SemanticMemberKind[] = preferredKind
    ? [preferredKind]
    : ["measure", "dimension", "segment"];

  for (const kind of kinds) {
    const member = semanticMemberList(model, kind).find(
      (candidate) =>
        candidate.name === name ||
        localMemberName(candidate.name) === localName,
    );

    if (!member) continue;

    const source = models.source_definitions[model.name];
    const definition = semanticSourceMembers(source, kind)?.[localName];
    const manifest = semanticManifest(model);
    const purpose = semanticPurpose(manifest.purpose);
    const aggregation =
      cleanText(member.aggType) ||
      (kind === "measure" ? cleanText(member.type) : undefined);

    return {
      key: `${kind}:${name}`,
      title: semanticMemberTitle(member),
      description: cleanText(member.description),
      kind,
      localName,
      sql: definition?.sql,
      aggregation,
      modelTitle: cleanText(model.meta.title) || humanizeIdentifier(model.name),
      purpose,
    };
  }

  return null;
}

function semanticMemberList(
  model: CollectionSemanticModel,
  kind: SemanticMemberKind,
): CubeMetaMember[] {
  if (kind === "measure") return model.meta.measures ?? [];
  if (kind === "dimension") return model.meta.dimensions ?? [];
  return model.meta.segments ?? [];
}

function semanticSourceMembers(
  source: CubeSourceDefinition | undefined,
  kind: SemanticMemberKind,
): Record<string, CubeSourceMemberDefinition> | undefined {
  if (!source) return undefined;
  if (kind === "measure") return source.measures;
  if (kind === "dimension") return source.dimensions;
  return source.segments;
}

function semanticManifest(
  model: CollectionSemanticModel,
): Record<string, unknown> {
  const settra = asRecord(asRecord(model.meta.meta).settra);
  const overlay = asRecord(settra.overlay);

  return Object.keys(overlay).length ? overlay : settra;
}

function semanticFormula(reference: SemanticMemberReference): string | null {
  const sql = cleanText(reference.sql);
  const aggregation = reference.aggregation?.toLowerCase();

  if (!sql) {
    return aggregation === "count" ? "COUNT(*)" : null;
  }
  if (
    reference.kind !== "measure" &&
    isDirectColumnMapping(sql, reference.localName)
  ) {
    return null;
  }
  if (
    reference.kind === "measure" &&
    aggregation &&
    !["number", "string", "boolean", "time"].includes(aggregation)
  ) {
    return `${aggregation.toUpperCase()}(\n  ${sql}\n)`;
  }

  return sql;
}

function semanticMemberTitle(member: CubeMetaMember): string {
  return (
    cleanText(member.shortTitle) ||
    cleanText(member.title) ||
    humanizeIdentifier(localMemberName(member.name))
  );
}

function semanticPurpose(value: unknown): string | undefined {
  const purpose = cleanText(value);

  if (
    !purpose ||
    purpose.startsWith("Relationships for ") ||
    purpose.startsWith("Semantic definitions for ")
  ) {
    return undefined;
  }

  return purpose;
}

function isDirectColumnMapping(sql: string, memberName: string): boolean {
  const expression = sql.trim().replace(/^\{CUBE\}\./, "");

  return expression === memberName || expression === `"${memberName}"`;
}

function localMemberName(name: string): string {
  return name.split(".").pop() ?? name;
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
        <div>
          <p className="text-sm font-medium">Advanced configuration</p>
          <p className="mt-1 text-xs text-muted-foreground">
            Edit the complete query definition when the visual summary is not
            enough.
          </p>
        </div>
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
    throw new Error("Analysis definition must contain an object");
  }
  const candidate = value as Partial<GraphDefinition>;
  if (!Array.isArray(candidate.nodes)) {
    throw new Error("Analysis definition must contain a steps list");
  }
  if (!candidate.outputs || typeof candidate.outputs !== "object") {
    throw new Error("Analysis definition must contain a results object");
  }
  return {
    version: 1,
    name: String(candidate.name || "artifact_graph"),
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
        type: "default",
        style: { strokeWidth: 4 },
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
  models: CollectionModelCatalog | null = null,
): StepFlowNode[] {
  return definition.nodes.map((node) => ({
    id: node.id,
    type: "step",
    position: layout.nodes[node.id] ?? { x: 0, y: 0 },
    data: {
      label: humanizeIdentifier(node.id),
      nodeType: node.type,
      detail: nodeDetail(node, models),
      resultKind: nodeResultKind(node),
      outputs: Object.entries(definition.outputs)
        .filter(([, nodeId]) => nodeId === node.id)
        .map(([name]) => name),
    },
    ariaLabel: `${nodeTypeLabel(node.type)} ${humanizeIdentifier(node.id)}`,
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

function nodeDetail(
  node: DefinitionNode,
  models: CollectionModelCatalog | null,
): string {
  if (node.type === "value") return `Value ${String(node.value ?? 0)}`;
  if (node.type === "formula") return String(node.expression || "Formula");
  if (node.type === "cube_query") {
    const query = asRecord(node.query);
    const selected = [
      ...(Array.isArray(query.measures) ? query.measures : []),
      ...(Array.isArray(query.dimensions) ? query.dimensions : []),
    ];
    const member = selected.length ? String(selected[0]) : null;
    const definition = member ? semanticMember(member, models) : null;

    return definition?.title ?? member ?? "Configure query";
  }
  if (node.type === "aggregate_query") {
    const source = asRecord(node.source);
    return `${String(source.connection || "source")} · ${String(source.table || "table")}`;
  }
  return "Configure step";
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
  }[type];
}

function uniqueNodeId(type: GraphNodeType, nodes: DefinitionNode[]): string {
  const base = {
    value: "value",
    formula: "formula",
    cube_query: "semantic_query",
    aggregate_query: "snapshot_aggregation",
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

function analysisTitle(
  definition: GraphDefinition,
  collection: DataCollection | null,
): string {
  const name = definition.name.trim();

  if (!name || name === "artifact_graph" || name === collection?.slug) {
    return collection?.name || "Artifact analysis";
  }

  return humanizeIdentifier(name);
}

function humanizeIdentifier(value: string): string {
  return value
    .replace(/[_-]+/g, " ")
    .replace(/\s+/g, " ")
    .trim()
    .replace(/\b\w/g, (character) => character.toUpperCase())
    .replace(/\bId\b/g, "ID")
    .replace(/\bUsd\b/g, "USD");
}

function cleanText(value: unknown): string | undefined {
  if (typeof value !== "string") return undefined;

  return value.trim() || undefined;
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
