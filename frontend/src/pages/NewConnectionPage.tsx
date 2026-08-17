import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { ArrowLeft } from "lucide-react";

import { api, type GoogleSheetsConfig, type SheetField } from "@/lib/api";
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
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.googleSheets
      .config()
      .then((nextConfig) => {
        setConfig(nextConfig);
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

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    setError(null);
    setSubmitting(true);

    try {
      const sheet = await api.connections.create({
        name: name.trim(),
        credentials,
      });
      navigate(`/sheets/${sheet.id}/edit`, {
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
        onClick={() => navigate("/sheets")}
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
                onClick={() => navigate("/sheets")}
              >
                Cancel
              </Button>
              <Button type="submit" variant="primary" disabled={submitting}>
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

            {config.fields.map((field) => (
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
