import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { ArrowLeft, FolderOpen } from "lucide-react";

import {
  api,
  type ConnectionCredentialValue,
  type Destination,
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
import { Input } from "@/components/ui/input";
import { ItemCard } from "@/components/ui/item-grid";
import { Label } from "@/components/ui/label";
import { SecretInput, SecretTextarea } from "@/components/ui/secret-input";
import { StateMessage } from "@/components/ui/state-message";
import { useDeploymentMode } from "@/config/product-provider";

export default function NewConnectionPage() {
  const navigate = useNavigate();
  const managed = useDeploymentMode() !== "self_hosted";
  const [config, setConfig] = useState<GoogleDriveConfig | null>(null);
  const [name, setName] = useState("My data file");
  const [credentials, setCredentials] = useState<
    Record<string, ConnectionCredentialValue>
  >({});
  const [rowKeys, setRowKeys] = useState<Record<string, RowKeyDefinition>>({});
  const [oauth, setOauth] = useState<GoogleOAuthStatus | null>(null);
  const [destination, setDestination] = useState<Destination | null>(null);
  const [selectedFileName, setSelectedFileName] = useState<string | null>(null);
  const [worksheetDiscovery, setWorksheetDiscovery] =
    useState<GoogleDriveWorksheetDiscovery | null>(null);
  const [loadingWorksheets, setLoadingWorksheets] = useState(false);
  const [loading, setLoading] = useState(true);
  const [picking, setPicking] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([
      api.googleDrive.config(),
      api.googleOAuth.status(),
      api.destinations.list(),
    ])
      .then(([nextConfig, nextOauth, destinations]) => {
        const nextDestination =
          destinations.find((item) => item.is_default) ?? destinations[0];

        if (!nextDestination) {
          throw new Error("No load destination is configured");
        }

        setConfig(nextConfig);
        setOauth(nextOauth);
        setDestination(nextDestination);
        setCredentials(
          Object.fromEntries(
            nextConfig.fields.map((field) => [
              field.key,
              String(field.default ?? ""),
            ]),
          ),
        );
      })
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    const fileId = credentialText(credentials.file_id);

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
        setCredentials((current) => ({
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
  }, [credentials.file_id, oauth?.picker_ready]);

  async function chooseDriveFile() {
    setError(null);
    setPicking(true);

    try {
      const session = await api.googlePicker.session();
      const selected = await openGoogleDriveFilePicker(session);

      if (!selected) {
        return;
      }

      setCredentials((current) => ({
        ...current,
        file_id: selected.id,
        file_name: selected.name,
        mime_type: selected.mimeType,
        sheets: ["*"],
      }));
      setWorksheetDiscovery(null);
      setSelectedFileName(selected.name);
      setRowKeys({});

      if (name === "My data file") {
        setName(selected.name);
      }
    } catch (err: any) {
      setError(err.message);
    } finally {
      setPicking(false);
    }
  }

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    setError(null);
    setSubmitting(true);

    try {
      const sheet = await api.connections.create({
        name: name.trim(),
        credentials,
        destination_id: destination?.id,
        row_keys: rowKeys,
      });
      navigate(`/data/${sheet.id}/edit`, {
        replace: true,
        state: { created: true },
      });
    } catch (err: any) {
      setError(err.message);
    } finally {
      setSubmitting(false);
    }
  }

  if (loading) {
    return (
      <StateMessage
        state="loading"
        variant="panel"
        message="Loading Google Drive data setup"
      />
    );
  }

  if (!config || !destination) {
    return (
      <StateMessage
        state="error"
        variant="panel"
        message={error ?? "Google Drive data setup is unavailable"}
      />
    );
  }

  return (
    <div className="max-w-lg space-y-4">
      <Button
        type="button"
        variant="ghost"
        onClick={() => navigate("/data/pipes")}
        className="mb-4 -ml-2 text-muted-foreground hover:text-foreground"
      >
        <ArrowLeft className="size-4" /> Back
      </Button>

      <form onSubmit={handleSubmit}>
        <ItemCard
          title="Connect Google Drive data"
          headerAction={<GoogleDriveDocumentationButton config={config} />}
          footer={
            <>
              <Button
                type="button"
                variant="outline"
                onClick={() => navigate("/data/pipes")}
              >
                Cancel
              </Button>
              <Button
                type="submit"
                variant="primary"
                disabled={
                  submitting ||
                  !oauth?.picker_ready ||
                  !credentials.file_id ||
                  loadingWorksheets
                }
              >
                {submitting ? "Connecting..." : "Connect data file"}
              </Button>
            </>
          }
        >
          <div className="space-y-5 text-foreground">
            <p className="text-sm text-muted-foreground">
              {config.description}
            </p>

            <div className="space-y-1.5">
              <Label htmlFor="sheet-name">Connection name</Label>
              <Input
                id="sheet-name"
                placeholder="Sales forecast"
                value={name}
                onChange={(event) => setName(event.target.value)}
                required
              />
              <p className="text-xs text-muted-foreground">
                A label agents and administrators can use to identify this
                source file.
              </p>
            </div>

            {!oauth?.connected && (
              <StateMessage
                state="warning"
                variant="inline"
                message="Connect Google from Data → Connections before adding a source file."
              />
            )}

            {oauth?.requires_reconnect && (
              <StateMessage
                state="warning"
                variant="inline"
                message="Reconnect Google from Data → Connections to enable file-specific Picker access."
              />
            )}

            {oauth?.connected && !oauth.picker_configured && (
              <StateMessage
                state="warning"
                variant="inline"
                message={
                  managed
                    ? "Google Drive file selection is currently unavailable. Please contact support."
                    : "Configure the Google Picker API key and project number before selecting a source file."
                }
              />
            )}

            {oauth?.picker_ready && (
              <div className="space-y-2 rounded-md border border-border bg-muted/20 p-4">
                <div className="flex items-center justify-between gap-3">
                  <div>
                    <Label>Google Drive file</Label>
                    <p className="mt-1 text-xs text-muted-foreground">
                      Browse My Drive, Shared with me, and Shared drives using
                      Google Picker.
                    </p>
                  </div>
                  <Button
                    type="button"
                    variant="outline"
                    disabled={picking}
                    onClick={() => void chooseDriveFile()}
                  >
                    <FolderOpen className="size-3.5" />
                    {picking ? "Opening..." : "Choose from Drive"}
                  </Button>
                </div>
                {selectedFileName && (
                  <p className="text-sm font-medium text-foreground">
                    Selected: {selectedFileName}
                  </p>
                )}
              </div>
            )}

            {config.fields
              .filter((field) => field.key !== "file_id" && !field.hidden)
              .map((field) =>
                field.key === "sheets" ? (
                  <WorksheetSelector
                    key={field.key}
                    field={field}
                    fileSelected={Boolean(credentialText(credentials.file_id))}
                    discovery={worksheetDiscovery}
                    loading={loadingWorksheets}
                    value={credentials.sheets}
                    onChange={(value) =>
                      setCredentials((previous) => ({
                        ...previous,
                        sheets: value,
                      }))
                    }
                  />
                ) : (
                  <SheetFieldInput
                    key={field.key}
                    field={field}
                    value={credentialText(credentials[field.key])}
                    onChange={(value) =>
                      setCredentials((previous) => ({
                        ...previous,
                        [field.key]: value,
                      }))
                    }
                  />
                ),
              )}

            <RowKeyEditor
              discovery={worksheetDiscovery}
              selectedWorksheets={credentials.sheets}
              value={rowKeys}
              onChange={setRowKeys}
            />

            <DestinationSummary destination={destination} />

            {error && (
              <StateMessage
                state="error"
                variant="inline"
                message={error}
                onClose={() => setError(null)}
              />
            )}
          </div>
        </ItemCard>
      </form>
    </div>
  );
}

function SheetFieldInput({
  field,
  value,
  onChange,
}: {
  field: SheetField;
  value: string;
  onChange: (value: string) => void;
}) {
  const sharedProps = {
    id: field.key,
    placeholder: field.placeholder,
    value,
    onChange: (
      event: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>,
    ) => onChange(event.target.value),
    required: field.required,
  };

  return (
    <div className="space-y-1.5">
      <Label htmlFor={field.key}>{field.label}</Label>
      {field.type === "textarea" && isSecretField(field) ? (
        <SecretTextarea {...sharedProps} rows={8} />
      ) : field.type === "textarea" ? (
        <textarea
          {...sharedProps}
          rows={8}
          className="min-h-32 w-full rounded-md border border-input bg-background px-3 py-2 text-sm shadow-sm outline-none transition-colors placeholder:text-muted-foreground focus-visible:ring-2 focus-visible:ring-ring"
        />
      ) : field.type === "secret" ? (
        <SecretInput {...sharedProps} />
      ) : (
        <Input {...sharedProps} type="text" />
      )}
      {field.help && (
        <p className="text-xs text-muted-foreground">{field.help}</p>
      )}
    </div>
  );
}

function isSecretField(field: SheetField) {
  return Boolean(field.secret || field.type === "secret");
}
