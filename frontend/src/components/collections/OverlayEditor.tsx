import { useEffect, useRef, useState } from "react";
import { Paintbrush, Save } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { StateMessage } from "@/components/ui/state-message";
import { useModal } from "@/components/ui/global-modal";
import { notify } from "@/components/ui/global-toast";
import {
  StructuredDataEditor,
  type StructuredDataEditorHandle,
} from "@/components/ui/structured-data-editor";
import {
  api,
  type CollectionSemanticModel,
  type OverlayDraft,
  type OverlayValidation,
} from "@/lib/api";
import { QueryTester } from "./QueryTester";
import { useWorkspaceChange } from "@/realtime/workspace-events";

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
  const [remoteChange, setRemoteChange] = useState(false);
  const editor = useRef<StructuredDataEditorHandle>(null);
  const dirty =
    !readOnly && (draft.create || draft.content !== draft.expected_content);

  useWorkspaceChange(["semantic_models"], (event) => {
    if (event.action === "transport_ready") return;
    if (event.artifact_id !== null && event.artifact_id !== collectionId) {
      return;
    }
    const matchingPath =
      !event.entity_key ||
      event.entity_key === draft.path ||
      event.entity_key.endsWith(`/${draft.path}`);
    if (matchingPath && !busy) setRemoteChange(true);
  });

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
      notify.error(err.message);
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
          synchronization; shared files may include models from other artifacts.
        </p>
      )}
      {remoteChange && (
        <StateMessage
          state="warning"
          variant="banner"
          message="This model changed elsewhere. Your draft is preserved; close and reopen it to review the latest version before saving."
        />
      )}
      {error && <StateMessage state="error" variant="banner" message={error} />}
      <StructuredDataEditor
        ref={editor}
        className="h-[28rem]"
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
    </section>
  );
}
