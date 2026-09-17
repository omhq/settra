import { useEffect, useState, type ReactNode } from "react";
import { ArrowLeft, Copy, Database, Pencil, Rows3, Trash2 } from "lucide-react";
import {
  useLocation,
  useNavigate,
  useParams,
  useSearchParams,
} from "react-router-dom";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { useModal } from "@/components/ui/global-modal";
import { ItemCard, ItemGrid } from "@/components/ui/item-grid";
import { RowActions } from "@/components/ui/row-actions";
import { StateMessage } from "@/components/ui/state-message";
import { Timestamp } from "@/components/ui/timestamp";
import { cn } from "@/lib/utils";
import { useDeploymentMode } from "@/config/product-provider";
import CalculationsPage from "@/pages/CalculationsPage";
import { RelationshipsSection } from "@/components/collections/RelationshipsSection";
import { ModelsSection } from "@/components/collections/ModelsSection";
import { TableInspector } from "@/components/collections/TableInspector";
import { DependencyImpactSummary } from "@/components/collections/DependencyImpactSummary";
import {
  api,
  type CalculationSummary,
  type CollectionPipe,
  type CollectionRelationship,
  type DataCollection,
  type DeploymentSettings,
  type ConnectionMetadata,
} from "@/lib/api";

type Section = "sources" | "relationships" | "models" | "calculations";

export default function CollectionDetailPage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const location = useLocation();
  const [searchParams, setSearchParams] = useSearchParams();
  const { openModal } = useModal();
  const managed = useDeploymentMode() !== "self_hosted";
  const collectionId = Number(id);
  const [collection, setCollection] = useState<DataCollection | null>(null);
  const [calculations, setCalculations] = useState<CalculationSummary[]>([]);
  const [relationships, setRelationships] = useState<CollectionRelationship[]>(
    [],
  );
  const [settings, setSettings] = useState<DeploymentSettings | null>(null);
  const [refreshVersion, setRefreshVersion] = useState(0);
  const [loading, setLoading] = useState(true);
  const [deleting, setDeleting] = useState(false);
  const [error, setError] = useState<string | null>(
    location.state?.recoveryError ?? null,
  );
  const [notice, setNotice] = useState<string | null>(null);
  const [semanticModelCount, setSemanticModelCount] = useState<number | null>(
    null,
  );
  const [ownedModelFileCount, setOwnedModelFileCount] = useState(0);
  const requestedSection = searchParams.get("section");
  const section: Section =
    requestedSection === "relationships" ||
    requestedSection === "calculations" ||
    requestedSection === "models"
      ? requestedSection
      : "sources";

  useEffect(() => {
    let active = true;
    setLoading(true);
    setCollection(null);
    setSemanticModelCount(null);
    setOwnedModelFileCount(0);
    async function load() {
      setError(location.state?.recoveryError ?? null);
      try {
        const [
          nextCollection,
          nextCalculations,
          nextRelationships,
          nextSettings,
        ] = await Promise.all([
          api.collections.get(collectionId),
          api.calculations.list(collectionId),
          api.collections.relationships(collectionId),
          api.settings.get(),
        ]);
        if (!active) return;
        setCollection(nextCollection);
        setCalculations(nextCalculations);
        setRelationships(nextRelationships.relationships);
        setSettings(nextSettings);
      } catch (err: any) {
        if (active) setError(err.message);
      } finally {
        if (active) setLoading(false);
      }
    }

    if (Number.isInteger(collectionId) && collectionId > 0) {
      void load();
    } else {
      setError("App not found");
      setLoading(false);
    }
    return () => {
      active = false;
    };
  }, [collectionId]);

  async function refreshCollection() {
    try {
      const [nextCollection, nextCalculations, nextRelationships] =
        await Promise.all([
          api.collections.get(collectionId),
          api.calculations.list(collectionId),
          api.collections.relationships(collectionId),
        ]);
      setCollection(nextCollection);
      setCalculations(nextCalculations);
      setRelationships(nextRelationships.relationships);
      setRefreshVersion((current) => current + 1);
    } catch (err: any) {
      setError(err.message);
    }
  }

  function selectSection(nextSection: Section) {
    setSearchParams(nextSection === "sources" ? {} : { section: nextSection }, {
      replace: true,
    });
  }

  async function copyMcpUrl() {
    if (!collection) return;
    const base = settings?.public_url || window.location.origin;
    const url = base.replace(/\/$/, "") + collection.mcp_path;

    try {
      await navigator.clipboard.writeText(url);
      setNotice("Copied the " + collection.name + " MCP URL.");
    } catch {
      setError("Could not copy the MCP URL. Use " + url);
    }
  }

  function confirmDelete() {
    if (!collection) return;

    openModal({
      title: "Delete App?",
      body: (
        <div className="space-y-2">
          <p>
            This removes{" "}
            <span className="font-medium text-foreground">
              {collection.name}
            </span>{" "}
            as a workspace. Its sources and synchronized data are retained.
          </p>
          {calculations.length > 0 && (
            <p>
              Move or delete its {calculations.length} calculations before
              deleting this App.
            </p>
          )}
          {ownedModelFileCount > 0 && (
            <p>
              Delete its authored semantic models before deleting this App so
              they remain accessible.
            </p>
          )}
        </div>
      ),
      actions: ({ close }) => (
        <>
          <Button type="button" variant="outline" onClick={close}>
            Cancel
          </Button>
          <Button
            type="button"
            variant="destructive"
            disabled={calculations.length > 0 || ownedModelFileCount > 0}
            onClick={() => {
              close();
              void removeCollection();
            }}
          >
            Delete App
          </Button>
        </>
      ),
    });
  }

  async function removeCollection() {
    if (!collection) return;

    setDeleting(true);
    setError(null);
    try {
      await api.collections.delete(collection.id);
      navigate("/data/apps", { replace: true });
    } catch (err: any) {
      setError(err.message);
      setDeleting(false);
    }
  }

  if (loading) {
    return (
      <StateMessage state="loading" variant="page" message="Loading App" />
    );
  }

  if (!collection) {
    return (
      <StateMessage
        state="error"
        variant="panel"
        message={error ?? "App not found"}
      />
    );
  }

  return (
    <div className="space-y-7">
      <div>
        <Button
          type="button"
          variant="ghost"
          size="sm"
          className="-ml-2 mb-3"
          onClick={() => navigate("/data/apps")}
        >
          <ArrowLeft className="size-3.5" /> Apps
        </Button>
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="min-w-0">
            <h1 className="break-words text-2xl font-semibold">
              {collection.name}
            </h1>
            <p className="mt-1 max-w-3xl whitespace-pre-wrap text-sm text-muted-foreground">
              {collection.description || "No App description has been added."}
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            {!managed && (
              <Button
                type="button"
                variant="outline"
                onClick={() => void copyMcpUrl()}
              >
                <Copy className="size-4" /> MCP URL
              </Button>
            )}
            <Button
              to={"/data/apps/" + collection.id + "/edit"}
              variant="outline"
            >
              <Pencil className="size-4" /> Edit
            </Button>
            <Button
              type="button"
              variant="destructive"
              disabled={deleting}
              onClick={confirmDelete}
            >
              <Trash2 className="size-4" /> Delete
            </Button>
          </div>
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
      {notice && (
        <StateMessage
          state="success"
          variant="banner"
          message={notice}
          onClose={() => setNotice(null)}
        />
      )}

      {collection.agent_instructions && (
        <section className="rounded-lg border bg-card p-4">
          <h2 className="text-sm font-medium">Agent instructions</h2>
          <p className="mt-2 whitespace-pre-wrap text-sm leading-6 text-muted-foreground">
            {collection.agent_instructions}
          </p>
        </section>
      )}

      <div className="flex items-end gap-3 border-b">
        <nav className="flex items-center gap-1" aria-label="App sections">
          {[
            {
              id: "sources",
              label: "Sources",
              count: collection.pipe_count,
            },
            {
              id: "relationships",
              label: "Relationships",
              count: relationships.length,
            },
            {
              id: "models",
              label: "Semantic models",
              count: semanticModelCount,
            },
            {
              id: "calculations",
              label: "Calculations",
              count: calculations.length,
            },
          ].map((item) => {
            const active = section === item.id;

            return (
              <button
                key={item.id}
                type="button"
                onClick={() => selectSection(item.id as Section)}
                className={cn(
                  "relative cursor-pointer px-3 py-2 text-sm font-medium transition-colors",
                  active
                    ? "text-foreground after:absolute after:inset-x-0 after:-bottom-px after:h-0.5 after:bg-primary"
                    : "text-muted-foreground hover:text-foreground",
                )}
              >
                <span className="flex items-center gap-1.5">
                  <span>{item.label}</span>
                  {item.count !== null && (
                    <span className="text-xs">{item.count}</span>
                  )}
                </span>
              </button>
            );
          })}
        </nav>
      </div>

      {section === "sources" && (
        <SourcesSection
          collection={collection}
          managed={managed}
          onChanged={() => void refreshCollection()}
        />
      )}
      <div hidden={section !== "relationships"}>
        <RelationshipsSection
          collectionId={collection.id}
          relationships={relationships}
          onChanged={() => void refreshCollection()}
        />
      </div>
      <div hidden={section !== "models"}>
        <ModelsSection
          key={collection.id}
          collectionId={collection.id}
          onLoaded={(modelCount, ownedFileCount) => {
            setSemanticModelCount(modelCount);
            setOwnedModelFileCount(ownedFileCount);
          }}
          refreshVersion={refreshVersion}
          onChanged={() => void refreshCollection()}
        />
      </div>
      <div hidden={section !== "calculations"}>
        <CalculationsPage
          key={collection.id}
          collectionId={collection.id}
          refreshVersion={refreshVersion}
          embedded
          onChanged={() => void refreshCollection()}
        />
      </div>
    </div>
  );
}

function SourcesSection({
  collection,
  managed,
  onChanged,
}: {
  collection: DataCollection;
  managed: boolean;
  onChanged: () => void;
}) {
  const { openModal } = useModal();
  const navigate = useNavigate();
  const [selectedPipeId, setSelectedPipeId] = useState<number | null>(null);
  const [metadata, setMetadata] = useState<Record<number, ConnectionMetadata>>(
    {},
  );
  const [busy, setBusy] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  async function sync(pipeId: number) {
    setBusy(pipeId);
    setError(null);
    try {
      const result = await api.connections.sync(pipeId);
      if (!result.ok) throw new Error("Source synchronization failed");
      setNotice("Source synchronized.");
      onChanged();
    } catch (err: any) {
      setError(err.message);
    } finally {
      setBusy(null);
    }
  }
  async function showSource(pipeId: number) {
    setSelectedPipeId(pipeId);
    if (metadata[pipeId]) return;
    setBusy(pipeId);
    setError(null);
    try {
      const next = await api.connections.metadata(pipeId);
      setMetadata((current) => ({ ...current, [pipeId]: next }));
    } catch (err: any) {
      setError(err.message);
    } finally {
      setBusy(null);
    }
  }
  async function confirmRemove(pipeId: number) {
    setBusy(pipeId);
    setError(null);
    try {
      const impact = await api.collections.sourceRemovalImpact(
        collection.id,
        pipeId,
      );
      openModal({
        title: "Remove source from App?",
        body: (
          <div className="space-y-3">
            <p>
              The source and its synchronized data will be retained. Review
              every App dependency that will become unavailable.
            </p>
            <DependencyImpactSummary impact={impact} />
          </div>
        ),
        actions: ({ close }) => (
          <>
            <Button variant="outline" onClick={close}>
              Cancel
            </Button>
            <Button
              variant="destructive"
              onClick={() => {
                close();
                void removeSource(pipeId);
              }}
            >
              Remove from App
            </Button>
          </>
        ),
      });
    } catch (err: any) {
      setError(err.message);
    } finally {
      setBusy(null);
    }
  }
  async function removeSource(pipeId: number) {
    setBusy(pipeId);
    setError(null);
    try {
      await api.collections.update(collection.id, {
        name: collection.name,
        description: collection.description,
        agent_instructions: collection.agent_instructions,
        pipe_ids: collection.pipe_ids.filter((id) => id !== pipeId),
      });
      onChanged();
      setNotice("Source removed from App.");
    } catch (err: any) {
      setError(err.message);
    } finally {
      setBusy(null);
    }
  }

  if (collection.pipes.length === 0) {
    return (
      <StateMessage
        state="empty"
        variant="panel"
        title="No sources"
        message="Edit this App to add one or more synchronized sources."
      />
    );
  }

  const selectedPipe = collection.pipes.find(
    (pipe) => pipe.id === selectedPipeId,
  );
  if (selectedPipe) {
    return (
      <div className="space-y-4">
        {error && (
          <StateMessage state="error" variant="banner" message={error} />
        )}
        {notice && (
          <StateMessage state="success" variant="banner" message={notice} />
        )}
        <SourceDetail
          collection={collection}
          pipe={selectedPipe}
          managed={managed}
          metadata={metadata[selectedPipe.id]}
          loading={busy === selectedPipe.id}
          onClose={() => setSelectedPipeId(null)}
        />
      </div>
    );
  }

  return (
    <div className="space-y-3">
      {error && <StateMessage state="error" variant="banner" message={error} />}
      {notice && (
        <StateMessage state="success" variant="banner" message={notice} />
      )}
      <ItemGrid>
        {collection.pipes.map((pipe) => {
          return (
            <ItemCard
              key={pipe.id}
              title={
                <button
                  type="button"
                  className="cursor-pointer text-left hover:text-primary hover:underline"
                  onClick={() => void showSource(pipe.id)}
                >
                  {pipe.name}
                </button>
              }
              pills={
                <>
                  <Badge variant={statusVariant(pipe.status)}>
                    {pipe.status}
                  </Badge>
                  <Badge variant="outline">{pipe.table_count} tables</Badge>
                </>
              }
              footer={
                <RowActions
                  actions={[
                    {
                      key: "view",
                      title: "View source",
                      ariaLabel: "View source",
                      disabled: busy !== null,
                      onClick: () => void showSource(pipe.id),
                    },
                    {
                      key: "sync",
                      title: "Sync now",
                      ariaLabel: "Sync source now",
                      disabled: busy !== null || pipe.status === "syncing",
                      loading: busy === pipe.id,
                      onClick: () => void sync(pipe.id),
                    },
                    {
                      key: "edit",
                      title: "Edit YAML and source",
                      ariaLabel: "Edit source",
                      onClick: () => {
                        navigate(`/data/${pipe.id}/edit`);
                      },
                    },
                    {
                      key: "delete",
                      title: "Remove source from App",
                      ariaLabel: "Remove source from App",
                      disabled: busy !== null,
                      danger: true,
                      onClick: () => {
                        void confirmRemove(pipe.id);
                      },
                    },
                  ]}
                />
              }
            >
              <div className="space-y-3">
                <div className="space-y-2 text-sm">
                  {!managed && (
                    <>
                      <Metric
                        label="Destination"
                        value={pipe.destination_name ?? "Destination"}
                      />
                      <Metric label="Schema" value={pipe.destination_schema} />
                    </>
                  )}
                  <Metric label="Tables" value={String(pipe.table_count)} />
                  <Metric
                    label="Last sync"
                    value={
                      pipe.last_synced_at ? (
                        <Timestamp value={pipe.last_synced_at} />
                      ) : (
                        "Never"
                      )
                    }
                  />
                </div>
              </div>
            </ItemCard>
          );
        })}
      </ItemGrid>
    </div>
  );
}

function SourceDetail({
  collection,
  pipe,
  managed,
  metadata,
  loading,
  onClose,
}: {
  collection: DataCollection;
  pipe: CollectionPipe;
  managed: boolean;
  metadata?: ConnectionMetadata;
  loading: boolean;
  onClose: () => void;
}) {
  const tables = (collection.tables ?? []).filter(
    (table) => table.pipe_id === pipe.id,
  );

  return (
    <section className="space-y-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h2 className="break-words text-lg font-semibold">{pipe.name}</h2>
          <div className="mt-2 flex flex-wrap gap-1.5">
            <Badge variant={statusVariant(pipe.status)}>{pipe.status}</Badge>
            <Badge variant="outline">{pipe.table_count} tables</Badge>
          </div>
        </div>
        <Button type="button" variant="outline" onClick={onClose}>
          Close
        </Button>
      </div>

      <div className="space-y-2 text-sm text-muted-foreground">
        {!managed && (
          <>
            <Metric
              label="Destination"
              value={pipe.destination_name ?? "Destination"}
            />
            <Metric label="Schema" value={pipe.destination_schema} />
          </>
        )}
        <Metric
          label="Last sync"
          value={
            pipe.last_synced_at ? (
              <Timestamp value={pipe.last_synced_at} />
            ) : (
              "Never"
            )
          }
        />
      </div>

      <SchemaView
        metadata={tables}
        loading={loading}
        collectionId={collection.id}
        pipeId={pipe.id}
        columns={metadata?.tables}
      />
    </section>
  );
}

function Metric({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div className="flex items-baseline gap-1.5">
      <span>{label}</span>
      <span className="font-medium text-foreground">{value}</span>
    </div>
  );
}

function SchemaView({
  metadata,
  loading,
  collectionId,
  pipeId,
  columns,
}: {
  metadata?: { schema: string; table: string; column_count: number }[];
  loading: boolean;
  collectionId: number;
  pipeId: number;
  columns?: ConnectionMetadata["tables"];
}) {
  if (loading) {
    return (
      <div className="flex items-center gap-2 rounded-lg border p-3">
        <span className="size-3.5 animate-spin"> </span> Loading schema
      </div>
    );
  }

  if (!metadata || metadata.length === 0) return null;

  return (
    <div className="space-y-3 border-t pt-3">
      <div className="flex items-center gap-2 text-sm font-medium">
        <Rows3 className="size-4" /> Synchronized schema
      </div>
      <div className="space-y-3">
        {metadata.map((table) => (
          <div
            key={table.schema + "." + table.table}
            className="w-full overflow-hidden rounded-lg border"
          >
            <div className="flex items-center gap-2 border-b bg-muted/35 px-3 py-2">
              <Database className="size-3.5" />
              <span className="font-mono text-sm font-medium">
                {table.table}
              </span>
              <Badge variant="outline" className="ml-auto">
                {table.column_count} columns
              </Badge>
            </div>
            {columns?.[table.table]?.columns && (
              <details className="px-3 pt-2 text-xs">
                <summary className="cursor-pointer">View columns</summary>
                <div className="mt-2 space-y-1">
                  {columns[table.table].columns.map((column) => (
                    <p key={column.name}>
                      <span className="font-mono">{column.name}</span> ·{" "}
                      {column.type}
                      {column.nullable ? " · Nullable" : ""}
                      {column.description ? ` · ${column.description}` : ""}
                    </p>
                  ))}
                </div>
              </details>
            )}
            <TableInspector
              collectionId={collectionId}
              pipeId={pipeId}
              table={table.table}
            />
          </div>
        ))}
      </div>
    </div>
  );
}

function statusVariant(status: string) {
  if (status === "active") return "success" as const;
  if (status === "failed") return "destructive" as const;
  return "warning" as const;
}
