import { lazy, Suspense, useEffect, useRef, useState } from "react";
import { useLocation, useNavigate, useParams } from "react-router-dom";
import { ArrowLeft, FolderOpen, Loader2, Paintbrush } from "lucide-react";
import {
  api,
  type Connection,
  type GoogleOAuthStatus,
  type GoogleDriveConfig,
  type SheetField,
} from "@/lib/api";
import { openGoogleDriveFilePicker } from "@/lib/google-picker";
import { GoogleDriveDocumentationButton } from "@/components/connections/google-drive-documentation-button";
import { DestinationSummary } from "@/components/connections/destination-summary";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { SecretInput, SecretTextarea } from "@/components/ui/secret-input";
import { StateMessage } from "@/components/ui/state-message";
import { ItemCard } from "@/components/ui/item-grid";
import { useDeploymentMode } from "@/config/product-provider";
import type { YamlEditorHandle } from "@/components/ui/yaml-editor";

const YamlEditor = lazy(() =>
  import("@/components/ui/yaml-editor").then((module) => ({
    default: module.YamlEditor,
  })),
);

export default function EditConnectionPage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const location = useLocation();
  const managed = useDeploymentMode() !== "self_hosted";
  const [connection, setConnection] = useState<Connection | null>(null);
  const [config, setConfig] = useState<GoogleDriveConfig | null>(null);
  const [oauth, setOauth] = useState<GoogleOAuthStatus | null>(null);
  const [name, setName] = useState("");
  const [creds, setCreds] = useState<Record<string, string>>({});
  const [selectedFileName, setSelectedFileName] = useState<string | null>(null);
  const [picking, setPicking] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(() =>
    Boolean((location.state as { created?: boolean } | null)?.created)
      ? "Connection created."
      : null,
  );
  const [loading, setLoading] = useState(true);
  const [syncYaml, setSyncYaml] = useState("");
  const [savingYaml, setSavingYaml] = useState(false);
  const [formattingYaml, setFormattingYaml] = useState(false);
  const yamlEditorRef = useRef<YamlEditorHandle>(null);

  useEffect(() => {
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
              String(
                conn.credentials?.[field.key] ?? defaults[field.key] ?? "",
              ),
            ]),
          ),
        );
      })
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, [id]);

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
      }));
      setSelectedFileName(selected.name);
    } catch (err: any) {
      setError(err.message);
    } finally {
      setPicking(false);
    }
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!config) return;

    setError(null);
    setNotice(null);
    setSubmitting(true);
    try {
      const updated = await api.connections.update(Number(id!), {
        name: name.trim(),
        credentials: creds,
        destination_id: connection?.destination_id,
      });
      const nextSyncConfig = await api.connections.syncConfig(Number(id!));
      setConnection(updated);
      setSyncYaml(nextSyncConfig.content);
      setName(updated.name);
      setCreds((prev) =>
        Object.fromEntries(
          config.fields.map((field) => [
            field.key,
            updated.secret_fields?.includes(field.key)
              ? ""
              : String(
                  updated.credentials?.[field.key] ?? prev[field.key] ?? "",
                ),
          ]),
        ),
      );
      setNotice("Connection updated.");
    } catch (err: any) {
      setError(err.message);
    } finally {
      setSubmitting(false);
    }
  }

  async function saveSyncYaml() {
    setSavingYaml(true);
    setError(null);
    setNotice(null);
    try {
      const result = await api.connections.updateSyncConfig(
        Number(id),
        syncYaml,
      );
      setSyncYaml(result.content);
      setNotice(
        result.config.load?.schedule?.enabled
          ? "Sync YAML saved. It will be applied by the next scheduled sync."
          : "Sync YAML saved. Run a sync from Pipes to apply it.",
      );
    } catch (err: any) {
      setError(err.message);
    } finally {
      setSavingYaml(false);
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

  async function revealSavedSecret(fieldKey: string) {
    if (!connection || creds[fieldKey]) return;
    if (!connection.secret_fields?.includes(fieldKey)) return;

    setError(null);
    try {
      const secrets = (await api.connections.secrets(connection.id)).secrets;
      const value = secrets[fieldKey];
      if (!value) throw new Error("Saved secret not found.");

      setCreds((prev) => ({ ...prev, [fieldKey]: value }));
    } catch (err: any) {
      setError(err.message);
      throw err;
    }
  }

  function concealSecret(fieldKey: string) {
    setCreds((prev) => ({ ...prev, [fieldKey]: "" }));
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
          onClick={() => navigate("/data/pipes")}
          className="mb-4 -ml-2 text-muted-foreground hover:text-foreground"
        >
          <ArrowLeft className="size-4" /> Back
        </Button>
        <div className="flex items-center gap-1.5">
          <h1 className="text-2xl font-semibold">Edit connection</h1>
          <GoogleDriveDocumentationButton config={config} />
        </div>
        <p className="text-sm text-muted-foreground mt-1">
          Update the selected Drive file and its durable load contract.
        </p>
      </div>

      {notice && (
        <StateMessage
          state="success"
          variant="banner"
          message={notice}
          onClose={() => setNotice(null)}
        />
      )}

      <form onSubmit={handleSubmit} className="space-y-5">
        <div className="space-y-1.5">
          <Label htmlFor="conn-name">Connection name</Label>
          <Input
            id="conn-name"
            value={name}
            onChange={(e) => setName(e.target.value)}
            required
          />
        </div>

        <DestinationSummary destination={connection.destination} />

        {config.fields
          .filter((field) => !field.hidden)
          .map((field) => {
            const hasSavedSecret = connection.secret_fields?.includes(
              field.key,
            );
            const required = Boolean(field.required && !hasSavedSecret);
            const help = [
              field.help,
              hasSavedSecret
                ? "Saved. Leave blank to keep existing value."
                : null,
            ]
              .filter(Boolean)
              .join(" ");

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
                          {selectedFileName ??
                            creds.file_name ??
                            creds.file_id ??
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
                          ? "Google Drive file selection is currently unavailable. Reconnect Google from Data → Connections or contact support."
                          : "Finish Google Picker setup or reconnect Google from Data → Connections."}
                      </p>
                    )}
                  </div>
                ) : field.type === "textarea" && isSecretField(field) ? (
                  <SecretTextarea
                    id={field.key}
                    placeholder={field.placeholder}
                    value={creds[field.key] ?? ""}
                    onConceal={() => concealSecret(field.key)}
                    onReveal={() => revealSavedSecret(field.key)}
                    onChange={(e) =>
                      setCreds((prev) => ({
                        ...prev,
                        [field.key]: e.target.value,
                      }))
                    }
                    required={required}
                    rows={8}
                  />
                ) : field.type === "textarea" ? (
                  <textarea
                    id={field.key}
                    placeholder={field.placeholder}
                    value={creds[field.key] ?? ""}
                    onChange={(e) =>
                      setCreds((prev) => ({
                        ...prev,
                        [field.key]: e.target.value,
                      }))
                    }
                    required={required}
                    rows={8}
                    className="min-h-32 w-full rounded-md border border-input bg-background px-3 py-2 text-sm shadow-sm outline-none transition-colors placeholder:text-muted-foreground focus-visible:ring-2 focus-visible:ring-ring"
                  />
                ) : field.type === "secret" ? (
                  <SecretInput
                    id={field.key}
                    placeholder={field.placeholder}
                    value={creds[field.key] ?? ""}
                    onConceal={() => concealSecret(field.key)}
                    onReveal={() => revealSavedSecret(field.key)}
                    onChange={(e) =>
                      setCreds((prev) => ({
                        ...prev,
                        [field.key]: e.target.value,
                      }))
                    }
                    required={required}
                  />
                ) : (
                  <Input
                    id={field.key}
                    type="text"
                    placeholder={field.placeholder}
                    value={creds[field.key] ?? ""}
                    onChange={(e) =>
                      setCreds((prev) => ({
                        ...prev,
                        [field.key]: e.target.value,
                      }))
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

        {error && (
          <StateMessage
            state="error"
            variant="inline"
            message={error}
            onClose={() => setError(null)}
          />
        )}

        <div className="flex gap-3 pt-2">
          <Button type="submit" variant="primary" disabled={submitting}>
            {submitting ? "Saving…" : "Save changes"}
          </Button>
          <Button
            type="button"
            variant="outline"
            onClick={() => navigate("/data/pipes")}
          >
            Cancel
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
            disabled={savingYaml || formattingYaml || !syncYaml}
            onClick={() => void saveSyncYaml()}
          >
            {savingYaml ? "Saving…" : "Save YAML"}
          </Button>
        }
      >
        <div className="space-y-3">
          <p className="text-sm text-muted-foreground">
            Configure the cron schedule, table and column descriptions, renamed
            fields, format detection, delimiter, encoding, header rows, and dlt
            data type overrides. OAuth secrets never appear in this file.
          </p>
          {syncYaml ? (
            <div className="h-[32rem] overflow-hidden rounded-lg border bg-background">
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
                  ref={yamlEditorRef}
                  ariaLabel="Sync YAML"
                  path={`connections/${connection.id}/sync.yaml`}
                  value={syncYaml}
                  onChange={setSyncYaml}
                />
              </Suspense>
            </div>
          ) : (
            <StateMessage
              state="warning"
              variant="inline"
              message="This source predates durable sync. Choose its Drive file with Google Picker above and save to create the first sync YAML."
            />
          )}
          <p className="text-xs text-muted-foreground">
            Supported overrides: binary, text, bigint, double, bool, timestamp,
            date, decimal, and json. The YAML names this pipe's selected
            destination and its dedicated target schema; destination
            registration is managed separately.
          </p>
        </div>
      </ItemCard>
    </div>
  );
}

function isSecretField(field: SheetField) {
  return Boolean(field.secret || field.type === "secret");
}
