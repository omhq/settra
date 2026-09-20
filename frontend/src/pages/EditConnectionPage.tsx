import { useEffect, useRef, useState } from "react";
import { useLocation, useNavigate, useParams } from "react-router-dom";
import { ArrowLeft, FolderOpen, Loader2, Paintbrush } from "lucide-react";
import {
  api,
  type Connection,
  type ConnectionCredentialValue,
  type GoogleDriveWorksheetDiscovery,
  type GoogleOAuthStatus,
  type GoogleDriveConfig,
  type RowKeyDefinition,
  type SheetField,
} from "@/lib/api";
import { openGoogleDriveFilePicker } from "@/lib/google-picker";
import { GoogleDriveDocumentationButton } from "@/components/connections/google-drive-documentation-button";
import { DestinationSummary } from "@/components/connections/destination-summary";
import { RowKeyEditor } from "@/components/connections/row-key-editor";
import {
  credentialText,
  WorksheetSelector,
} from "@/components/connections/worksheet-selector";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { StateMessage } from "@/components/ui/state-message";
import { ItemCard } from "@/components/ui/item-grid";
import { useModal } from "@/components/ui/global-modal";
import { notify } from "@/components/ui/global-toast";
import { WorkspaceDependencyImpactSummary } from "@/components/collections/DependencyImpactSummary";
import { useDeploymentMode } from "@/config/product-provider";
import {
  StructuredDataEditor,
  type StructuredDataEditorHandle,
} from "@/components/ui/structured-data-editor";
import { useUnsavedChanges } from "@/hooks/use-unsaved-changes";

export default function EditConnectionPage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const location = useLocation();
  const { openModal } = useModal();
  const managed = useDeploymentMode() !== "self_hosted";
  const [connection, setConnection] = useState<Connection | null>(null);
  const [config, setConfig] = useState<GoogleDriveConfig | null>(null);
  const [oauth, setOauth] = useState<GoogleOAuthStatus | null>(null);
  const [name, setName] = useState("");
  const [creds, setCreds] = useState<Record<string, ConnectionCredentialValue>>(
    {},
  );
  const [rowKeys, setRowKeys] = useState<Record<string, RowKeyDefinition>>({});
  const [selectedFileName, setSelectedFileName] = useState<string | null>(null);
  const [worksheetDiscovery, setWorksheetDiscovery] =
    useState<GoogleDriveWorksheetDiscovery | null>(null);
  const [loadingWorksheets, setLoadingWorksheets] = useState(false);
  const [picking, setPicking] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [syncYaml, setSyncYaml] = useState("");
  const [savedSyncYaml, setSavedSyncYaml] = useState("");
  const [savingYaml, setSavingYaml] = useState(false);
  const [previewingImpact, setPreviewingImpact] = useState(false);
  const [formattingYaml, setFormattingYaml] = useState(false);
  const [sourceDirty, setSourceDirty] = useState(false);
  const yamlEditorRef = useRef<StructuredDataEditorHandle>(null);
  const yamlDirty = syncYaml !== savedSyncYaml;

  useUnsavedChanges({
    dirty: sourceDirty || yamlDirty,
    title: "Discard source changes?",
    message: "Your unsaved source settings or Sync YAML changes will be lost.",
  });

  useEffect(() => {
    if (Boolean((location.state as { created?: boolean } | null)?.created)) {
      notify.success("Connection created.");
    }
  }, [location.state]);

  useEffect(() => {
    setSourceDirty(false);
    Promise.all([
      api.connections.get(Number(id)),
      api.googleDrive.config(),
      api.connections.syncConfig(Number(id)).catch(() => ({ content: "" })),
      api.googleOAuth.status(),
    ])
      .then(([conn, nextConfig, syncConfig, nextOauth]) => {
        setConnection(conn);
        setName(conn.name);
        setConfig(nextConfig);
        setOauth(nextOauth);
        setSyncYaml(syncConfig.content);
        setSavedSyncYaml(syncConfig.content);
        setRowKeys(conn.row_keys ?? {});
        const defaults = Object.fromEntries(
          nextConfig.fields.map((field) => [
            field.key,
            String(field.default ?? ""),
          ]),
        );
        setCreds(
          Object.fromEntries(
            nextConfig.fields.map((field) => [
              field.key,
              conn.credentials?.[field.key] ?? defaults[field.key] ?? "",
            ]),
          ),
        );
      })
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, [id]);

  useEffect(() => {
    const fileId = credentialText(creds.file_id);

    if (!fileId || !oauth?.picker_ready) {
      setWorksheetDiscovery(null);
      setLoadingWorksheets(false);
      return;
    }

    let cancelled = false;
    setLoadingWorksheets(true);
    setWorksheetDiscovery(null);

    api.googlePicker
      .worksheets(fileId)
      .then((result) => {
        if (cancelled) return;
        setWorksheetDiscovery(result);
        setCreds((current) => ({
          ...current,
          file_name: result.file_name,
          mime_type: result.mime_type,
        }));
      })
      .catch((err) => {
        if (!cancelled) {
          setError(
            `${err.message} You can still enter worksheet names manually.`,
          );
        }
      })
      .finally(() => {
        if (!cancelled) setLoadingWorksheets(false);
      });

    return () => {
      cancelled = true;
    };
  }, [creds.file_id, oauth?.picker_ready]);

  async function chooseDriveFile() {
    setError(null);
    setPicking(true);

    try {
      const session = await api.googlePicker.session();
      const selected = await openGoogleDriveFilePicker(session);

      if (!selected) {
        return;
      }

      setCreds((previous) => ({
        ...previous,
        file_id: selected.id,
        file_name: selected.name,
        mime_type: selected.mimeType,
        sheets: ["*"],
      }));
      setWorksheetDiscovery(null);
      setSelectedFileName(selected.name);
      setRowKeys({});
      setSourceDirty(true);
    } catch (err: any) {
      setError(err.message);
    } finally {
      setPicking(false);
    }
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!config) return;

    if (schemaInputsChanged()) {
      await previewSchemaChange("Save source changes", submitConnection);
      return;
    }

    await submitConnection();
  }

  async function submitConnection() {
    if (!config) return;

    setError(null);
    setSubmitting(true);
    try {
      const updated = await api.connections.update(Number(id!), {
        name: name.trim(),
        credentials: creds,
        destination_id: connection?.destination_id,
        row_keys: rowKeys,
      });
      const nextSyncConfig = await api.connections.syncConfig(Number(id!));
      setConnection(updated);
      setRowKeys(updated.row_keys ?? {});
      if (!yamlDirty) {
        setSyncYaml(nextSyncConfig.content);
      }
      setSavedSyncYaml(nextSyncConfig.content);
      setName(updated.name);
      setCreds(
        Object.fromEntries(
          config.fields.map((field) => [
            field.key,
            updated.credentials?.[field.key] ?? creds[field.key] ?? "",
          ]),
        ),
      );
      setSourceDirty(false);
      notify.success("Connection updated.");
    } catch (err: any) {
      setError(err.message);
      notify.error(err.message);
    } finally {
      setSubmitting(false);
    }
  }

  async function saveSyncYaml() {
    if (syncYaml !== savedSyncYaml) {
      await previewSchemaChange("Save Sync YAML", persistSyncYaml);
      return;
    }

    await persistSyncYaml();
  }

  async function persistSyncYaml() {
    setSavingYaml(true);
    setError(null);
    try {
      const result = await api.connections.updateSyncConfig(
        Number(id),
        syncYaml,
      );
      setSyncYaml(result.content);
      setSavedSyncYaml(result.content);
      setRowKeys(result.row_keys);
      notify.success(
        result.config.load?.schedule?.enabled
          ? "Sync YAML saved. It will be applied by the next scheduled sync."
          : "Sync YAML saved. Run a sync from Sources to apply it.",
      );
    } catch (err: any) {
      setError(err.message);
      notify.error(err.message);
    } finally {
      setSavingYaml(false);
    }
  }

  function schemaInputsChanged() {
    if (!connection) return false;

    return (
      credentialText(creds.file_id) !==
        credentialText(connection.credentials?.file_id) ||
      JSON.stringify(creds.sheets ?? []) !==
        JSON.stringify(connection.credentials?.sheets ?? []) ||
      JSON.stringify(rowKeys) !== JSON.stringify(connection.row_keys ?? {})
    );
  }

  async function previewSchemaChange(
    confirmLabel: string,
    onConfirm: () => Promise<void>,
  ) {
    setPreviewingImpact(true);
    setError(null);
    try {
      const impact = await api.connections.schemaImpact(Number(id));
      if (!impact.has_impact) {
        await onConfirm();
        return;
      }

      openModal({
        title: "Review source dependency impact",
        body: <WorkspaceDependencyImpactSummary impact={impact} />,
        actions: ({ close }) => (
          <>
            <Button variant="outline" onClick={close}>
              Cancel
            </Button>
            <Button
              variant="primary"
              onClick={() => {
                close();
                void onConfirm();
              }}
            >
              {confirmLabel}
            </Button>
          </>
        ),
      });
    } catch (err: any) {
      setError(err.message);
    } finally {
      setPreviewingImpact(false);
    }
  }

  async function formatSyncYaml() {
    setFormattingYaml(true);
    setError(null);

    try {
      const formatted = await yamlEditorRef.current?.format();
      if (!formatted) setError("The YAML formatter is not ready yet.");
    } catch {
      setError(
        "Unable to format this YAML. Fix its syntax errors and try again.",
      );
    } finally {
      setFormattingYaml(false);
    }
  }

  function updateCredential(
    fieldKey: string,
    value: ConnectionCredentialValue,
  ) {
    setCreds((previous) => ({ ...previous, [fieldKey]: value }));
    setSourceDirty(true);
  }

  if (loading)
    return (
      <StateMessage
        state="loading"
        variant="panel"
        message="Loading connection"
      />
    );
  if (!connection || !config)
    return (
      <StateMessage
        state="error"
        variant="panel"
        message={error ?? "Connection not found"}
      />
    );

  return (
    <div className="max-w-3xl space-y-6">
      <div>
        <Button
          type="button"
          variant="ghost"
          onClick={() => navigate("/data/sources")}
          className="mb-4 -ml-2 text-muted-foreground hover:text-foreground"
        >
          <ArrowLeft className="size-4" /> Back
        </Button>
        <div className="flex flex-wrap items-center gap-1.5">
          <h1 className="text-2xl font-semibold">Edit connection</h1>
          {(sourceDirty || yamlDirty) && (
            <Badge variant="secondary">Unsaved</Badge>
          )}
          <GoogleDriveDocumentationButton config={config} />
        </div>
        <p className="text-sm text-muted-foreground mt-1">
          Update the selected Drive file and its durable load contract.
        </p>
      </div>

      <form onSubmit={handleSubmit} className="space-y-5">
        <div className="space-y-1.5">
          <Label htmlFor="conn-name">Connection name</Label>
          <Input
            id="conn-name"
            value={name}
            onChange={(event) => {
              setName(event.target.value);
              setSourceDirty(true);
            }}
            required
          />
        </div>

        {config.fields
          .filter((field) => !field.hidden)
          .map((field) => {
            if (
              field.key === "sheets" &&
              worksheetDiscovery &&
              worksheetDiscovery.format !== "google_sheets" &&
              worksheetDiscovery.format !== "excel"
            ) {
              return null;
            }

            const required = Boolean(field.required);
            const help = field.help;

            return (
              <div key={field.key} className="space-y-1.5">
                <Label htmlFor={field.key}>{field.label}</Label>
                {field.key === "file_id" ? (
                  <div className="space-y-2 rounded-md border border-border bg-muted/20 p-4">
                    <div className="flex items-center justify-between gap-3">
                      <div className="min-w-0">
                        <p className="text-xs text-muted-foreground">
                          {selectedFileName
                            ? "Selected Drive file"
                            : "Current Drive file"}
                        </p>
                        <p className="truncate font-mono text-sm text-foreground">
                          {selectedFileName ||
                            credentialText(creds.file_name) ||
                            credentialText(creds.file_id) ||
                            "None selected"}
                        </p>
                      </div>
                      <Button
                        type="button"
                        variant="outline"
                        disabled={picking || !oauth?.picker_ready}
                        onClick={() => void chooseDriveFile()}
                      >
                        <FolderOpen className="size-3.5" />
                        {picking ? "Opening..." : "Choose from Drive"}
                      </Button>
                    </div>
                    {!oauth?.picker_ready && (
                      <p className="text-xs text-amber-700 dark:text-amber-300">
                        {managed
                          ? "Google Drive file selection is currently unavailable. Reconnect Google from Data -> Connections or contact support."
                          : "Finish Google Picker setup or reconnect Google from Data -> Connections."}
                      </p>
                    )}
                  </div>
                ) : field.key === "sheets" ? (
                  <WorksheetSelector
                    field={field}
                    fileSelected={Boolean(credentialText(creds.file_id))}
                    discovery={worksheetDiscovery}
                    loading={loadingWorksheets}
                    value={creds.sheets}
                    showLabel={false}
                    onChange={(value) => updateCredential("sheets", value)}
                  />
                ) : field.type === "textarea" ? (
                  <textarea
                    id={field.key}
                    placeholder={field.placeholder}
                    value={credentialText(creds[field.key])}
                    onChange={(event) =>
                      updateCredential(field.key, event.target.value)
                    }
                    required={required}
                    rows={8}
                    className="min-h-32 w-full rounded-md border border-input bg-background px-3 py-2 text-sm shadow-sm outline-none transition-colors placeholder:text-muted-foreground focus-visible:ring-2 focus-visible:ring-ring"
                  />
                ) : (
                  <Input
                    id={field.key}
                    type="text"
                    placeholder={field.placeholder}
                    value={credentialText(creds[field.key])}
                    onChange={(event) =>
                      updateCredential(field.key, event.target.value)
                    }
                    required={required}
                  />
                )}
                {help && field.key !== "file_id" && (
                  <p className="text-xs text-muted-foreground">{help}</p>
                )}
              </div>
            );
          })}

        <RowKeyEditor
          discovery={worksheetDiscovery}
          selectedWorksheets={creds.sheets}
          value={rowKeys}
          onChange={(value) => {
            setRowKeys(value);
            setSourceDirty(true);
          }}
        />

        <DestinationSummary destination={connection.destination} />

        {error && (
          <StateMessage
            state="error"
            variant="inline"
            message={error}
            onClose={() => setError(null)}
          />
        )}

        <div className="flex flex-wrap justify-end gap-2 pt-2">
          <Button
            type="button"
            variant="outline"
            onClick={() => navigate("/data/sources")}
          >
            Cancel
          </Button>
          <Button
            type="submit"
            variant="primary"
            disabled={
              !sourceDirty ||
              submitting ||
              previewingImpact ||
              loadingWorksheets
            }
          >
            {submitting ? "Saving…" : "Save changes"}
          </Button>
        </div>
      </form>

      <ItemCard
        title="Sync YAML"
        headerAction={
          syncYaml ? (
            <Button
              type="button"
              variant="ghost"
              size="sm"
              disabled={formattingYaml || savingYaml}
              onClick={() => void formatSyncYaml()}
            >
              {formattingYaml ? (
                <Loader2 className="size-4 animate-spin" />
              ) : (
                <Paintbrush className="size-4" />
              )}
              Format
            </Button>
          ) : undefined
        }
        footer={
          <Button
            type="button"
            variant="primary"
            title={
              sourceDirty
                ? "Save the source settings before saving Sync YAML"
                : undefined
            }
            disabled={
              savingYaml ||
              previewingImpact ||
              formattingYaml ||
              !syncYaml ||
              !yamlDirty ||
              sourceDirty
            }
            onClick={() => void saveSyncYaml()}
          >
            {savingYaml ? "Saving…" : "Save YAML"}
          </Button>
        }
      >
        <div className="space-y-3">
          <p className="text-sm text-muted-foreground">
            Configure the cron schedule, table and column descriptions, renamed
            fields, row identity keys, format detection, delimiter, encoding,
            header rows, and data type overrides.
          </p>
          {syncYaml ? (
            <StructuredDataEditor
              ref={yamlEditorRef}
              ariaLabel="Sync YAML"
              path={`connections/${connection.id}/sync.yaml`}
              value={syncYaml}
              onChange={setSyncYaml}
            />
          ) : (
            <StateMessage
              state="warning"
              variant="inline"
              message="Sync configuration is unavailable. Choose the Drive file again and save the source."
            />
          )}
        </div>
      </ItemCard>
    </div>
  );
}
