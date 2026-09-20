import { useEffect, useRef, useState } from "react";
import { CheckCheck, Loader2, Play } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useModal } from "@/components/ui/global-modal";
import { Input } from "@/components/ui/input";
import { SelectMenu } from "@/components/ui/select-menu";
import { StateMessage } from "@/components/ui/state-message";
import { api, type CalculationValidation } from "@/lib/api";

type Parameter = CalculationValidation["parameters"][number];
type QueryResult = {
  kind: string;
  value?: unknown;
  columns?: string[];
  rows?: Record<string, unknown>[];
  row_count?: number;
  has_more?: boolean;
};
type Execution = {
  target_node_id?: string | null;
  ok: boolean;
  duration_ms: number;
  execution_order: string[];
  result?: QueryResult;
  outputs?: Record<string, { node_id: string; result: QueryResult }>;
};
type RunScope =
  | { kind: "selectable" }
  | { kind: "graph" }
  | { kind: "node"; nodeId: string };

export function CalculationRunner({
  id,
  content,
  disabled = false,
}: {
  id: number;
  content: string;
  disabled?: boolean;
}) {
  return (
    <DefinitionRunner
      content={content}
      disabled={disabled}
      subject="calculation"
      scope={{ kind: "selectable" }}
      modalTitle="Run calculation"
      triggerLabel="Run"
      triggerVariant="outline"
      validate={(draft, targetNodeId) =>
        api.calculations.validate(id, draft, targetNodeId)
      }
      execute={(draft, target, parameters) =>
        api.calculations.execute(id, draft, target, parameters)
      }
      parameterOptions={(parameter, draft, search) =>
        api.calculations.parameterOptions(id, parameter, draft, search)
      }
    />
  );
}

export function GraphRunner({
  collectionId,
  content,
  disabled = false,
  targetNodeId,
  buttonLabel,
}: {
  collectionId: number;
  content: string;
  disabled?: boolean;
  targetNodeId?: string;
  buttonLabel?: string;
}) {
  const scope: RunScope = targetNodeId
    ? { kind: "node", nodeId: targetNodeId }
    : { kind: "graph" };

  return (
    <DefinitionRunner
      content={content}
      disabled={disabled}
      subject="graph"
      scope={scope}
      modalTitle={targetNodeId ? `Run ${targetNodeId}` : "Run graph"}
      triggerLabel={buttonLabel ?? ""}
      triggerVariant={targetNodeId ? "primary" : "outline"}
      validate={(draft, validationTarget) =>
        api.collections.validateGraph(collectionId, draft, validationTarget)
      }
      execute={(draft, target, parameters) =>
        api.collections.executeGraph(collectionId, draft, target, parameters)
      }
      parameterOptions={(parameter, draft, search) =>
        api.collections.graphParameterOptions(
          collectionId,
          parameter,
          draft,
          search,
        )
      }
    />
  );
}

function DefinitionRunner({
  content,
  disabled,
  subject,
  scope,
  modalTitle,
  triggerLabel,
  triggerVariant,
  validate,
  execute,
  parameterOptions,
}: {
  content: string;
  disabled: boolean;
  subject: "calculation" | "graph";
  scope: RunScope;
  modalTitle: string;
  triggerLabel: string;
  triggerVariant: "primary" | "outline";
  validate: (
    content: string,
    targetNodeId: string | null,
  ) => Promise<CalculationValidation>;
  execute: (
    content: string,
    targetNodeId: string | null,
    parameters: Record<string, unknown>,
  ) => Promise<Record<string, unknown>>;
  parameterOptions: (
    parameter: string,
    content: string,
    search: string,
  ) => Promise<{ options: (string | boolean)[]; has_more: boolean }>;
}) {
  const { openModal } = useModal();

  return (
    <Button
      type="button"
      variant={triggerVariant}
      size={triggerLabel ? "default" : "icon"}
      disabled={disabled}
      aria-label={modalTitle}
      title={modalTitle}
      onClick={() =>
        openModal({
          title: modalTitle,
          body: (
            <DefinitionRunForm
              content={content}
              disabled={disabled}
              subject={subject}
              scope={scope}
              validateDefinition={validate}
              executeDefinition={execute}
              parameterOptions={parameterOptions}
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
      <Play className="size-4" />
      {triggerLabel}
    </Button>
  );
}

function DefinitionRunForm({
  content,
  disabled,
  subject,
  scope,
  validateDefinition,
  executeDefinition,
  parameterOptions,
}: {
  content: string;
  disabled: boolean;
  subject: "calculation" | "graph";
  scope: RunScope;
  validateDefinition: (
    content: string,
    targetNodeId: string | null,
  ) => Promise<CalculationValidation>;
  executeDefinition: (
    content: string,
    targetNodeId: string | null,
    parameters: Record<string, unknown>,
  ) => Promise<Record<string, unknown>>;
  parameterOptions: (
    parameter: string,
    content: string,
    search: string,
  ) => Promise<{ options: (string | boolean)[]; has_more: boolean }>;
}) {
  const [validation, setValidation] = useState<CalculationValidation | null>(
    null,
  );
  const [target, setTarget] = useState("");
  const [parameters, setParameters] = useState<Record<string, unknown>>({});
  const [execution, setExecution] = useState<Execution | null>(null);
  const [activity, setActivity] = useState<"validating" | "running" | null>(
    "validating",
  );
  const [error, setError] = useState<string | null>(null);
  const [stale, setStale] = useState(false);
  const validationTarget = scope.kind === "node" ? scope.nodeId : null;
  const executionTarget =
    scope.kind === "selectable" ? target || null : validationTarget;
  const latestInput = useRef({ content, target: executionTarget, parameters });
  const runner = useRef({
    validateDefinition,
    executeDefinition,
    parameterOptions,
  });
  latestInput.current = { content, target: executionTarget, parameters };
  runner.current = { validateDefinition, executeDefinition, parameterOptions };

  useEffect(() => {
    let active = true;

    async function loadValidation() {
      setError(null);
      try {
        const result = await runner.current.validateDefinition(
          content,
          validationTarget,
        );
        if (active) setValidation(result);
      } catch (err: any) {
        if (active) setError(err.message);
      } finally {
        if (active) setActivity(null);
      }
    }

    void loadValidation();
    return () => {
      active = false;
    };
  }, [content, validationTarget]);

  async function validate() {
    setActivity("validating");
    setError(null);
    try {
      const result = await validateDefinition(content, validationTarget);
      if (
        latestInput.current.content === content &&
        latestInput.current.target === executionTarget
      ) {
        setValidation(result);
      }
    } catch (err: any) {
      setError(err.message);
    } finally {
      setActivity(null);
    }
  }
  async function run() {
    setActivity("running");
    setError(null);
    setExecution(null);
    try {
      const values = Object.fromEntries(
        Object.entries(parameters).filter(
          ([, value]) =>
            value !== "" &&
            value !== undefined &&
            (!Array.isArray(value) || value.length > 0),
        ),
      );
      const result = await executeDefinition(content, executionTarget, values);
      setExecution(result as unknown as Execution);
      setStale(
        latestInput.current.content !== content ||
          latestInput.current.target !== executionTarget ||
          latestInput.current.parameters !== parameters,
      );
    } catch (err: any) {
      setError(err.message);
    } finally {
      setActivity(null);
    }
  }
  const unavailable = activity !== null || disabled;
  const outputNodeIds = new Set(Object.values(validation?.outputs ?? {}));
  const explanation =
    scope.kind === "graph"
      ? "Runs every published output from the current graph draft using the global inputs below."
      : scope.kind === "node"
        ? `Runs ${scope.nodeId} and only the steps and inputs it depends on.`
        : "Uses the current draft, including unsaved changes. Choose all published outputs or one step to run.";
  const validationMessage = validation
    ? scope.kind === "node"
      ? `Ready to run ${scope.nodeId}: ${validation.execution_order.length} step${validation.execution_order.length === 1 ? "" : "s"} in its dependency closure.`
      : scope.kind === "graph"
        ? `Ready to run ${Object.keys(validation.outputs).length} published output${Object.keys(validation.outputs).length === 1 ? "" : "s"} across ${validation.nodes.length} steps.`
        : `Valid definition: ${Object.keys(validation.outputs).length} outputs, ${validation.nodes.length} steps.`
    : "";
  const completionLabel =
    scope.kind === "node"
      ? "Step"
      : subject === "graph"
        ? "Graph"
        : "Calculation";
  return (
    <section className="space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="max-w-2xl text-xs text-muted-foreground">{explanation}</p>
        <div className="flex gap-2">
          <Button
            variant="outline"
            disabled={unavailable}
            onClick={() => void validate()}
          >
            {activity === "validating" ? (
              <Loader2 className="size-4 animate-spin" />
            ) : (
              <CheckCheck className="size-4" />
            )}{" "}
            Validate
          </Button>
          <Button
            disabled={unavailable || !validation}
            onClick={() => void run()}
          >
            {activity === "running" ? (
              <Loader2 className="size-4 animate-spin" />
            ) : (
              <Play className="size-4" />
            )}{" "}
            Run
          </Button>
        </div>
      </div>
      {error && <StateMessage state="error" variant="banner" message={error} />}
      {validation && (
        <StateMessage
          state="success"
          variant="banner"
          message={validationMessage}
        />
      )}
      {!validation && activity === "validating" && (
        <StateMessage
          state="loading"
          variant="panel"
          message={scope.kind === "node" ? "Preparing step" : "Preparing run"}
        />
      )}
      {scope.kind === "selectable" && (
        <label className="block max-w-md space-y-1 text-sm">
          <span>Run target</span>
          {validation ? (
            <SelectMenu
              value={target}
              disabled={unavailable}
              onChange={(value) => {
                setTarget(value);
                setStale(true);
              }}
              options={[
                { value: "", label: "All outputs" },
                ...Object.entries(validation.outputs).map(([name, nodeId]) => ({
                  value: nodeId,
                  label: `Output: ${name}`,
                  description: nodeId,
                })),
                ...validation.nodes
                  .filter((node) => !outputNodeIds.has(node.id))
                  .map((node) => ({
                    value: node.id,
                    label: node.id,
                    description: node.type,
                  })),
              ]}
            />
          ) : (
            <Input
              value={target}
              disabled={unavailable}
              placeholder="Leave empty for all outputs, or enter a step ID"
              onChange={(event) => {
                setTarget(event.target.value);
                setStale(true);
              }}
            />
          )}
        </label>
      )}
      {validation && validation.parameters.length > 0 && (
        <div className="grid gap-4 md:grid-cols-2">
          {validation.parameters.map((parameter) => (
            <ParameterInput
              key={parameter.id}
              parameter={parameter}
              content={content}
              parameterOptions={parameterOptions}
              value={parameters[parameter.id]}
              disabled={unavailable}
              onChange={(value) => {
                setParameters((current) => ({
                  ...current,
                  [parameter.id]: value,
                }));
                setStale(true);
              }}
            />
          ))}
        </div>
      )}
      {execution && (
        <div className="space-y-4">
          <StateMessage
            state="success"
            variant="banner"
            message={`${completionLabel} completed successfully.`}
          />
          {stale && (
            <StateMessage
              state="warning"
              variant="banner"
              message="These results are from an earlier draft or set of inputs. Run again to refresh them."
            />
          )}
          <p className="text-xs text-muted-foreground">
            Completed in {execution.duration_ms} ms ·{" "}
            {execution.execution_order.join(" -> ")}
          </p>
          {execution.result ? (
            <ResultView
              name={execution.target_node_id || "Step result"}
              result={execution.result}
            />
          ) : (
            Object.entries(execution.outputs ?? {}).map(([name, output]) => (
              <ResultView key={name} name={name} result={output.result} />
            ))
          )}
        </div>
      )}
    </section>
  );
}

function ParameterInput({
  parameter,
  content,
  parameterOptions,
  value,
  disabled,
  onChange,
}: {
  parameter: Parameter;
  content: string;
  parameterOptions: (
    parameter: string,
    content: string,
    search: string,
  ) => Promise<{ options: (string | boolean)[]; has_more: boolean }>;
  value: unknown;
  disabled: boolean;
  onChange: (value: unknown) => void;
}) {
  const [search, setSearch] = useState("");
  const [options, setOptions] = useState<(string | boolean)[]>([]);
  const [loading, setLoading] = useState(false);
  const [more, setMore] = useState(false);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    if (!parameter.options_available) return;
    let active = true;
    const timer = window.setTimeout(async () => {
      setLoading(true);
      setError(null);
      try {
        const result = await parameterOptions(parameter.id, content, search);
        if (active) {
          setOptions(result.options);
          setMore(result.has_more);
        }
      } catch (err: any) {
        if (active) setError(err.message);
      } finally {
        if (active) setLoading(false);
      }
    }, 250);
    return () => {
      active = false;
      window.clearTimeout(timer);
    };
  }, [
    content,
    parameter.id,
    parameter.options_available,
    parameterOptions,
    search,
  ]);
  const multiple = parameter.cardinality === "one_or_more";
  const selected =
    value === undefined || value === ""
      ? []
      : Array.isArray(value)
        ? value
        : [value];
  const allOptions = [...new Set([...selected, ...options])] as (
    | string
    | boolean
  )[];
  return (
    <div className="space-y-2">
      <label
        className="block text-sm font-medium"
        htmlFor={`parameter-${parameter.id}`}
      >
        {parameter.title}
      </label>
      <p className="text-xs text-muted-foreground">
        {parameter.member} · {parameter.operators.join(", ")}
      </p>
      {parameter.options_available ? (
        <>
          {parameter.type === "string" && (
            <Input
              aria-label={`Search ${parameter.title} options`}
              value={search}
              disabled={disabled}
              placeholder="Search values"
              onChange={(event) => setSearch(event.target.value)}
            />
          )}
          <select
            id={`parameter-${parameter.id}`}
            className="min-h-9 w-full rounded-md border bg-background px-2 py-1 text-sm"
            disabled={disabled || loading}
            multiple={multiple}
            value={
              multiple
                ? selected.map((item) => JSON.stringify(item))
                : selected.length
                  ? JSON.stringify(selected[0])
                  : ""
            }
            onChange={(event) => {
              const values = Array.from(event.target.selectedOptions)
                .map((option) => option.value)
                .filter(Boolean)
                .map((item) => JSON.parse(item));
              onChange(multiple ? values : values[0]);
            }}
          >
            {!multiple && <option value="">Choose a value</option>}
            {allOptions.map((option) => (
              <option
                key={JSON.stringify(option)}
                value={JSON.stringify(option)}
              >
                {String(option)}
              </option>
            ))}
          </select>
          {loading && (
            <p className="text-xs text-muted-foreground">Loading values…</p>
          )}
          {multiple && (
            <p className="text-xs text-muted-foreground">
              Select one or more values using Ctrl or Command.
            </p>
          )}
          {more && (
            <p className="text-xs text-muted-foreground">
              More values are available. Refine your search.
            </p>
          )}
        </>
      ) : parameter.cardinality === "range" ? (
        <div className="flex flex-wrap gap-2">
          {[0, 1].map((index) => (
            <Input
              key={index}
              id={index === 0 ? `parameter-${parameter.id}` : undefined}
              aria-label={`${parameter.title} ${index === 0 ? "start" : "end"}`}
              className="w-44"
              type="date"
              disabled={disabled}
              value={String((Array.isArray(value) ? value : [])[index] ?? "")}
              onChange={(event) => {
                const range = Array.isArray(value) ? [...value] : ["", ""];
                range[index] = event.target.value;
                onChange(range);
              }}
            />
          ))}
        </div>
      ) : (
        <Input
          id={`parameter-${parameter.id}`}
          disabled={disabled}
          type={parameter.type === "number" ? "number" : "date"}
          step="any"
          value={value === undefined ? "" : String(value)}
          onChange={(event) =>
            onChange(
              event.target.value === ""
                ? undefined
                : parameter.type === "number"
                  ? Number(event.target.value)
                  : event.target.value,
            )
          }
        />
      )}
      {error && <p className="text-xs text-destructive">{error}</p>}
    </div>
  );
}

function display(value: unknown): string {
  return value === null || value === undefined
    ? "—"
    : typeof value === "object"
      ? JSON.stringify(value)
      : String(value);
}
function ResultView({ name, result }: { name: string; result: QueryResult }) {
  const columns = result.columns ?? Object.keys(result.rows?.[0] ?? {});
  return (
    <div className="space-y-2">
      <h4 className="text-sm font-medium">{name}</h4>
      {result.kind === "scalar" ? (
        <p className="text-2xl font-semibold">{display(result.value)}</p>
      ) : (
        <>
          <p className="text-xs text-muted-foreground">
            {result.row_count ?? result.rows?.length ?? 0} rows
            {result.has_more ? " · Result limit reached" : ""}
          </p>
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
                {result.rows?.map((row, index) => (
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
        </>
      )}
    </div>
  );
}
