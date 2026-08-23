import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { ArrowLeft, FolderOpen } from "lucide-react";

import {
  api,
  type GoogleOAuthStatus,
  type GoogleSheetsConfig,
  type SheetField,
} from "@/lib/api";
import { openGoogleSpreadsheetPicker } from "@/lib/google-picker";
import { GoogleSheetsDocumentationButton } from "@/components/connections/google-sheets-documentation-button";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ItemCard } from "@/components/ui/item-grid";
import { Label } from "@/components/ui/label";
import { SecretInput, SecretTextarea } from "@/components/ui/secret-input";
import { StateMessage } from "@/components/ui/state-message";

export default function NewConnectionPage() {
  const navigate = useNavigate();
  const [config, setConfig] = useState<GoogleSheetsConfig | null>(null);
  const [name, setName] = useState("My spreadsheet");
  const [credentials, setCredentials] = useState<Record<string, string>>({});
  const [oauth, setOauth] = useState<GoogleOAuthStatus | null>(null);
  const [selectedSheetName, setSelectedSheetName] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [picking, setPicking] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([api.googleSheets.config(), api.googleOAuth.status()])
      .then(([nextConfig, nextOauth]) => {
        setConfig(nextConfig);
        setOauth(nextOauth);
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

  async function chooseSpreadsheet() {
    setError(null);
    setPicking(true);

    try {
      const session = await api.googlePicker.session();
      const selected = await openGoogleSpreadsheetPicker(session);

      if (!selected) {
        return;
      }

      setCredentials((current) => ({
        ...current,
        spreadsheet_id: selected.id,
      }));
      setSelectedSheetName(selected.name);

      if (name === "My spreadsheet") {
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
        message="Loading sheet data setup"
      />
    );
  }

  if (!config) {
    return (
      <StateMessage
        state="error"
        variant="panel"
        message={error ?? "Sheet data setup is unavailable"}
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
          title="Connect sheet data"
          headerAction={<GoogleSheetsDocumentationButton config={config} />}
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
                  !credentials.spreadsheet_id
                }
              >
                {submitting ? "Connecting..." : "Connect sheet data"}
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
                spreadsheet.
              </p>
            </div>

            {!oauth?.connected && (
              <StateMessage
                state="warning"
                variant="inline"
                message="Connect Google from Data → Connections before adding a spreadsheet."
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
                message="Configure the Google Picker API key and project number before selecting a spreadsheet."
              />
            )}

            {oauth?.picker_ready && (
              <div className="space-y-2 rounded-md border border-border bg-muted/20 p-4">
                <div className="flex items-center justify-between gap-3">
                  <div>
                    <Label>Google spreadsheet</Label>
                    <p className="mt-1 text-xs text-muted-foreground">
                      Browse My Drive, Shared with me, and Shared drives using
                      Google Picker.
                    </p>
                  </div>
                  <Button
                    type="button"
                    variant="outline"
                    disabled={picking}
                    onClick={() => void chooseSpreadsheet()}
                  >
                    <FolderOpen className="size-3.5" />
                    {picking ? "Opening..." : "Choose from Drive"}
                  </Button>
                </div>
                {selectedSheetName && (
                  <p className="text-sm font-medium text-foreground">
                    Selected: {selectedSheetName}
                  </p>
                )}
              </div>
            )}

            {config.fields
              .filter((field) => field.key !== "spreadsheet_id")
              .map((field) => (
              <SheetFieldInput
                key={field.key}
                field={field}
                value={credentials[field.key] ?? ""}
                onChange={(value) =>
                  setCredentials((previous) => ({
                    ...previous,
                    [field.key]: value,
                  }))
                }
              />
              ))}

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
