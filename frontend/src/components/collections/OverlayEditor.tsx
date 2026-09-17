import { lazy, Suspense, useEffect, useRef, useState } from "react";
import { Paintbrush, Save } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { StateMessage } from "@/components/ui/state-message";
import { useModal } from "@/components/ui/global-modal";
import type { YamlEditorHandle } from "@/components/ui/yaml-editor";
import {
  api,
  type CollectionSemanticModel,
  type OverlayDraft,
  type OverlayValidation,
} from "@/lib/api";
import { QueryTester } from "./QueryTester";

const YamlEditor = lazy(() =>
  import("@/components/ui/yaml-editor").then((module) => ({
    default: module.YamlEditor,
  })),
);

export function OverlayEditor({
  collectionId,
  initial,
  models,
  readOnly = false,
  title = "Semantic model",
  onClose,
  onSaved,
}: {
  collectionId: number;
  initial: OverlayDraft;
  models: CollectionSemanticModel[];
  readOnly?: boolean;
  title?: string;
  onClose: () => void;
  onSaved: (message: string) => void;
}) {
  const { openModal } = useModal();
  const [draft, setDraft] = useState(initial);
  const [validation, setValidation] = useState<OverlayValidation | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const editor = useRef<YamlEditorHandle>(null);
  const dirty =
    !readOnly && (draft.create || draft.content !== draft.expected_content);

  useEffect(() => {
    if (!dirty) return;
    const preventClose = (event: BeforeUnloadEvent) => event.preventDefault();
    window.addEventListener("beforeunload", preventClose);
    return () => window.removeEventListener("beforeunload", preventClose);
  }, [dirty]);

  function cancel() {
    if (!dirty) return onClose();
    openModal({
      title: "Discard model changes?",
      body: <p>Your unsaved model changes will be discarded.</p>,
      actions: ({ close }) => (
        <>
          <Button variant="outline" onClick={close}>
            Keep editing
          </Button>
          <Button
            variant="destructive"
            onClick={() => {
              close();
              onClose();
            }}
          >
            Discard
          </Button>
        </>
      ),
    });
  }

  async function save() {
    setBusy(true);
    setError(null);
    try {
      const result = await api.collections.writeOverlay(collectionId, draft);
      onSaved(
        result.cube.compiled
          ? "Model saved and compiled."
          : "Model saved. Cube compilation needs attention; inspect the model status.",
      );
    } catch (err: any) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="space-y-4 rounded-lg border bg-card p-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 className="text-base font-semibold">{title}</h2>
        <div className="flex flex-wrap gap-2">
          <Button variant="outline" disabled={busy} onClick={cancel}>
            {readOnly ? "Close" : "Cancel"}
          </Button>
          <QueryTester
            collectionId={collectionId}
            models={models}
            initialCubeName={
              models.find((model) => model.path === draft.path)?.name ??
              models[0]?.name
            }
            draft={readOnly ? undefined : draft}
            disabled={busy}
            onValidated={readOnly ? undefined : setValidation}
          />
          {!readOnly && (
            <>
              <Button
                variant="outline"
                disabled={busy}
                onClick={async () => {
                  try {
                    await editor.current?.format();
                  } catch {
                    setError("Fix the YAML syntax before formatting.");
                  }
                }}
              >
                <Paintbrush className="size-4" /> Format
              </Button>
              <Button
                disabled={
                  busy ||
                  !dirty ||
                  !validation?.ready_to_save ||
                  !!validation.cleanup.error
                }
                onClick={() => void save()}
              >
                <Save className="size-4" /> Save model
              </Button>
            </>
          )}
        </div>
      </div>
      <label className="block space-y-1 text-sm">
        <span>Model path</span>
        <Input
          disabled={!draft.create || busy || readOnly}
          value={draft.path}
          onChange={(event) => {
            setDraft({ ...draft, path: event.target.value });
            setValidation(null);
          }}
        />
      </label>
      {readOnly && (
        <p className="text-sm text-muted-foreground">
          This model is read-only here. Source models are maintained by
          synchronization; shared files may include models from other Apps.
        </p>
      )}
      {error && <StateMessage state="error" variant="banner" message={error} />}
      <div className="h-[28rem] overflow-hidden rounded-lg border bg-background">
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
            ref={editor}
            readOnly={busy || readOnly}
            path={draft.path || "model.yaml"}
            value={draft.content}
            onChange={(content) => {
              if (!busy && !readOnly) {
                setDraft({ ...draft, content });
                setValidation(null);
              }
            }}
          />
        </Suspense>
      </div>
      {!readOnly && (
        <p className="text-xs text-muted-foreground">
          Validate the current draft from Run before saving. Validation
          temporarily compiles the draft, runs the selected query, and restores
          the active model. Each model needs purpose, requirement, grain,
          assumptions, and evidence under meta.settra.
        </p>
      )}
    </section>
  );
}
