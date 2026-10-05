import { useEffect, useMemo, useState } from "react";
import { ArrowLeft } from "lucide-react";
import { useNavigate, useParams, useSearchParams } from "react-router-dom";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { MultiSelect } from "@/components/ui/multi-select";
import { StateMessage } from "@/components/ui/state-message";
import { useModal } from "@/components/ui/global-modal";
import { notify } from "@/components/ui/global-toast";
import { DependencyImpactSummary } from "@/components/collections/DependencyImpactSummary";
import { api, type Connection, type DataCollectionInput } from "@/lib/api";
import { useDeploymentMode } from "@/config/product-provider";

const EMPTY_FORM: DataCollectionInput = {
  name: "",
  description: "",
  agent_instructions: "",
  pipe_ids: [],
};

export default function CollectionFormPage() {
  const navigate = useNavigate();
  const { openModal } = useModal();
  const managed = useDeploymentMode() !== "self_hosted";
  const { id } = useParams();
  const [searchParams] = useSearchParams();
  const requestedSources = searchParams.get("sources");
  const collectionId = id ? Number(id) : null;
  const editing = collectionId !== null;
  const [connections, setConnections] = useState<Connection[]>([]);
  const [form, setForm] = useState<DataCollectionInput>(EMPTY_FORM);
  const [originalPipeIds, setOriginalPipeIds] = useState<number[]>([]);
  const [slug, setSlug] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    async function load() {
      try {
        const [pipes, collection] = await Promise.all([
          api.connections.list(),
          collectionId ? api.collections.get(collectionId) : null,
        ]);
        setConnections(pipes);
        if (collection) {
          setSlug(collection.slug);
          setOriginalPipeIds(collection.pipe_ids);
          setForm({
            name: collection.name,
            description: collection.description,
            agent_instructions: collection.agent_instructions,
            pipe_ids: collection.pipe_ids,
          });
        } else if (requestedSources) {
          const available = new Set(pipes.map((pipe) => pipe.id));
          setForm((current) => ({
            ...current,
            pipe_ids: requestedSources
              .split(",")
              .map(Number)
              .filter((id) => available.has(id)),
          }));
        }
      } catch (err: any) {
        setError(err.message);
      } finally {
        setLoading(false);
      }
    }

    void load();
  }, [collectionId, requestedSources]);

  const pipeOptions = useMemo(
    () =>
      connections.map((connection) => ({
        value: String(connection.id),
        label: connection.name,
        description: `${connection.slug} · ${connection.status}`,
      })),
    [connections],
  );

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    const removedPipeIds = originalPipeIds.filter(
      (pipeId) => !form.pipe_ids.includes(pipeId),
    );

    if (collectionId && removedPipeIds.length > 0) {
      setSaving(true);
      setError(null);
      try {
        const impacts = await Promise.all(
          removedPipeIds.map((pipeId) =>
            api.collections.sourceRemovalImpact(collectionId, pipeId),
          ),
        );
        openModal({
          title: "Review removed source dependencies",
          body: (
            <div className="space-y-4">
              {impacts.map((impact) => (
                <div
                  key={String(impact.target.connection_id)}
                  className="space-y-2 rounded-md border p-3"
                >
                  <p className="font-medium">
                    {String(impact.target.name ?? "Source")}
                  </p>
                  <DependencyImpactSummary impact={impact} />
                </div>
              ))}
            </div>
          ),
          actions: ({ close }) => (
            <>
              <Button variant="outline" onClick={close}>
                Cancel
              </Button>
              <Button
                variant="primary"
                onClick={() => {
                  close();
                  void save();
                }}
              >
                Save artifact
              </Button>
            </>
          ),
        });
      } catch (err: any) {
        setError(err.message);
        notify.error(err.message);
      } finally {
        setSaving(false);
      }
      return;
    }

    await save();
  }

  async function save() {
    setError(null);
    setSaving(true);

    try {
      const saved = collectionId
        ? await api.collections.update(collectionId, form)
        : await api.collections.create(form);
      notify.success(collectionId ? "Artifact saved." : "Artifact created.");
      navigate(`/data/artifacts/${saved.id}`);
    } catch (err: any) {
      setError(err.message);
      notify.error(err.message);
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="space-y-7">
      <div className="flex items-start justify-between gap-4">
        <div>
          <Button
            type="button"
            variant="ghost"
            size="sm"
            className="-ml-2 mb-2"
            onClick={() =>
              navigate(
                collectionId
                  ? `/data/artifacts/${collectionId}`
                  : "/data/artifacts",
              )
            }
          >
            <ArrowLeft className="size-3.5" /> Artifacts
          </Button>
          <h1 className="text-2xl font-semibold">
            {editing ? "Edit artifact" : "New artifact"}
          </h1>
          <p className="mt-1 text-sm text-muted-foreground">
            Select the sources and context an agent should work with together.
          </p>
        </div>
      </div>

      {loading && (
        <StateMessage
          state="loading"
          variant="banner"
          message="Loading artifact"
        />
      )}
      {error && (
        <StateMessage
          state="error"
          variant="banner"
          message={error}
          onClose={() => setError(null)}
        />
      )}

      {!loading && (
        <form
          onSubmit={submit}
          className="max-w-3xl space-y-6 rounded-lg border bg-card p-5"
        >
          <div className="space-y-2">
            <Label htmlFor="collection-name">Name</Label>
            <Input
              id="collection-name"
              value={form.name}
              placeholder="Finance"
              required
              autoFocus={!editing}
              onChange={(event) =>
                setForm((current) => ({
                  ...current,
                  name: event.target.value,
                }))
              }
            />
            {slug && !managed && (
              <p className="text-xs text-muted-foreground">
                Stable MCP slug: <span className="font-mono">{slug}</span>
              </p>
            )}
          </div>

          <div className="space-y-2">
            <Label htmlFor="collection-description">Description</Label>
            <textarea
              id="collection-description"
              rows={3}
              value={form.description}
              placeholder="Banking, budgets, and reporting data used by the finance team."
              className="w-full resize-y rounded-lg border border-input bg-transparent px-2.5 py-2 text-sm outline-none placeholder:text-muted-foreground focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 dark:bg-input/30"
              onChange={(event) =>
                setForm((current) => ({
                  ...current,
                  description: event.target.value,
                }))
              }
            />
          </div>

          <div className="space-y-2">
            <Label>Sources</Label>
            <MultiSelect
              options={pipeOptions}
              value={form.pipe_ids.map(String)}
              placeholder="Select sources"
              triggerClassName="h-auto min-h-8"
              onChange={(values) =>
                setForm((current) => ({
                  ...current,
                  pipe_ids: values.map(Number),
                }))
              }
            />
            <p className="text-xs text-muted-foreground">
              {managed
                ? "Tables and source models are derived from these sources. Configure relationships from the artifact page."
                : "Destination schemas, tables, and source cubes are derived from these sources. Configure relationships from the artifact page."}
            </p>
          </div>

          <div className="space-y-2">
            <Label htmlFor="agent-instructions">Agent instructions</Label>
            <textarea
              id="agent-instructions"
              rows={5}
              value={form.agent_instructions}
              placeholder="Use this artifact for cash-flow and budget questions. Ask before assuming account categories."
              className="w-full resize-y rounded-lg border border-input bg-transparent px-2.5 py-2 text-sm outline-none placeholder:text-muted-foreground focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 dark:bg-input/30"
              onChange={(event) =>
                setForm((current) => ({
                  ...current,
                  agent_instructions: event.target.value,
                }))
              }
            />
            <p className="text-xs text-muted-foreground">
              Returned once with artifact context so the agent does not need to
              rediscover these rules.
            </p>
          </div>

          <div className="flex justify-end gap-2 border-t pt-5">
            <Button
              type="button"
              variant="outline"
              onClick={() =>
                navigate(
                  collectionId
                    ? `/data/artifacts/${collectionId}`
                    : "/data/artifacts",
                )
              }
            >
              Cancel
            </Button>
            <Button type="submit" variant="primary" disabled={saving}>
              {saving ? "Saving" : editing ? "Save" : "Create"}
            </Button>
          </div>
        </form>
      )}
    </div>
  );
}
