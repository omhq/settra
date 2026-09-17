import { useEffect, useRef, useState, type FormEvent } from "react";
import { CheckCheck, GitBranch, Loader2, Plus, RefreshCw } from "lucide-react";
import { useAuth } from "@/auth/auth-provider";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { ItemCard, ItemGrid } from "@/components/ui/item-grid";
import { RowActions } from "@/components/ui/row-actions";
import { SelectMenu } from "@/components/ui/select-menu";
import { StateMessage } from "@/components/ui/state-message";
import { useModal } from "@/components/ui/global-modal";
import { waitForRefreshFeedback } from "@/lib/refresh-feedback";
import { OverlayEditor } from "./OverlayEditor";
import {
  api,
  type CollectionRelationship,
  type CollectionModelCatalog,
  type OverlayDraft,
  type RelationshipDraftInput,
} from "@/lib/api";

const emptyForm: RelationshipDraftInput = {
  source_cube: "",
  target_cube: "",
  source_member: "",
  target_member: "",
  source_primary_key: "",
  target_primary_key: "",
  relationship: "many_to_one",
};
type IntegrityResult = Awaited<
  ReturnType<typeof api.collections.validateRelationships>
>;

export function RelationshipsSection({
  collectionId,
  relationships,
  onChanged,
}: {
  collectionId: number;
  relationships: CollectionRelationship[];
  onChanged: () => void;
}) {
  const { session } = useAuth();
  const { openModal } = useModal();
  const canWrite = ["owner", "admin"].includes(
    session?.organization.role ?? "",
  );
  const [catalog, setCatalog] = useState<CollectionModelCatalog | null>(null);
  const [displayedRelationships, setDisplayedRelationships] =
    useState(relationships);
  const [form, setForm] = useState<RelationshipDraftInput | null>(null);
  const [draft, setDraft] = useState<OverlayDraft | null>(null);
  const [validation, setValidation] = useState<IntegrityResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [metadataError, setMetadataError] = useState<string | null>(null);
  const loadVersion = useRef(0);
  useEffect(() => {
    setDisplayedRelationships(relationships);
    void load();
    setValidation(null);
    return () => {
      loadVersion.current += 1;
    };
  }, [collectionId, relationships]);
  async function load(announce = false) {
    const version = ++loadVersion.current;
    const startedAt = Date.now();
    setRefreshing(true);
    setError(null);
    if (announce) setNotice(null);
    try {
      const [models, joins] = await Promise.all([
        api.collections.models(collectionId),
        api.collections.relationships(collectionId),
      ]);
      if (version !== loadVersion.current) return;
      setCatalog(models);
      setDisplayedRelationships(joins.relationships);
      setMetadataError(joins.cube.error);
      if (announce) setNotice("Relationships refreshed.");
    } catch (err: any) {
      if (version === loadVersion.current) setError(err.message);
    } finally {
      if (announce) await waitForRefreshFeedback(startedAt);
      if (version === loadVersion.current) setRefreshing(false);
    }
  }
  function startEdit(item?: CollectionRelationship) {
    setError(null);
    setNotice(null);
    setForm(
      item
        ? {
            source_cube: item.source_cube,
            target_cube: item.target_cube,
            source_member: item.source_member ?? "",
            target_member: item.target_member ?? "",
            relationship: item.relationship,
            source_primary_key:
              catalog?.cubes
                .find((cube) => cube.name === item.source_cube)
                ?.dimensions.find((dimension) => dimension.primary_key)?.name ??
              "",
            target_primary_key:
              catalog?.cubes
                .find((cube) => cube.name === item.target_cube)
                ?.dimensions.find((dimension) => dimension.primary_key)?.name ??
              "",
            existing_id: item.id,
          }
        : { ...emptyForm },
    );
  }
  async function prepare(event: FormEvent) {
    event.preventDefault();
    if (!form) return;
    setBusy(true);
    setError(null);
    try {
      setDraft(await api.collections.relationshipDraft(collectionId, form));
    } catch (err: any) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }
  function confirmRemove(item: CollectionRelationship) {
    openModal({
      title: "Remove relationship?",
      body: (
        <p>
          This removes the join between these tables. Their models, metrics, and
          synchronized data are retained. Queries that use this join may need to
          be updated. Review and validate the model change before saving.
        </p>
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
              void prepareRemove(item);
            }}
          >
            Review removal
          </Button>
        </>
      ),
    });
  }
  async function prepareRemove(item: CollectionRelationship) {
    setBusy(true);
    setError(null);
    try {
      setForm(null);
      setDraft(
        await api.collections.relationshipDraft(collectionId, {
          ...emptyForm,
          source_cube: item.source_cube,
          existing_id: item.id,
          remove: true,
        }),
      );
    } catch (err: any) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }
  async function validate() {
    setBusy(true);
    setError(null);
    setValidation(null);
    try {
      setValidation(await api.collections.validateRelationships(collectionId));
    } catch (err: any) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }
  const cubes = catalog?.cubes ?? [];
  const source = cubes.find((cube) => cube.name === form?.source_cube);
  const target = cubes.find((cube) => cube.name === form?.target_cube);
  const cubeOptions = cubes.map((cube) => ({
    value: cube.name,
    label: cube.title,
    description:
      cube.source_type === "generated_connection"
        ? "Synchronized source"
        : `Authored model · ${cube.name}`,
  }));
  const dimensions = (cube: typeof source) =>
    (cube?.dimensions ?? []).map((dimension) => ({
      value: dimension.name,
      label: dimension.title || dimension.name,
      description: `${dimension.type}${dimension.primary_key ? " · Unique row key" : ""}`,
    }));

  return (
    <div className="space-y-4">
      {error && (
        <StateMessage
          state="error"
          variant="banner"
          message={error}
          onClose={() => setError(null)}
        />
      )}
      {notice && (
        <StateMessage state="success" variant="banner" message={notice} />
      )}
      {metadataError && (
        <StateMessage
          state="warning"
          variant="banner"
          message={metadataError}
        />
      )}
      {draft ? (
        <OverlayEditor
          collectionId={collectionId}
          initial={draft}
          models={catalog?.models ?? []}
          title={
            form ? "Review relationship model" : "Review relationship removal"
          }
          onClose={() => setDraft(null)}
          onSaved={(message) => {
            setDraft(null);
            setForm(null);
            setNotice(message);
            setValidation(null);
            void load();
            onChanged();
          }}
        />
      ) : (
        <>
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <h2 className="text-lg font-semibold">Relationships</h2>
              <p className="mt-1 text-sm text-muted-foreground">
                Connect tables with matching keys and validate their cardinality
                against synchronized data.
              </p>
            </div>
            <div className="flex flex-wrap gap-2">
              <Button
                variant="outline"
                disabled={busy || refreshing}
                onClick={() => void load(true)}
                aria-label="Refresh relationships"
              >
                <RefreshCw
                  className={refreshing ? "size-4 animate-spin" : "size-4"}
                />
              </Button>
              <Button
                variant="outline"
                disabled={busy || refreshing || !displayedRelationships.length}
                onClick={() => void validate()}
              >
                {busy ? (
                  <Loader2 className="size-4 animate-spin" />
                ) : (
                  <CheckCheck className="size-4" />
                )}{" "}
                Validate relationships
              </Button>
              {canWrite && (
                <Button
                  disabled={busy || refreshing || !catalog}
                  onClick={() => startEdit()}
                >
                  <Plus className="size-4" /> Add relationship
                </Button>
              )}
            </div>
          </div>
          {form && (
            <form
              onSubmit={prepare}
              className="space-y-4 rounded-lg border bg-card p-4"
            >
              <h3 className="font-medium">
                {form.existing_id ? "Edit relationship" : "New relationship"}
              </h3>
              <div className="grid gap-4 md:grid-cols-2">
                <div className="space-y-3">
                  <label className="block space-y-1 text-sm">
                    <span>From table</span>
                    <SelectMenu
                      options={cubeOptions.filter(
                        (option) =>
                          cubes.find((cube) => cube.name === option.value)
                            ?.source_type !== "overlay",
                      )}
                      value={form.source_cube}
                      disabled={busy || !!form.existing_id}
                      onChange={(value) =>
                        setForm({
                          ...form,
                          source_cube: value,
                          source_member: "",
                          source_primary_key:
                            cubes
                              .find((cube) => cube.name === value)
                              ?.dimensions.find(
                                (dimension) => dimension.primary_key,
                              )?.name ?? "",
                        })
                      }
                      placeholder="Choose source table"
                    />
                  </label>
                  <label className="block space-y-1 text-sm">
                    <span>Matching key</span>
                    <SelectMenu
                      options={dimensions(source)}
                      value={form.source_member}
                      disabled={busy || !source}
                      onChange={(value) =>
                        setForm({
                          ...form,
                          source_member: value,
                          source_primary_key:
                            form.source_primary_key ||
                            (form.relationship !== "many_to_one" ? value : ""),
                        })
                      }
                      placeholder="Choose source key"
                    />
                  </label>
                  <label className="block space-y-1 text-sm">
                    <span>Unique row key</span>
                    <SelectMenu
                      options={dimensions(source)}
                      value={form.source_primary_key}
                      disabled={
                        busy ||
                        !source ||
                        !!source.dimensions.find(
                          (dimension) => dimension.primary_key,
                        )
                      }
                      onChange={(value) =>
                        setForm({ ...form, source_primary_key: value })
                      }
                      placeholder="Choose a unique row identifier"
                    />
                  </label>
                </div>
                <div className="space-y-3">
                  <label className="block space-y-1 text-sm">
                    <span>To table</span>
                    <SelectMenu
                      options={cubeOptions.filter(
                        (option) => option.value !== form.source_cube,
                      )}
                      value={form.target_cube}
                      disabled={busy}
                      onChange={(value) =>
                        setForm({
                          ...form,
                          target_cube: value,
                          target_member: "",
                          target_primary_key:
                            cubes
                              .find((cube) => cube.name === value)
                              ?.dimensions.find(
                                (dimension) => dimension.primary_key,
                              )?.name ?? "",
                        })
                      }
                      placeholder="Choose target table"
                    />
                  </label>
                  <label className="block space-y-1 text-sm">
                    <span>Matching key</span>
                    <SelectMenu
                      options={dimensions(target)}
                      value={form.target_member}
                      disabled={busy || !target}
                      onChange={(value) =>
                        setForm({
                          ...form,
                          target_member: value,
                          target_primary_key:
                            form.target_primary_key ||
                            (form.relationship !== "one_to_many" ? value : ""),
                        })
                      }
                      placeholder="Choose target key"
                    />
                  </label>
                  <label className="block space-y-1 text-sm">
                    <span>Unique row key</span>
                    <SelectMenu
                      options={dimensions(target)}
                      value={form.target_primary_key}
                      disabled={
                        busy ||
                        !target ||
                        !!target.dimensions.find(
                          (dimension) => dimension.primary_key,
                        )
                      }
                      onChange={(value) =>
                        setForm({ ...form, target_primary_key: value })
                      }
                      placeholder="Choose a unique row identifier"
                    />
                  </label>
                </div>
              </div>
              <label className="block max-w-md space-y-1 text-sm">
                <span>Relationship from source to target</span>
                <SelectMenu
                  options={[
                    {
                      value: "many_to_one",
                      label: "Many to one",
                      description: "Many source rows match one target row",
                    },
                    {
                      value: "one_to_many",
                      label: "One to many",
                      description: "One source row matches many target rows",
                    },
                    {
                      value: "one_to_one",
                      label: "One to one",
                      description: "One source row matches one target row",
                    },
                  ]}
                  value={form.relationship}
                  disabled={busy}
                  onChange={(value) =>
                    setForm({ ...form, relationship: value })
                  }
                />
              </label>
              <p className="text-xs text-muted-foreground">
                The unique row key identifies each table's rows. The matching
                key on each “one” side must be that table's unique row key.
                Source models are copied into an authored App model when needed.
                Use Semantic models for composite keys or other model changes.
              </p>
              <div className="flex flex-wrap justify-end gap-2">
                <Button
                  type="button"
                  variant="outline"
                  disabled={busy}
                  onClick={() => setForm(null)}
                >
                  Cancel
                </Button>
                <Button
                  type="submit"
                  disabled={
                    busy ||
                    !form.source_cube ||
                    !form.target_cube ||
                    !form.source_member ||
                    !form.target_member ||
                    !form.source_primary_key ||
                    !form.target_primary_key
                  }
                >
                  Review model change
                </Button>
              </div>
            </form>
          )}
          {!displayedRelationships.length ? (
            <StateMessage
              state="empty"
              variant="panel"
              title="No relationships"
              message="Add a relationship to connect two tables using their matching keys."
            />
          ) : (
            <ItemGrid>
              {displayedRelationships.map((item) => {
                const result = validation?.relationships.find(
                  (result) => result.id === item.id,
                );
                const title = (name: string) =>
                  cubes.find((cube) => cube.name === name)?.title || name;
                return (
                  <ItemCard
                    key={item.id}
                    title={
                      <span className="flex items-center gap-2">
                        <GitBranch className="size-4 shrink-0 text-muted-foreground" />
                        {title(item.source_cube)} {"->"}{" "}
                        {title(item.target_cube)}
                      </span>
                    }
                    pills={
                      <>
                        <Badge variant="secondary">
                          {item.relationship.replace(/_/g, " ")}
                        </Badge>
                        <Badge
                          variant={
                            item.valid && item.models_compiled
                              ? "success"
                              : "destructive"
                          }
                        >
                          {item.valid && item.models_compiled
                            ? "Compiled"
                            : "Needs attention"}
                        </Badge>
                        {result && (
                          <Badge
                            variant={result.valid ? "success" : "destructive"}
                          >
                            {result.valid ? "Validated" : "Validation failed"}
                          </Badge>
                        )}
                      </>
                    }
                    footer={
                      canWrite && item.source_type === "generated_overlay" ? (
                        <RowActions
                          actions={[
                            {
                              key: "edit",
                              title: "Edit relationship",
                              disabled: busy || !catalog,
                              onClick: () => startEdit(item),
                            },
                            {
                              key: "delete",
                              title: "Remove relationship",
                              disabled: busy,
                              onClick: () => confirmRemove(item),
                            },
                          ]}
                        />
                      ) : undefined
                    }
                  >
                    <p className="font-mono text-xs">
                      {item.source_member ?? "?"} = {item.target_member ?? "?"}
                    </p>
                    {item.issues.map((issue, index) => (
                      <p key={index} className="mt-2 text-xs text-destructive">
                        {issue.message}
                      </p>
                    ))}
                    {result && (
                      <div className="mt-3 space-y-1 text-xs">
                        <p>
                          Source rows: {result.data_integrity.source_row_count}{" "}
                          · Target rows:{" "}
                          {result.data_integrity.target_row_count}
                        </p>
                        <p>
                          Unmatched source rows:{" "}
                          {result.data_integrity.unmatched_source_row_count}
                        </p>
                        <p>
                          Duplicate keys:{" "}
                          {result.data_integrity.duplicate_source_key_count}{" "}
                          source ·{" "}
                          {result.data_integrity.duplicate_target_key_count}{" "}
                          target
                        </p>
                        <p>
                          Null keys:{" "}
                          {result.data_integrity.source_null_key_count} source ·{" "}
                          {result.data_integrity.target_null_key_count} target
                        </p>
                        {[result.cube_query.error, result.data_integrity.error]
                          .filter(Boolean)
                          .map((message, index) => (
                            <p key={index} className="text-destructive">
                              {message}
                            </p>
                          ))}
                      </div>
                    )}
                  </ItemCard>
                );
              })}
            </ItemGrid>
          )}
          {validation && (
            <StateMessage
              state={validation.valid ? "success" : "warning"}
              variant="banner"
              message={
                validation.valid
                  ? `All ${validation.relationship_count} relationships passed Cube and snapshot validation.`
                  : "Some relationships failed validation. Review their query errors and key counts."
              }
            />
          )}
        </>
      )}
    </div>
  );
}
