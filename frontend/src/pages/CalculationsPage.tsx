import {
  lazy,
  Suspense,
  useEffect,
  useMemo,
  useRef,
  useState,
  type FormEvent,
} from "react";
import {
  FileCode2,
  FolderTree,
  Loader2,
  Paintbrush,
  Plus,
  Save,
  Trash2,
} from "lucide-react";
import { useSearchParams } from "react-router-dom";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { useModal } from "@/components/ui/global-modal";
import { Input } from "@/components/ui/input";
import { ItemCard, ItemGrid } from "@/components/ui/item-grid";
import { RowActions } from "@/components/ui/row-actions";
import { SelectMenu } from "@/components/ui/select-menu";
import { StateMessage } from "@/components/ui/state-message";
import { CalculationRunner } from "@/components/collections/CalculationRunner";
import { Timestamp } from "@/components/ui/timestamp";
import type { YamlEditorHandle } from "@/components/ui/yaml-editor";
import {
  api,
  type Calculation,
  type CalculationSummary,
  type DataCollection,
} from "@/lib/api";

const YamlEditor = lazy(() =>
  import("@/components/ui/yaml-editor").then((module) => ({
    default: module.YamlEditor,
  })),
);

export default function CalculationsPage({
  collectionId,
  embedded = false,
  onChanged,
  refreshVersion = 0,
}: {
  collectionId?: number;
  embedded?: boolean;
  onChanged?: () => void;
  refreshVersion?: number;
}) {
  const { openModal } = useModal();
  const [searchParams, setSearchParams] = useSearchParams();
  const [calculations, setCalculations] = useState<CalculationSummary[]>([]);
  const [collections, setCollections] = useState<DataCollection[]>([]);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [editorOpen, setEditorOpen] = useState(false);
  const [calculation, setCalculation] = useState<Calculation | null>(null);
  const [content, setContent] = useState("");
  const [savedContent, setSavedContent] = useState("");
  const [loading, setLoading] = useState(true);
  const [calculationLoading, setCalculationLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [formatting, setFormatting] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const yamlEditorRef = useRef<YamlEditorHandle>(null);
  const calculationLoadVersion = useRef(0);
  const dirty = content !== savedContent;
  const requestedCalculationId = Number(searchParams.get("calculation"));
  const requestedCollectionId = Number(searchParams.get("collection"));
  const effectiveCollectionId =
    Number.isInteger(collectionId) && collectionId! > 0
      ? collectionId
      : Number.isInteger(requestedCollectionId)
        ? requestedCollectionId
        : undefined;

  const calculationOptions = useMemo(
    () =>
      calculations.map((item) => ({
        value: String(item.id),
        label: item.name,
        description: item.collection_name
          ? `${item.collection_name} · ${item.slug}`
          : `Unassigned · ${item.slug}`,
      })),
    [calculations],
  );
  const collectionOptions = useMemo(
    () =>
      collections.map((item) => ({
        value: String(item.id),
        label: item.name,
        description: `${item.pipe_count} sources · ${item.table_count} tables`,
      })),
    [collections],
  );

  useEffect(() => {
    void loadCalculations();
  }, [effectiveCollectionId, refreshVersion]);

  useEffect(() => {
    if (selectedId === null) {
      calculationLoadVersion.current += 1;
      setCalculationLoading(false);
      setCalculation(null);
      setContent("");
      setSavedContent("");
      return;
    }

    void loadCalculation(selectedId);
  }, [selectedId]);

  useEffect(() => {
    if (!dirty) return;

    function preventAccidentalClose(event: BeforeUnloadEvent) {
      event.preventDefault();
    }

    window.addEventListener("beforeunload", preventAccidentalClose);
    return () =>
      window.removeEventListener("beforeunload", preventAccidentalClose);
  }, [dirty]);

  async function loadCalculations() {
    setError(null);

    try {
      const [nextCalculations, nextCollections] = await Promise.all([
        embedded
          ? api.calculations.list(effectiveCollectionId)
          : api.calculations.list(),
        api.collections.list(),
      ]);
      setCalculations(nextCalculations);
      setCollections(nextCollections);
      setSelectedId((current) => {
        if (embedded) {
          if (
            current !== null &&
            nextCalculations.some((item) => item.id === current)
          ) {
            return current;
          }

          if (
            Number.isInteger(requestedCalculationId) &&
            nextCalculations.some((item) => item.id === requestedCalculationId)
          ) {
            return requestedCalculationId;
          }

          return null;
        }

        const collectionScoped =
          effectiveCollectionId !== undefined
            ? nextCalculations.filter(
                (item) => item.collection_id === effectiveCollectionId,
              )
            : nextCalculations;

        if (
          current !== null &&
          nextCalculations.some((item) => item.id === current)
        ) {
          return current;
        }

        if (
          Number.isInteger(requestedCalculationId) &&
          nextCalculations.some((item) => item.id === requestedCalculationId)
        ) {
          return requestedCalculationId;
        }

        if (effectiveCollectionId !== undefined) {
          return (
            nextCalculations.find(
              (item) => item.collection_id === effectiveCollectionId,
            )?.id ??
            collectionScoped[0]?.id ??
            null
          );
        }

        if (Number.isInteger(requestedCollectionId)) {
          return (
            nextCalculations.find(
              (item) => item.collection_id === requestedCollectionId,
            )?.id ??
            nextCalculations[0]?.id ??
            null
          );
        }

        return nextCalculations[0]?.id ?? null;
      });
    } catch (err: any) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  async function loadCalculation(id: number) {
    const version = ++calculationLoadVersion.current;
    setCalculationLoading(true);
    setError(null);

    try {
      const nextCalculation = await api.calculations.get(id);
      if (version !== calculationLoadVersion.current) return;
      setCalculation(nextCalculation);
      setContent(nextCalculation.content);
      setSavedContent(nextCalculation.content);
    } catch (err: any) {
      if (version === calculationLoadVersion.current) setError(err.message);
    } finally {
      if (version === calculationLoadVersion.current) {
        setCalculationLoading(false);
      }
    }
  }

  function selectCalculationForEdit(id: number) {
    setSelectedId(id);
    setEditorOpen(true);
  }

  function openCreateModal() {
    const targetCollectionId =
      effectiveCollectionId ?? calculation?.collection_id ?? collections[0]?.id;

    if (!targetCollectionId) {
      openModal({
        title: "Create an App first",
        body: (
          <p>
            Every calculation belongs to an App containing related sources,
            semantic models, inputs, and results.
          </p>
        ),
        actions: ({ close }) => (
          <Button to="/data/apps/new" onClick={close}>
            New App
          </Button>
        ),
      });
      return;
    }

    openModal({
      title: "New calculation",
      body: ({ close }) => (
        <CreateCalculationForm
          close={close}
          showCollectionSelect={!embedded}
          collectionOptions={
            embedded
              ? [
                  {
                    value: String(targetCollectionId),
                    label: "This App",
                  },
                ]
              : collectionOptions
          }
          initialCollectionId={targetCollectionId}
          onCreate={async (input) => {
            const created = await api.calculations.create(input);
            setCalculations((current) =>
              [...current, created].sort((left, right) =>
                left.name.localeCompare(right.name),
              ),
            );
            setSelectedId(created.id);
            setCalculation(created);
            setContent(created.content);
            setSavedContent(created.content);
            if (!embedded) {
              setSearchParams(
                {
                  collection: String(created.collection_id),
                  calculation: String(created.id),
                },
                { replace: true },
              );
            }
            setNotice(`${created.name} created.`);
            onChanged?.();
          }}
        />
      ),
      bodyClassName: "text-foreground",
    });
  }

  async function saveCalculation() {
    if (selectedId === null) return;

    setSaving(true);
    setError(null);
    setNotice(null);

    try {
      const updated = await api.calculations.update(
        selectedId,
        content,
        savedContent,
      );
      setCalculation(updated);
      setContent(updated.content);
      setSavedContent(updated.content);
      setCalculations((current) =>
        current.map((item) => (item.id === updated.id ? updated : item)),
      );
      if (embedded && updated.collection_id !== collectionId) {
        setCalculations((current) =>
          current.filter((item) => item.id !== updated.id),
        );
        setSelectedId(null);
        setEditorOpen(false);
      }
      onChanged?.();
      setNotice(`${updated.name} saved.`);
    } catch (err: any) {
      setError(err.message);
    } finally {
      setSaving(false);
    }
  }

  async function formatYaml() {
    setFormatting(true);
    setError(null);

    try {
      const formatted = await yamlEditorRef.current?.format();
      if (!formatted) setError("The YAML formatter is not ready yet.");
    } catch {
      setError(
        "Unable to format this YAML. Fix its syntax errors and try again.",
      );
    } finally {
      setFormatting(false);
    }
  }

  function selectCalculation(value: string) {
    const nextId = Number(value);
    if (!dirty) {
      commitCalculationSelection(nextId);
      return;
    }

    openModal({
      title: "Discard unsaved changes?",
      body: <p>Your changes to this calculation have not been saved.</p>,
      actions: ({ close }) => (
        <>
          <Button type="button" variant="outline" onClick={close}>
            Keep editing
          </Button>
          <Button
            type="button"
            variant="destructive"
            onClick={() => {
              close();
              commitCalculationSelection(nextId);
            }}
          >
            Discard changes
          </Button>
        </>
      ),
    });
  }

  function commitCalculationSelection(id: number) {
    setSelectedId(id);
    if (embedded) {
      return;
    }

    const selected = calculations.find((item) => item.id === id);
    const nextParams: Record<string, string> = { calculation: String(id) };
    const targetCollectionId = selected?.collection_id ?? effectiveCollectionId;
    if (targetCollectionId) {
      nextParams.collection = String(targetCollectionId);
    }
    setSearchParams(nextParams, { replace: true });
  }

  function closeEmbeddedEditor() {
    if (!dirty) {
      commitCloseEmbeddedEditor();
      return;
    }

    openModal({
      title: "Discard unsaved changes?",
      body: <p>Your changes to this calculation have not been saved.</p>,
      actions: ({ close }) => (
        <>
          <Button type="button" variant="outline" onClick={close}>
            Keep editing
          </Button>
          <Button
            type="button"
            variant="destructive"
            onClick={() => {
              close();
              commitCloseEmbeddedEditor();
            }}
          >
            Discard changes
          </Button>
        </>
      ),
    });
  }

  function commitCloseEmbeddedEditor() {
    setEditorOpen(false);
    setSelectedId(null);
  }

  function confirmDelete() {
    if (!calculation) return;

    const selected = calculation;
    openModal({
      title: "Delete calculation?",
      body: (
        <p>
          This permanently deletes{" "}
          <span className="font-medium text-foreground">{selected.name}</span>.
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
              void removeCalculation(selected);
            }}
          >
            Delete calculation
          </Button>
        </>
      ),
    });
  }

  async function removeCalculation(selected: Calculation) {
    setDeleting(true);
    setError(null);
    setNotice(null);

    try {
      await api.calculations.delete(selected.id);
      const remaining = calculations.filter((item) => item.id !== selected.id);
      setCalculations(remaining);
      setSelectedId(remaining[0]?.id ?? null);
      setNotice(`${selected.name} deleted.`);
      onChanged?.();
    } catch (err: any) {
      setError(err.message);
    } finally {
      setDeleting(false);
    }
  }

  if (loading) {
    return (
      <StateMessage
        state="loading"
        variant="page"
        message="Loading calculations"
      />
    );
  }

  return (
    <div className="flex h-full min-h-0 flex-col gap-5 overflow-hidden">
      {!embedded && (
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <h1 className="text-2xl font-semibold">Calculations</h1>
            <p className="mt-1 max-w-2xl text-sm text-muted-foreground">
              Define App-scoped calculations and their named outputs as YAML.
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <SelectMenu
              options={calculationOptions}
              value={selectedId === null ? null : String(selectedId)}
              onChange={selectCalculation}
              placeholder="Select calculation"
              disabled={!calculations.length || saving || deleting}
              className="w-full min-w-56 sm:w-64"
              triggerClassName="h-9"
            />
            <Button
              type="button"
              variant="outline"
              disabled={dirty || saving || deleting}
              title={dirty ? "Save or discard your changes first" : undefined}
              onClick={openCreateModal}
            >
              <Plus className="size-4" />
              New
            </Button>
            <Button
              type="button"
              variant="outline"
              size="icon"
              disabled={!calculation || saving || deleting}
              aria-label="Delete selected calculation"
              onClick={confirmDelete}
            >
              {deleting ? (
                <Loader2 className="size-4 animate-spin" />
              ) : (
                <Trash2 className="size-4" />
              )}
            </Button>
            <Button
              type="button"
              variant="outline"
              disabled={!calculation || calculationLoading || formatting}
              onClick={() => void formatYaml()}
            >
              {formatting ? (
                <Loader2 className="size-4 animate-spin" />
              ) : (
                <Paintbrush className="size-4" />
              )}
              Format
            </Button>
            {calculation &&
              !calculationLoading &&
              calculation.id === selectedId && (
                <CalculationRunner
                  key={`run-${calculation.id}`}
                  id={calculation.id}
                  content={content}
                  disabled={saving || deleting}
                />
              )}
            <Button
              type="button"
              disabled={!dirty || saving || deleting || !calculation}
              onClick={() => void saveCalculation()}
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
      )}

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

      {embedded && !editorOpen && (
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h2 className="text-lg font-semibold">Calculations</h2>
          <Button type="button" onClick={openCreateModal}>
            <Plus className="size-4" /> Add calculation
          </Button>
        </div>
      )}

      {embedded && editorOpen ? (
        <section className="flex h-[calc(100dvh-18rem)] min-h-[32rem] flex-col overflow-hidden rounded-lg border bg-card">
          <div className="flex flex-wrap items-center justify-between gap-2 border-b px-4 py-3">
            <div className="min-w-0">
              <div className="flex min-w-0 items-center gap-2">
                <FileCode2 className="size-4 shrink-0 text-muted-foreground" />
                <h2 className="truncate text-sm font-medium">
                  {calculation?.name ?? "Calculation"}
                </h2>
                <Badge variant="outline">YAML draft</Badge>
                {calculation && !calculation.collection_id && (
                  <Badge variant="secondary">Unassigned</Badge>
                )}
                {dirty && <Badge variant="secondary">Unsaved</Badge>}
              </div>
              {calculation && (
                <p className="mt-1 text-xs text-muted-foreground">
                  {calculation.slug}.yaml | Updated{" "}
                  <Timestamp value={calculation.updated_at} />
                </p>
              )}
            </div>
            <div className="flex items-center gap-2">
              <Button
                type="button"
                variant="outline"
                disabled={saving || deleting}
                onClick={closeEmbeddedEditor}
              >
                Cancel
              </Button>
              <Button
                type="button"
                variant="outline"
                size="icon"
                disabled={!calculation || saving || deleting}
                aria-label="Delete selected calculation"
                onClick={confirmDelete}
              >
                {deleting ? (
                  <Loader2 className="size-4 animate-spin" />
                ) : (
                  <Trash2 className="size-4" />
                )}
              </Button>
              <Button
                type="button"
                variant="outline"
                disabled={!calculation || calculationLoading || formatting}
                onClick={() => void formatYaml()}
              >
                {formatting ? (
                  <Loader2 className="size-4 animate-spin" />
                ) : (
                  <Paintbrush className="size-4" />
                )}
                Format
              </Button>
              {calculation &&
                !calculationLoading &&
                calculation.id === selectedId && (
                  <CalculationRunner
                    key={`run-${calculation.id}`}
                    id={calculation.id}
                    content={content}
                    disabled={saving || deleting}
                  />
                )}
              <Button
                type="button"
                disabled={!dirty || saving || deleting || !calculation}
                onClick={() => void saveCalculation()}
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

          {calculationLoading ||
          !calculation ||
          calculation.id !== selectedId ? (
            <StateMessage
              state="loading"
              variant="panel"
              message="Loading calculation"
            />
          ) : (
            <div className="min-h-0 flex-1 overflow-hidden rounded-b-lg bg-background">
              <Suspense
                fallback={
                  <StateMessage
                    state="loading"
                    variant="panel"
                    message="Loading YAML editor"
                  />
                }
              >
                <YamlEditor
                  key={calculation.id}
                  ref={yamlEditorRef}
                  ariaLabel="Calculation YAML"
                  path={`calculations/${calculation?.slug ?? "draft"}.yaml`}
                  value={content}
                  onChange={setContent}
                />
              </Suspense>
            </div>
          )}
        </section>
      ) : (
        <>
          {calculations.length === 0 ? (
            <StateMessage
              state="empty"
              variant="panel"
              title="No calculations"
              message="Create a calculation to start drafting its YAML definition."
              action={
                <Button type="button" onClick={openCreateModal}>
                  <Plus className="size-4" />
                  {embedded ? "Add calculation" : "New calculation"}
                </Button>
              }
            />
          ) : (
            <>
              {embedded && (
                <ItemGrid>
                  {calculations.map((item) => (
                    <ItemCard
                      key={item.id}
                      title={
                        <button
                          type="button"
                          className="cursor-pointer text-left hover:text-primary hover:underline"
                          onClick={() => selectCalculationForEdit(item.id)}
                        >
                          {item.name}
                        </button>
                      }
                      pills={<Badge variant="outline">YAML</Badge>}
                      footer={
                        <RowActions
                          actions={[
                            {
                              key: "edit",
                              title: "Edit calculation",
                              onClick: () => selectCalculationForEdit(item.id),
                            },
                          ]}
                        />
                      }
                    >
                      <p className="font-mono text-xs text-muted-foreground">
                        {item.slug}.yaml
                      </p>
                    </ItemCard>
                  ))}
                </ItemGrid>
              )}
            </>
          )}

          {!embedded && (
            <section className="flex min-h-[32rem] flex-1 flex-col overflow-hidden rounded-lg border bg-card">
              <div className="flex flex-wrap items-center justify-between gap-2 border-b px-4 py-3">
                <div className="min-w-0">
                  <div className="flex min-w-0 items-center gap-2">
                    <FileCode2 className="size-4 shrink-0 text-muted-foreground" />
                    <h2 className="truncate text-sm font-medium">
                      {calculation?.name ?? "Calculation"}
                    </h2>
                    <Badge variant="outline">YAML draft</Badge>
                    {!embedded && calculation?.collection_name && (
                      <Badge variant="secondary">
                        <FolderTree className="size-3" />
                        {calculation.collection_name}
                      </Badge>
                    )}
                    {calculation && !calculation.collection_id && (
                      <Badge variant="secondary">Unassigned</Badge>
                    )}
                    {dirty && <Badge variant="secondary">Unsaved</Badge>}
                  </div>
                  {calculation && (
                    <p className="mt-1 text-xs text-muted-foreground">
                      {calculation.slug}.yaml | Updated{" "}
                      <Timestamp value={calculation.updated_at} />
                    </p>
                  )}
                </div>
                <p className="text-xs text-muted-foreground">
                  App-owned definition
                </p>
              </div>

              {calculationLoading ||
              !calculation ||
              calculation.id !== selectedId ? (
                <StateMessage
                  state="loading"
                  variant="panel"
                  message="Loading calculation"
                />
              ) : (
                <div className="min-h-0 flex-1 overflow-hidden rounded-b-lg bg-background">
                  <Suspense
                    fallback={
                      <StateMessage
                        state="loading"
                        variant="panel"
                        message="Loading YAML editor"
                      />
                    }
                  >
                    <YamlEditor
                      key={calculation.id}
                      ref={yamlEditorRef}
                      ariaLabel="Calculation YAML"
                      path={`calculations/${calculation?.slug ?? "draft"}.yaml`}
                      value={content}
                      onChange={setContent}
                    />
                  </Suspense>
                </div>
              )}
            </section>
          )}
        </>
      )}
    </div>
  );
}

function CreateCalculationForm({
  close,
  showCollectionSelect,
  collectionOptions,
  initialCollectionId,
  onCreate,
}: {
  close: () => void;
  showCollectionSelect: boolean;
  collectionOptions: {
    value: string;
    label: string;
    description?: string;
  }[];
  initialCollectionId: number;
  onCreate: (input: {
    collection_id: number;
    name: string;
    content: string;
  }) => Promise<void>;
}) {
  const [name, setName] = useState("");
  const [collectionId, setCollectionId] = useState(String(initialCollectionId));
  const [initialContent, setInitialContent] = useState("");
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!name.trim() || !collectionId || !initialContent.trim()) return;

    setCreating(true);
    setError(null);

    try {
      await onCreate({
        collection_id: Number(collectionId),
        name: name.trim(),
        content: initialContent,
      });
      close();
    } catch (err: any) {
      setError(err.message);
      setCreating(false);
    }
  }

  return (
    <form className="space-y-4" onSubmit={(event) => void submit(event)}>
      <div>
        <label className="text-sm font-medium" htmlFor="calculation-name">
          Name
        </label>
        <Input
          id="calculation-name"
          className="mt-2"
          value={name}
          maxLength={120}
          autoFocus
          placeholder="Monthly revenue"
          disabled={creating}
          onChange={(event) => setName(event.target.value)}
        />
      </div>
      {showCollectionSelect && (
        <div>
          <label className="text-sm font-medium">App</label>
          <SelectMenu
            options={collectionOptions}
            value={collectionId}
            onChange={setCollectionId}
            placeholder="Select App"
            disabled={creating}
            className="mt-2 w-full"
          />
        </div>
      )}
      <div>
        <label className="text-sm font-medium" htmlFor="calculation-yaml">
          YAML definition
        </label>
        <textarea
          id="calculation-yaml"
          rows={10}
          value={initialContent}
          spellCheck={false}
          disabled={creating}
          placeholder="Enter the initial calculation YAML"
          className="mt-2 w-full resize-y rounded-lg border border-input bg-transparent px-2.5 py-2 font-mono text-xs leading-5 outline-none placeholder:text-muted-foreground focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 dark:bg-input/30"
          onChange={(event) => setInitialContent(event.target.value)}
        />
        <p className="mt-2 text-xs text-muted-foreground">
          No starter definition is inserted automatically. Use a
          <span className="mx-1 font-mono text-foreground">
            calculation_output
          </span>
          node to consume a named output from another calculation in this App.
        </p>
      </div>
      {error && <p className="mt-3 text-sm text-destructive">{error}</p>}
      <div className="flex flex-col-reverse gap-2 pt-1 sm:flex-row sm:justify-end">
        <Button
          type="button"
          variant="outline"
          disabled={creating}
          onClick={close}
        >
          Cancel
        </Button>
        <Button
          type="submit"
          disabled={
            !name.trim() || !collectionId || !initialContent.trim() || creating
          }
        >
          {creating && <Loader2 className="size-4 animate-spin" />}
          Create calculation
        </Button>
      </div>
    </form>
  );
}
