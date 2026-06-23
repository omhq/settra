import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { ChevronDown, FileCode2, Loader2, RefreshCw, Save } from "lucide-react";

import {
  api,
  type CubeMetaCube,
  type CubeModelFile,
  type CubeModelSummary,
} from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ItemCard, ItemGrid } from "@/components/ui/item-grid";
import { RowActions } from "@/components/ui/row-actions";
import { SelectMenu } from "@/components/ui/select-menu";
import { StateMessage } from "@/components/ui/state-message";
import { Timestamp } from "@/components/ui/timestamp";

export default function SemanticsPage() {
  const [summary, setSummary] = useState<CubeModelSummary | null>(null);
  const [selectedPath, setSelectedPath] = useState<string | null>(null);
  const [file, setFile] = useState<CubeModelFile | null>(null);
  const [content, setContent] = useState("");
  const [savedContent, setSavedContent] = useState("");
  const [loading, setLoading] = useState(true);
  const [fileLoading, setFileLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [syncing, setSyncing] = useState(false);
  const [yamlOpen, setYamlOpen] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const dirty = content !== savedContent;

  const cubeFiles = summary?.files ?? [];
  const cubes = summary?.cube.meta?.cubes ?? [];

  useEffect(() => {
    void loadSummary();
  }, []);

  useEffect(() => {
    if (!summary || selectedPath) return;
    setSelectedPath(summary.files[0]?.path ?? null);
  }, [selectedPath, summary]);

  useEffect(() => {
    if (!selectedPath) {
      setFile(null);
      setContent("");
      setSavedContent("");
      return;
    }

    void loadFile(selectedPath);
  }, [selectedPath]);

  const selectedSummary = useMemo(
    () => cubeFiles.find((item) => item.path === selectedPath) ?? null,
    [cubeFiles, selectedPath],
  );
  const selectedCubes = useMemo(() => {
    if (!selectedSummary) return cubes;

    const names = new Set(selectedSummary.cube_names);
    return cubes.filter((cube) => names.has(cube.name));
  }, [cubes, selectedSummary]);
  const fileOptions = useMemo(
    () =>
      cubeFiles.map((item) => ({
        value: item.path,
        label: item.path,
        description: `${item.cube_count} cubes${
          item.view_count ? `, ${item.view_count} views` : ""
        }`,
      })),
    [cubeFiles],
  );

  async function loadSummary() {
    setError(null);

    try {
      const nextSummary = await api.semantics.model();
      setSummary(nextSummary);

      if (
        selectedPath &&
        !nextSummary.files.some((item) => item.path === selectedPath)
      ) {
        setSelectedPath(nextSummary.files[0]?.path ?? null);
      }
    } catch (err: any) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  async function loadFile(path: string) {
    setFileLoading(true);
    setError(null);

    try {
      const nextFile = await api.semantics.getFile(path);
      setFile(nextFile);
      setContent(nextFile.content);
      setSavedContent(nextFile.content);
    } catch (err: any) {
      setError(err.message);
    } finally {
      setFileLoading(false);
    }
  }

  async function syncModel() {
    setSyncing(true);
    setError(null);
    setNotice(null);

    try {
      const result = await api.semantics.syncModel();
      await loadSummary();
      setNotice(`Cube model refreshed. ${result.files.length} files available.`);
    } catch (err: any) {
      setError(err.message);
    } finally {
      setSyncing(false);
    }
  }

  async function saveFile() {
    if (!selectedPath) return;

    setSaving(true);
    setError(null);
    setNotice(null);

    try {
      await api.semantics.saveFile(selectedPath, content);
      const nextFile = await api.semantics.getFile(selectedPath);
      setFile(nextFile);
      setContent(nextFile.content);
      setSavedContent(nextFile.content);
      await refreshCompiledMetadata();
      setNotice(`${selectedPath} saved.`);
    } catch (err: any) {
      setError(err.message);
    } finally {
      setSaving(false);
    }
  }

  async function refreshCompiledMetadata() {
    for (const delayMs of [200, 400, 800, 1200]) {
      await delay(delayMs);
      await loadSummary();
    }
  }

  if (loading) {
    return (
      <StateMessage
        state="loading"
        variant="page"
        message="Loading Cube model"
      />
    );
  }

  return (
    <div className="flex h-full min-h-0 flex-col gap-5 overflow-hidden">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h1 className="text-2xl font-semibold">Semantics</h1>
          <div className="mt-2 flex flex-wrap items-center gap-2">
            <Badge variant="secondary">
              {summary?.cube.cube_count ?? 0} cubes
            </Badge>
            <Badge variant="outline">{cubeFiles.length} files</Badge>
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <SelectMenu
            options={fileOptions}
            value={selectedPath}
            onChange={setSelectedPath}
            placeholder="Select model file"
            disabled={!cubeFiles.length}
            className="w-full min-w-64 sm:w-80"
            triggerClassName="h-9"
          />
          <Button
            type="button"
            variant="outline"
            disabled={syncing}
            onClick={() => void syncModel()}
          >
            {syncing ? (
              <Loader2 className="size-4 animate-spin" />
            ) : (
              <RefreshCw className="size-4" />
            )}
            Refresh
          </Button>
          <Button
            type="button"
            disabled={!dirty || saving || !selectedPath}
            onClick={() => void saveFile()}
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

      {error && <StateMessage state="error" variant="banner" message={error} />}
      {notice && (
        <StateMessage state="success" variant="banner" message={notice} />
      )}
      {summary?.cube.error && (
        <StateMessage
          state="warning"
          variant="banner"
          title="Cube compile error"
          message={summary.cube.error}
        />
      )}
      {cubeFiles.length === 0 ? (
        <StateMessage
          state="empty"
          variant="panel"
          title="No Cube model files"
          message="Add Cube YAML files to the model directory."
          action={
            <Button
              type="button"
              variant="primary"
              disabled={syncing}
              onClick={() => void syncModel()}
            >
              <RefreshCw className="size-4" />
              Refresh
            </Button>
          }
        />
      ) : (
        <section className="min-h-0 flex-1 overflow-y-auto">
          <div
            className={
              yamlOpen ? "flex min-h-full flex-col gap-4" : "space-y-4"
            }
          >
            <div
              className={
                yamlOpen
                  ? "flex min-h-[calc(100vh-11rem)] flex-col rounded-lg border bg-card"
                  : "rounded-lg border bg-card"
              }
            >
              <div
                className={
                  yamlOpen
                    ? "flex flex-wrap items-center justify-between gap-2 border-b px-4 py-3"
                    : "flex flex-wrap items-center justify-between gap-2 px-4 py-3"
                }
              >
                <div className="min-w-0">
                  <div className="flex min-w-0 items-center gap-2">
                    <FileCode2 className="size-4 shrink-0 text-muted-foreground" />
                    <h2 className="min-w-0 break-words text-sm font-medium">
                      {selectedPath ?? "Model file"}
                    </h2>
                  </div>
                  {selectedSummary && (
                    <p className="mt-1 text-xs text-muted-foreground">
                      {selectedSummary.cube_count} cubes |{" "}
                      <Timestamp value={selectedSummary.updated_at} />
                    </p>
                  )}
                </div>
                <div className="flex flex-wrap items-center gap-1.5">
                  {dirty && <Badge variant="secondary">Unsaved</Badge>}
                  <Button
                    type="button"
                    variant="ghost"
                    size="icon-sm"
                    aria-label={yamlOpen ? "Collapse YAML" : "Expand YAML"}
                    aria-expanded={yamlOpen}
                    aria-controls="cube-yaml-editor"
                    onClick={() => setYamlOpen((current) => !current)}
                  >
                    <ChevronDown
                      className={
                        yamlOpen
                          ? "size-4 rotate-180 transition-transform"
                          : "size-4 transition-transform"
                      }
                    />
                  </Button>
                </div>
              </div>

              {yamlOpen &&
                (fileLoading ? (
                  <StateMessage
                    state="loading"
                    variant="panel"
                    message="Loading file"
                  />
                ) : (
                  <textarea
                    id="cube-yaml-editor"
                    spellCheck={false}
                    value={content}
                    onChange={(event) => setContent(event.target.value)}
                    className="block min-h-0 flex-1 resize-none rounded-b-lg border-0 bg-background px-4 py-3 font-mono text-[0.82rem] leading-5 text-foreground outline-none focus-visible:ring-3 focus-visible:ring-ring/40"
                    aria-label="Cube YAML model"
                  />
                ))}
            </div>

            <CubeMetadata cubes={selectedCubes} selectedFile={selectedSummary} />
          </div>
        </section>
      )}
    </div>
  );
}

function CubeMetadata({
  cubes,
  selectedFile,
}: {
  cubes: CubeMetaCube[];
  selectedFile: CubeModelSummary["files"][number] | null;
}) {
  const navigate = useNavigate();
  const [query, setQuery] = useState("");
  const filteredCubes = useMemo(
    () => cubes.filter((cube) => matchesSearch(cube, query)),
    [cubes, query],
  );

  if (!cubes.length) {
    return (
      <StateMessage
        state="empty"
        variant="panel"
        title="Cube metadata is empty"
        message={
          selectedFile
            ? "Cube has not compiled any cubes from this file yet."
            : "Cube has not compiled any cubes yet."
        }
      />
    );
  }

  return (
    <div className="space-y-3">
      <Input
        type="search"
        value={query}
        onChange={(event) => setQuery(event.target.value)}
        placeholder="Filter cubes"
        aria-label="Filter compiled cubes"
        className="max-w-sm"
      />
      <h2 className="text-base font-semibold">Compiled Cubes</h2>
      {filteredCubes.length === 0 ? (
        <StateMessage
          state="empty"
          variant="panel"
          title="No cubes match"
          message="Try a different filter."
        />
      ) : (
        <ItemGrid className="lg:grid-cols-2 xl:grid-cols-3">
          {filteredCubes.map((cube) => (
            <ItemCard
              key={cube.name}
              title={cube.title || cube.name}
              pills={
                <>
                  <Badge variant="outline">
                    {cube.measures.length} measures
                  </Badge>
                  <Badge variant="outline">
                    {cube.dimensions.length} dimensions
                  </Badge>
                  {cube.segments.length > 0 && (
                    <Badge variant="outline">
                      {cube.segments.length} segments
                    </Badge>
                  )}
                </>
              }
              footer={
                <RowActions
                  actions={[
                    {
                      key: "view",
                      title: "View",
                      ariaLabel: `View ${cube.title || cube.name}`,
                      onClick: () =>
                        navigate(
                          `/semantics/cubes/${encodeURIComponent(cube.name)}`,
                        ),
                    },
                  ]}
                />
              }
            >
              <p className="line-clamp-3">
                {cube.description || "No description available."}
              </p>
            </ItemCard>
          ))}
        </ItemGrid>
      )}
    </div>
  );
}

function matchesSearch(value: unknown, query: string): boolean {
  const normalizedQuery = query.trim().toLowerCase();

  if (!normalizedQuery) return true;

  return searchableText(value).includes(normalizedQuery);
}

function searchableText(value: unknown): string {
  if (value === null || value === undefined) return "";
  if (typeof value === "string") return value.toLowerCase();
  if (typeof value === "number" || typeof value === "boolean") {
    return String(value).toLowerCase();
  }
  if (Array.isArray(value)) return value.map(searchableText).join(" ");
  if (typeof value === "object") {
    return Object.values(value as Record<string, unknown>)
      .map(searchableText)
      .join(" ");
  }

  return "";
}

function delay(ms: number) {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}
