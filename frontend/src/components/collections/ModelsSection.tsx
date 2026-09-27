import { useEffect, useRef, useState } from "react";
import { Plus, RefreshCw } from "lucide-react";
import { Link, useNavigate } from "react-router-dom";
import { useAuth } from "@/auth/auth-provider";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { ItemCard, ItemGrid } from "@/components/ui/item-grid";
import { RowActions } from "@/components/ui/row-actions";
import { StateMessage } from "@/components/ui/state-message";
import { useModal } from "@/components/ui/global-modal";
import { notify } from "@/components/ui/global-toast";
import { OverlayEditor } from "./OverlayEditor";
import { QueryTester } from "./QueryTester";
import { WorkspaceDependencyImpactSummary } from "./DependencyImpactSummary";
import { api, type CollectionModelCatalog, type OverlayDraft } from "@/lib/api";
import { waitForRefreshFeedback } from "@/lib/refresh-feedback";

export function ModelsSection({
  collectionId,
  onChanged,
  refreshVersion,
  onLoaded,
}: {
  collectionId: number;
  onChanged: () => void;
  refreshVersion: number;
  onLoaded?: (modelCount: number, ownedFileCount: number) => void;
}) {
  const navigate = useNavigate();
  const { openModal } = useModal();
  const { session } = useAuth();
  const canWrite = ["owner", "admin"].includes(
    session?.organization.role ?? "",
  );
  const [catalog, setCatalog] = useState<CollectionModelCatalog | null>(null);
  const [draft, setDraft] = useState<OverlayDraft | null>(null);
  const [readOnly, setReadOnly] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const loadVersion = useRef(0);

  useEffect(() => {
    void load();
    return () => {
      loadVersion.current += 1;
    };
  }, [collectionId, refreshVersion]);
  async function load(announce = false) {
    const version = ++loadVersion.current;
    const startedAt = Date.now();
    setRefreshing(true);
    setError(null);
    try {
      const nextCatalog = await api.collections.models(collectionId);
      if (version !== loadVersion.current) return;
      setCatalog(nextCatalog);
      onLoaded?.(
        nextCatalog.files.length,
        nextCatalog.files.filter((file) => file.owned).length,
      );
      if (announce) notify.success("Semantic models refreshed.");
    } catch (err: any) {
      if (version === loadVersion.current) {
        setError(err.message);
        if (announce) notify.error(err.message);
      }
    } finally {
      if (announce) await waitForRefreshFeedback(startedAt);
      if (version === loadVersion.current) setRefreshing(false);
    }
  }
  async function edit(path: string, sourceType: string) {
    setBusy(true);
    setError(null);
    try {
      const file = await api.collections.modelFile(collectionId, path);
      setReadOnly(
        !canWrite || sourceType !== "generated_overlay" || !!file.read_only,
      );
      setDraft({
        path: file.path,
        content: file.content,
        expected_content: file.content,
        create: false,
      });
    } catch (err: any) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }
  async function confirmDelete(path: string) {
    setBusy(true);
    setError(null);
    try {
      const impact = await api.collections.modelDeletionImpact(
        collectionId,
        path,
      );
      openModal({
        title: "Delete semantic model?",
        body: (
          <div className="space-y-3">
            <p>
              This removes the entire overlay and its cubes and views. Review
              every affected dependency before continuing.
            </p>
            <WorkspaceDependencyImpactSummary impact={impact} />
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
                void remove(path);
              }}
            >
              Delete model
            </Button>
          </>
        ),
      });
    } catch (err: any) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }
  async function remove(path: string) {
    setBusy(true);
    setError(null);
    try {
      await api.collections.deleteOverlay(collectionId, path);
      await load();
      onChanged();
      notify.success("Model deleted.");
    } catch (err: any) {
      setError(err.message);
      notify.error(err.message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="space-y-4">
      {error && <StateMessage state="error" variant="banner" message={error} />}
      {draft ? (
        <OverlayEditor
          collectionId={collectionId}
          initial={draft}
          models={catalog?.models ?? []}
          readOnly={readOnly}
          onClose={() => setDraft(null)}
          onSaved={(message) => {
            setDraft(null);
            if (message.includes("needs attention")) {
              notify.warning(message);
            } else {
              notify.success(message);
            }
            void load();
            onChanged();
          }}
        />
      ) : (
        <>
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div></div>
            <div className="flex gap-2">
              <QueryTester
                collectionId={collectionId}
                models={catalog?.models ?? []}
                disabled={busy || refreshing || !catalog}
              />
              <Button
                variant="outline"
                disabled={busy || refreshing}
                onClick={() => void load(true)}
                aria-label="Refresh semantic models"
              >
                <RefreshCw
                  className={refreshing ? "size-4 animate-spin" : "size-4"}
                />
              </Button>
              {canWrite && (
                <Button
                  disabled={busy || refreshing}
                  onClick={() => {
                    setReadOnly(false);
                    setDraft({
                      path: `collections/${collectionId}/model_${crypto.randomUUID().slice(0, 8)}.yaml`,
                      content: "cubes: []\n",
                      expected_content: null,
                      create: true,
                    });
                  }}
                >
                  <Plus className="size-4" /> Add model
                </Button>
              )}
            </div>
          </div>
          {catalog?.metadata_error && (
            <StateMessage
              state="warning"
              variant="banner"
              message={`${catalog.metadata_error}. Stored models remain available below.`}
            />
          )}
          {!catalog ? (
            <StateMessage
              state={error ? "error" : "loading"}
              variant="panel"
              message={
                error
                  ? "Could not load semantic models. Refresh to try again."
                  : "Loading models"
              }
            />
          ) : !catalog.files.length ? (
            <StateMessage
              state="empty"
              variant="panel"
              title="No semantic models"
              message="Synchronize a source to generate its model, or author a model using this App's sources."
            />
          ) : (
            <ItemGrid>
              {catalog.files.map((file) => (
                <ItemCard
                  key={file.path}
                  title={
                    <Link
                      to={`/data/apps/${collectionId}/model?path=${encodeURIComponent(file.path)}`}
                      className="hover:text-primary hover:underline"
                    >
                      {file.path.split("/").slice(-1)[0]}
                    </Link>
                  }
                  pills={
                    <>
                      <Badge variant="outline">{file.cube_count} cubes</Badge>
                      {file.view_count > 0 && (
                        <Badge variant="outline">{file.view_count} views</Badge>
                      )}
                      <Badge variant="secondary">
                        {file.source_type === "generated_connection"
                          ? "Source model"
                          : "Overlay"}
                      </Badge>
                      {!file.compile.compiled && (
                        <Badge variant="warning">Needs attention</Badge>
                      )}
                    </>
                  }
                  footer={
                    <RowActions
                      actions={[
                        {
                          key: "view",
                          title: "View model",
                          onClick: () => {
                            navigate(
                              `/data/apps/${collectionId}/model?path=${encodeURIComponent(file.path)}`,
                            );
                          },
                        },
                        ...(canWrite &&
                        !file.read_only &&
                        file.source_type === "generated_overlay"
                          ? [
                              {
                                key: "edit" as const,
                                title: "Edit and validate",
                                disabled: busy,
                                onClick: () =>
                                  void edit(file.path, file.source_type),
                              },
                              {
                                key: "delete" as const,
                                title: "Delete model",
                                danger: true,
                                onClick: () => {
                                  if (!busy) void confirmDelete(file.path);
                                },
                              },
                            ]
                          : []),
                      ]}
                    />
                  }
                >
                  <p className="break-words font-mono text-xs">
                    {[...file.cube_names, ...file.view_names].join(", ")}
                  </p>
                  {file.issues.map((issue) => (
                    <p
                      key={issue}
                      className="mt-2 text-sm text-amber-700 dark:text-amber-300"
                    >
                      {issue}
                    </p>
                  ))}
                  {file.compile.error && (
                    <p className="mt-2 text-sm text-amber-700 dark:text-amber-300">
                      {file.compile.error}
                    </p>
                  )}
                </ItemCard>
              ))}
            </ItemGrid>
          )}
        </>
      )}
    </div>
  );
}
