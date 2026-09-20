import { useEffect, useState, type ReactNode } from "react";
import { ArrowLeft, Pencil, Trash2 } from "lucide-react";
import { useNavigate, useParams, useSearchParams } from "react-router-dom";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { useModal } from "@/components/ui/global-modal";
import { notify } from "@/components/ui/global-toast";
import { ItemCard, ItemGrid } from "@/components/ui/item-grid";
import { RowActions } from "@/components/ui/row-actions";
import { StateMessage } from "@/components/ui/state-message";
import { Timestamp } from "@/components/ui/timestamp";
import { cn } from "@/lib/utils";
import { useDeploymentMode } from "@/config/product-provider";
import { GraphSection } from "@/components/collections/GraphSection";
import { RelationshipsSection } from "@/components/collections/RelationshipsSection";
import { ModelsSection } from "@/components/collections/ModelsSection";
import { TableInspector } from "@/components/collections/TableInspector";
import { DependencyImpactSummary } from "@/components/collections/DependencyImpactSummary";
import { SourceDetail } from "@/components/data/source-detail";
import {
  api,
  type CollectionRelationship,
  type DataCollection,
  type ConnectionMetadata,
} from "@/lib/api";

type Section = "sources" | "relationships" | "models" | "graph";

export default function CollectionDetailPage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const { openModal } = useModal();
  const managed = useDeploymentMode() !== "self_hosted";
  const collectionId = Number(id);
  const [collection, setCollection] = useState<DataCollection | null>(null);
  const [relationships, setRelationships] = useState<CollectionRelationship[]>(
    [],
  );
  const [refreshVersion, setRefreshVersion] = useState(0);
  const [loading, setLoading] = useState(true);
  const [deleting, setDeleting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [semanticModelCount, setSemanticModelCount] = useState<number | null>(
    null,
  );
  const [ownedModelFileCount, setOwnedModelFileCount] = useState(0);
  const requestedSection = searchParams.get("section");
  const section: Section =
    requestedSection === "relationships" || requestedSection === "models"
      ? requestedSection
      : requestedSection === "graph"
        ? "graph"
        : "sources";

  useEffect(() => {
    let active = true;
    setLoading(true);
    setCollection(null);
    setSemanticModelCount(null);
    setOwnedModelFileCount(0);
    async function load() {
      setError(null);
      try {
        const [nextCollection, nextRelationships] = await Promise.all([
          api.collections.get(collectionId),
          api.collections.relationships(collectionId),
        ]);
        if (!active) return;
        setCollection(nextCollection);
        setRelationships(nextRelationships.relationships);
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
      const [nextCollection, nextRelationships] = await Promise.all([
        api.collections.get(collectionId),
        api.collections.relationships(collectionId),
      ]);
      setCollection(nextCollection);
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
            disabled={ownedModelFileCount > 0}
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
      notify.success("App deleted.");
      navigate("/data/apps", { replace: true });
    } catch (err: any) {
      setError(err.message);
      notify.error(err.message);
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
            <Button
              to={"/data/apps/" + collection.id + "/edit"}
              variant="outline"
            >
              <Pencil className="size-4" />
            </Button>
            <Button
              type="button"
              variant="destructive"
              disabled={deleting}
              onClick={confirmDelete}
            >
              <Trash2 className="size-4" />
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
              id: "graph",
              label: "Graph",
              count: null,
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
      <div hidden={section !== "graph"}>
        <GraphSection key={collection.id} collectionId={collection.id} />
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

  async function sync(pipeId: number) {
    setBusy(pipeId);
    setError(null);
    try {
      const result = await api.connections.sync(pipeId);
      if (!result.ok) throw new Error("Source synchronization failed");
      notify.success("Source synchronized.");
      onChanged();
    } catch (err: any) {
      setError(err.message);
      notify.error(err.message);
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
      notify.error(err.message);
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
      notify.success("Source removed from App.");
    } catch (err: any) {
      setError(err.message);
      notify.error(err.message);
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
        <SourceDetail
          name={selectedPipe.name}
          status={selectedPipe.status}
          tableCount={selectedPipe.table_count}
          managed={managed}
          destinationName={selectedPipe.destination_name}
          destinationSchema={selectedPipe.destination_schema}
          lastSyncedAt={selectedPipe.last_synced_at}
          tables={(collection.tables ?? [])
            .filter((table) => table.pipe_id === selectedPipe.id)
            .map((table) => ({
              key: table.schema + "." + table.table,
              name: table.table,
              columnCount: table.column_count,
              description:
                metadata[selectedPipe.id]?.tables[table.table]?.description,
              columns: metadata[selectedPipe.id]?.tables[table.table]?.columns,
            }))}
          loading={busy === selectedPipe.id}
          onClose={() => setSelectedPipeId(null)}
          renderTableContent={(table) => (
            <TableInspector
              collectionId={collection.id}
              pipeId={selectedPipe.id}
              table={table.name}
            />
          )}
        />
      </div>
    );
  }

  return (
    <div className="space-y-3">
      {error && <StateMessage state="error" variant="banner" message={error} />}
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

function Metric({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div className="flex items-baseline gap-1.5">
      <span>{label}</span>
      <span className="font-medium text-foreground">{value}</span>
    </div>
  );
}

function statusVariant(status: string) {
  if (status === "active") return "success" as const;
  if (status === "failed") return "destructive" as const;
  return "warning" as const;
}
