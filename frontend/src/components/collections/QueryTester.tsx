import { useMemo, useState } from "react";
import { Braces, CheckCheck, Loader2, Play } from "lucide-react";

import { Button } from "@/components/ui/button";
import { useModal } from "@/components/ui/global-modal";
import { Input } from "@/components/ui/input";
import { SelectMenu } from "@/components/ui/select-menu";
import { StateMessage } from "@/components/ui/state-message";
import { StructuredDataEditor } from "@/components/ui/structured-data-editor";
import {
  api,
  type CollectionSemanticModel,
  type CubeMetaMember,
  type OverlayDraft,
  type OverlayValidation,
} from "@/lib/api";

type QueryMode = "builder" | "json";

export function QueryTester({
  collectionId,
  models,
  initialCubeName,
  draft,
  disabled = false,
  onValidated,
}: {
  collectionId: number;
  models: CollectionSemanticModel[];
  initialCubeName?: string;
  draft?: OverlayDraft;
  disabled?: boolean;
  onValidated?: (validation: OverlayValidation) => void;
}) {
  const { openModal } = useModal();

  return (
    <Button
      type="button"
      variant="outline"
      disabled={disabled || (!draft && models.length === 0)}
      onClick={() =>
        openModal({
          title: draft ? "Validate and run" : "Run semantic query",
          body: (
            <SemanticQueryRunForm
              collectionId={collectionId}
              models={models}
              initialCubeName={initialCubeName}
              draft={draft}
              onValidated={onValidated}
            />
          ),
          dialogClassName:
            "max-h-[calc(100dvh-2rem)] max-w-4xl overflow-hidden",
          bodyClassName:
            "max-h-[calc(100dvh-7rem)] overflow-y-auto pr-1 text-foreground",
          closeOnBackdrop: false,
        })
      }
    >
      <Play className="size-4" /> Run
    </Button>
  );
}

function SemanticQueryRunForm({
  collectionId,
  models,
  initialCubeName,
  draft,
  onValidated,
}: {
  collectionId: number;
  models: CollectionSemanticModel[];
  initialCubeName?: string;
  draft?: OverlayDraft;
  onValidated?: (validation: OverlayValidation) => void;
}) {
  const initialModel =
    models.find((item) => item.name === initialCubeName) ??
    models.find((item) => item.in_scope && (draft || item.compile.compiled)) ??
    models[0];
  const initialSelection = querySelection(initialModel);
  const [cubeName, setCubeName] = useState(initialModel?.name ?? "");
  const [measures, setMeasures] = useState(initialSelection.measures);
  const [dimensions, setDimensions] = useState(initialSelection.dimensions);
  const [segments, setSegments] = useState<string[]>([]);
  const [limit, setLimit] = useState(10);
  const [mode, setMode] = useState<QueryMode>("builder");
  const [jsonQuery, setJsonQuery] = useState(() =>
    formatQuery(
      buildQuery(
        initialSelection.measures,
        initialSelection.dimensions,
        [],
        10,
      ),
    ),
  );
  const [validation, setValidation] = useState<OverlayValidation | null>(null);
  const [rows, setRows] = useState<Record<string, unknown>[] | null>(null);
  const [activity, setActivity] = useState<"validating" | "running" | null>(
    null,
  );
  const [error, setError] = useState<string | null>(null);

  const model = models.find((item) => item.name === cubeName) ?? initialModel;
  const visibleMeasures = useMemo(
    () => selectableMembers(model?.meta.measures ?? []),
    [model],
  );
  const visibleDimensions = useMemo(
    () => selectableMembers(model?.meta.dimensions ?? []),
    [model],
  );
  const visibleSegments = useMemo(
    () => selectableMembers(model?.meta.segments ?? []),
    [model],
  );
  const unavailable = activity !== null;
  const modelCanRun = draft
    ? true
    : Boolean(model?.in_scope && model.compile.compiled);

  function clearResponse() {
    setError(null);
    setRows(null);
  }

  function selectModel(value: string) {
    const nextModel = models.find((item) => item.name === value);
    const selection = querySelection(nextModel);
    setCubeName(value);
    setMeasures(selection.measures);
    setDimensions(selection.dimensions);
    setSegments([]);
    setMode("builder");
    setJsonQuery(
      formatQuery(
        buildQuery(selection.measures, selection.dimensions, [], limit),
      ),
    );
    clearResponse();
  }

  function updateSelection(
    kind: "measures" | "dimensions" | "segments",
    member: string,
    selected: boolean,
  ) {
    const update = (current: string[]) =>
      selected
        ? [...new Set([...current, member])]
        : current.filter((item) => item !== member);

    if (kind === "measures") setMeasures(update);
    if (kind === "dimensions") setDimensions(update);
    if (kind === "segments") setSegments(update);
    clearResponse();
  }

  function currentQuery(): Record<string, unknown> {
    if (mode === "json") {
      const parsed: unknown = JSON.parse(jsonQuery);
      if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
        throw new Error("Advanced query JSON must contain one query object.");
      }
      return parsed as Record<string, unknown>;
    }

    if (measures.length + dimensions.length === 0) {
      throw new Error("Choose at least one measure or dimension to run.");
    }

    return buildQuery(measures, dimensions, segments, limit);
  }

  async function validateModel() {
    if (!draft) return;
    setActivity("validating");
    setError(null);
    setRows(null);
    try {
      const result = await api.collections.validateOverlay(
        collectionId,
        draft,
        [],
      );
      setValidation(result);
      onValidated?.(result);
    } catch (err: any) {
      setError(err.message);
    } finally {
      setActivity(null);
    }
  }

  async function run() {
    setActivity("running");
    setError(null);
    setRows(null);
    try {
      const query = currentQuery();
      if (draft) {
        const result = await api.collections.validateOverlay(
          collectionId,
          draft,
          [
            {
              description: `Preview ${model?.meta.title || model?.name || "semantic model"}`,
              query,
            },
          ],
        );
        const queryResult = result.test_queries[0] ?? null;
        setValidation(result);
        setRows(queryResult?.data ?? null);
        onValidated?.(result);
      } else {
        const response = await api.collections.query(collectionId, query);
        setRows(response.data);
      }
    } catch (err: any) {
      setError(err.message);
    } finally {
      setActivity(null);
    }
  }

  const modelOptions = models.map((item) => ({
    value: item.name,
    label: item.meta.title || item.name,
    description: `${item.meta.measures.length} measures · ${item.meta.dimensions.length} dimensions`,
    disabled: !item.in_scope || (!draft && !item.compile.compiled),
  }));

  return (
    <section className="space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="max-w-2xl text-xs text-muted-foreground">
          {draft
            ? "Uses the current YAML draft, including unsaved changes. The draft is compiled temporarily and restored after the test."
            : "Build a bounded query from this artifact’s published measures and dimensions."}
        </p>
        <div className="flex flex-wrap gap-2">
          {draft && (
            <Button
              type="button"
              variant="outline"
              disabled={unavailable}
              onClick={() => void validateModel()}
            >
              {activity === "validating" ? (
                <Loader2 className="size-4 animate-spin" />
              ) : (
                <CheckCheck className="size-4" />
              )}{" "}
              Validate model
            </Button>
          )}
          <Button
            type="button"
            disabled={unavailable || !modelCanRun}
            onClick={() => void run()}
          >
            {activity === "running" ? (
              <Loader2 className="size-4 animate-spin" />
            ) : (
              <Play className="size-4" />
            )}{" "}
            Run query
          </Button>
        </div>
      </div>

      {error && <StateMessage state="error" variant="banner" message={error} />}
      {!modelCanRun && model && (
        <StateMessage
          state="warning"
          variant="banner"
          message={
            !model.in_scope
              ? "This model has unavailable dependencies and cannot be queried."
              : "Cube has not confirmed this saved model revision yet. Validate or repair it before running a query."
          }
        />
      )}

      <label className="block max-w-lg space-y-1 text-sm">
        <span>Semantic model</span>
        <SelectMenu
          value={cubeName}
          options={modelOptions}
          disabled={unavailable}
          onChange={selectModel}
          placeholder="Choose a model"
        />
      </label>

      <div className="flex gap-2 border-b pb-3">
        <Button
          type="button"
          variant={mode === "builder" ? "primary" : "outline"}
          disabled={unavailable}
          onClick={() => {
            setMode("builder");
            clearResponse();
          }}
        >
          Build query
        </Button>
        <Button
          type="button"
          variant={mode === "json" ? "primary" : "outline"}
          disabled={unavailable}
          onClick={() => {
            setJsonQuery(
              formatQuery(buildQuery(measures, dimensions, segments, limit)),
            );
            setMode("json");
            clearResponse();
          }}
        >
          <Braces className="size-4" /> Advanced JSON
        </Button>
      </div>

      {mode === "builder" ? (
        <div className="space-y-5">
          <MemberPicker
            title="Measures"
            description="Numbers to calculate, such as revenue, count, or average."
            members={visibleMeasures}
            selected={measures}
            disabled={unavailable}
            onChange={(member, selected) =>
              updateSelection("measures", member, selected)
            }
          />
          <MemberPicker
            title="Dimensions"
            description="Fields used to group or describe each result row."
            members={visibleDimensions}
            selected={dimensions}
            disabled={unavailable}
            onChange={(member, selected) =>
              updateSelection("dimensions", member, selected)
            }
          />
          {visibleSegments.length > 0 && (
            <MemberPicker
              title="Segments"
              description="Saved model conditions used to narrow the result."
              members={visibleSegments}
              selected={segments}
              disabled={unavailable}
              onChange={(member, selected) =>
                updateSelection("segments", member, selected)
              }
            />
          )}
          <label className="block max-w-32 space-y-1 text-sm">
            <span>Row limit</span>
            <Input
              type="number"
              min={1}
              max={500}
              value={limit}
              disabled={unavailable}
              onChange={(event) => {
                setLimit(
                  Math.min(500, Math.max(1, Number(event.target.value))),
                );
                clearResponse();
              }}
            />
          </label>
        </div>
      ) : (
        <div className="space-y-1 text-sm">
          <p>Cube REST query</p>
          <StructuredDataEditor
            className="h-64"
            language="json"
            ariaLabel="Cube REST query JSON"
            path={`semantic-queries/collection-${collectionId}.json`}
            value={jsonQuery}
            readOnly={unavailable}
            onChange={(value) => {
              setJsonQuery(value);
              clearResponse();
            }}
          />
          <span className="block text-xs text-muted-foreground">
            Use this only for filters, time dimensions, ordering, or
            joined-model queries that the guided builder does not cover.
          </span>
        </div>
      )}

      {validation && <ValidationResult validation={validation} />}
      {rows && <QueryResultTable rows={rows} />}
    </section>
  );
}

function MemberPicker({
  title,
  description,
  members,
  selected,
  disabled,
  onChange,
}: {
  title: string;
  description: string;
  members: CubeMetaMember[];
  selected: string[];
  disabled: boolean;
  onChange: (member: string, selected: boolean) => void;
}) {
  return (
    <fieldset className="space-y-2" disabled={disabled}>
      <legend className="text-sm font-medium">{title}</legend>
      <p className="text-xs text-muted-foreground">{description}</p>
      {members.length > 0 ? (
        <div className="grid max-h-44 gap-2 overflow-y-auto rounded-lg border p-2 sm:grid-cols-2">
          {members.map((member) => (
            <label
              key={member.name}
              className="flex cursor-pointer items-start gap-2 rounded-md p-2 hover:bg-muted"
            >
              <input
                type="checkbox"
                className="mt-0.5 size-4 accent-primary"
                checked={selected.includes(member.name)}
                onChange={(event) =>
                  onChange(member.name, event.target.checked)
                }
              />
              <span className="min-w-0">
                <span className="block truncate text-sm font-medium">
                  {member.shortTitle ||
                    member.title ||
                    localMemberName(member.name)}
                </span>
                <span className="block truncate font-mono text-[11px] text-muted-foreground">
                  {localMemberName(member.name)}
                </span>
              </span>
            </label>
          ))}
        </div>
      ) : (
        <p className="rounded-lg border border-dashed p-3 text-xs text-muted-foreground">
          No published {title.toLowerCase()} are available on this model.
        </p>
      )}
    </fieldset>
  );
}

function ValidationResult({ validation }: { validation: OverlayValidation }) {
  const ready = validation.ready_to_save && !validation.cleanup.error;

  return (
    <div className="space-y-2 border-t pt-4">
      <StateMessage
        state={ready ? "success" : "warning"}
        variant="banner"
        message={
          ready
            ? "Model validation passed. The current draft is ready to save."
            : "Model validation needs attention before this draft can be saved."
        }
      />
      {validation.errors.map((issue, index) => (
        <StateMessage
          key={`error-${index}`}
          state="error"
          variant="banner"
          message={[issue.message, issue.detail].filter(Boolean).join(" ")}
        />
      ))}
      {validation.warnings.map((issue, index) => (
        <StateMessage
          key={`warning-${index}`}
          state="warning"
          variant="banner"
          message={[issue.message, issue.detail].filter(Boolean).join(" ")}
        />
      ))}
      {validation.cleanup.error && (
        <StateMessage
          state="error"
          variant="banner"
          message={validation.cleanup.error}
        />
      )}
      {validation.test_queries.map((query, index) => (
        <StateMessage
          key={`query-${index}`}
          state={query.success ? "success" : "error"}
          variant="banner"
          message={
            query.success
              ? `${query.description}: ${query.row_count} rows returned.`
              : `${query.description}: ${query.error || "Query failed."}`
          }
        />
      ))}
    </div>
  );
}

function QueryResultTable({ rows }: { rows: Record<string, unknown>[] }) {
  const columns = Object.keys(rows[0] ?? {});

  return (
    <div className="space-y-2 border-t pt-4">
      <StateMessage
        state="success"
        variant="banner"
        message={`Query completed successfully. ${rows.length} rows returned.`}
      />
      {rows.length === 0 ? (
        <StateMessage
          state="empty"
          variant="panel"
          title="No matching rows"
          message="The query is valid, but no data matched the selected members and conditions."
        />
      ) : (
        <div className="max-h-96 overflow-auto rounded-md border">
          <table className="w-full text-left text-xs">
            <thead className="sticky top-0 bg-muted">
              <tr>
                {columns.map((column) => (
                  <th
                    key={column}
                    className="whitespace-nowrap px-3 py-2 font-medium"
                  >
                    {column}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((row, index) => (
                <tr key={index} className="border-t">
                  {columns.map((column) => (
                    <td key={column} className="whitespace-nowrap px-3 py-2">
                      {display(row[column])}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function selectableMembers(members: CubeMetaMember[]): CubeMetaMember[] {
  return members.filter(
    (member) => member.public !== false && member.isVisible !== false,
  );
}

function querySelection(model?: CollectionSemanticModel): {
  measures: string[];
  dimensions: string[];
} {
  const measures = selectableMembers(model?.meta.measures ?? []);
  const dimensions = selectableMembers(model?.meta.dimensions ?? []);

  return {
    measures: measures[0] ? [measures[0].name] : [],
    dimensions: dimensions[0] ? [dimensions[0].name] : [],
  };
}

function buildQuery(
  measures: string[],
  dimensions: string[],
  segments: string[],
  limit: number,
): Record<string, unknown> {
  return {
    ...(measures.length ? { measures } : {}),
    ...(dimensions.length ? { dimensions } : {}),
    ...(segments.length ? { segments } : {}),
    limit,
  };
}

function formatQuery(query: Record<string, unknown>): string {
  return JSON.stringify(query, null, 2);
}

function localMemberName(name: string): string {
  return name.split(".").pop() ?? name;
}

function display(value: unknown): string {
  if (value === null || value === undefined) return "—";
  return typeof value === "object" ? JSON.stringify(value) : String(value);
}
