import { useEffect, useRef, useState } from "react";
import { ArrowLeft } from "lucide-react";
import { Link, useParams, useSearchParams } from "react-router-dom";

import { useAuth } from "@/auth/auth-provider";
import { OverlayEditor } from "@/components/collections/OverlayEditor";
import { QueryTester } from "@/components/collections/QueryTester";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ItemCard, ItemGrid } from "@/components/ui/item-grid";
import { StateMessage } from "@/components/ui/state-message";
import { notify } from "@/components/ui/global-toast";
import { api, type CollectionModelCatalog, type OverlayDraft } from "@/lib/api";
import { useWorkspaceChange } from "@/realtime/workspace-events";

export default function CollectionModelPage() {
  const { id } = useParams<{ id: string }>();
  const [searchParams] = useSearchParams();
  const collectionId = Number(id);
  const path = searchParams.get("path");
  const { session } = useAuth();
  const canWrite = ["owner", "admin"].includes(
    session?.organization.role ?? "",
  );
  const [catalog, setCatalog] = useState<CollectionModelCatalog | null>(null);
  const [draft, setDraft] = useState<OverlayDraft | null>(null);
  const [readOnly, setReadOnly] = useState(true);
  const [search, setSearch] = useState("");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [refreshVersion, setRefreshVersion] = useState(0);
  const yamlVersion = useRef(0);

  useWorkspaceChange(["semantic_models", "connections"], (event) => {
    if (event.artifact_id !== null && event.artifact_id !== collectionId) {
      return;
    }
    if (!draft) setRefreshVersion((current) => current + 1);
  });

  useEffect(() => {
    let active = true;
    yamlVersion.current += 1;
    setLoading(true);
    setBusy(false);
    setError(null);
    setCatalog(null);
    setDraft(null);
    setSearch("");
    if (!path || !Number.isInteger(collectionId) || collectionId <= 0) {
      setError("Semantic model not found");
      setLoading(false);
      return;
    }
    api.collections
      .models(collectionId)
      .then((nextCatalog) => {
        if (active) setCatalog(nextCatalog);
      })
      .catch((err) => {
        if (active) setError(err.message);
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
      yamlVersion.current += 1;
    };
  }, [collectionId, path, refreshVersion]);

  const file = catalog?.files.find((item) => item.path === path);
  const editable =
    canWrite && !file?.read_only && file?.source_type === "generated_overlay";
  const models = catalog?.models.filter((model) => model.path === path) ?? [];
  const filteredModels = models.filter((model) =>
    JSON.stringify(model.meta)
      .toLowerCase()
      .includes(search.trim().toLowerCase()),
  );
  async function openYaml() {
    if (!file) return;
    const version = ++yamlVersion.current;
    setBusy(true);
    setError(null);
    try {
      const stored = await api.collections.modelFile(collectionId, file.path);
      if (version !== yamlVersion.current) return;
      setReadOnly(!editable || !!stored.read_only);
      setDraft({
        path: stored.path,
        content: stored.content,
        expected_content: stored.content,
        create: false,
      });
    } catch (err: any) {
      if (version === yamlVersion.current) setError(err.message);
    } finally {
      if (version === yamlVersion.current) setBusy(false);
    }
  }

  return (
    <div className="space-y-6">
      {!draft && (
        <Button
          to={`/data/artifacts/${collectionId}?section=models`}
          variant="ghost"
          size="sm"
          className="-ml-2"
        >
          <ArrowLeft className="size-3.5" /> Semantic models
        </Button>
      )}
      {loading ? (
        <StateMessage
          state="loading"
          variant="panel"
          message="Loading semantic model"
        />
      ) : !file ? (
        <StateMessage
          state="error"
          variant="panel"
          message={error ?? "Semantic model not found in this artifact"}
        />
      ) : (
        <>
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div className="min-w-0">
              <h1 className="break-words text-2xl font-semibold">
                {file.display_name || "Semantic definition"}
              </h1>
              <p className="mt-1 text-sm text-muted-foreground">
                Cubes and views defined by this semantic model.
              </p>
              {!file.compile.compiled && (
                <div className="mt-3">
                  <Badge variant="warning">Needs attention</Badge>
                </div>
              )}
            </div>
            {!draft && (
              <div className="flex flex-wrap gap-2">
                <QueryTester
                  collectionId={collectionId}
                  models={models}
                  initialCubeName={models[0]?.name}
                  disabled={busy}
                />
                <Button
                  variant="outline"
                  disabled={busy}
                  onClick={() => void openYaml()}
                >
                  {editable ? "Edit model" : "View YAML"}
                </Button>
              </div>
            )}
          </div>
          {error && (
            <StateMessage state="error" variant="banner" message={error} />
          )}
          {catalog?.metadata_error && (
            <StateMessage
              state="warning"
              variant="banner"
              message={`${catalog.metadata_error}. Stored definitions remain available.`}
            />
          )}
          {file.issues.map((issue) => (
            <StateMessage
              key={issue}
              state="warning"
              variant="banner"
              message={issue}
            />
          ))}
          {file.compile.error && (
            <StateMessage
              state="warning"
              variant="banner"
              message={file.compile.error}
            />
          )}
          {draft ? (
            <OverlayEditor
              key={draft.path}
              collectionId={collectionId}
              initial={draft}
              models={models}
              readOnly={readOnly}
              title={file.display_name || "Semantic definition"}
              onClose={() => setDraft(null)}
              onSaved={(message) => {
                setDraft(null);
                if (message.includes("needs attention")) {
                  notify.warning(message);
                } else {
                  notify.success(message);
                }
                setRefreshVersion((current) => current + 1);
              }}
            />
          ) : (
            <section className="space-y-4">
              <h2 className="text-lg font-semibold">Cubes and views</h2>
              {models.length > 0 && (
                <Input
                  type="search"
                  value={search}
                  onChange={(event) => setSearch(event.target.value)}
                  placeholder="Find a cube, view, measure, or dimension"
                  aria-label="Find model cubes and views"
                  className="max-w-sm"
                />
              )}
              {!filteredModels.length ? (
                <StateMessage
                  state="empty"
                  variant="panel"
                  title={
                    models.length
                      ? "No matching cubes or views"
                      : "No cubes or views"
                  }
                  message={
                    models.length
                      ? "Try a different search."
                      : "Inspect the stored YAML to add definitions or repair this model."
                  }
                />
              ) : (
                <ItemGrid>
                  {filteredModels.map((model) => {
                    const memberSummary = formatCountSummary(
                      [
                        [model.meta.measures.length, "measure"],
                        [model.meta.dimensions.length, "dimension"],
                        [model.meta.segments.length, "segment"],
                      ],
                      " | ",
                    );

                    return (
                      <ItemCard
                        key={model.name}
                        title={
                          <Link
                            to={`/data/artifacts/${collectionId}/models/${encodeURIComponent(model.name)}`}
                            className="hover:text-primary hover:underline"
                          >
                            {model.meta.title || model.name}
                          </Link>
                        }
                        pills={
                          <>
                            {model.meta.type === "view" && (
                              <Badge variant="outline">View</Badge>
                            )}
                            {!model.in_scope ? (
                              <Badge variant="warning">
                                Missing dependencies
                              </Badge>
                            ) : !model.compile.compiled ? (
                              <Badge variant="warning">Needs attention</Badge>
                            ) : null}
                          </>
                        }
                      >
                        <p className="break-words font-mono text-xs">
                          {model.name}
                        </p>
                        <p className="mt-2">
                          {model.meta.description ||
                            "No description available."}
                        </p>
                        {memberSummary && (
                          <p className="mt-2 text-xs">{memberSummary}</p>
                        )}
                      </ItemCard>
                    );
                  })}
                </ItemGrid>
              )}
            </section>
          )}
        </>
      )}
    </div>
  );
}

function formatCountSummary(
  items: Array<[count: number, label: string]>,
  separator: string,
) {
  return items
    .filter(([count]) => count > 0)
    .map(([count, label]) => `${count} ${label}${count === 1 ? "" : "s"}`)
    .join(separator);
}
