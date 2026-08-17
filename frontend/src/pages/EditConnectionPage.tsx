import { useEffect, useState } from "react";
import { useLocation, useNavigate, useParams } from "react-router-dom";
import { ArrowLeft } from "lucide-react";
import {
  api,
  type Connection,
  type GoogleSheetsConfig,
  type SheetField,
} from "@/lib/api";
import { GoogleSheetsDocumentationButton } from "@/components/connections/google-sheets-documentation-button";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { SecretInput, SecretTextarea } from "@/components/ui/secret-input";
import { StateMessage } from "@/components/ui/state-message";

export default function EditConnectionPage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const location = useLocation();
  const [connection, setConnection] = useState<Connection | null>(null);
  const [config, setConfig] = useState<GoogleSheetsConfig | null>(null);
  const [name, setName] = useState("");
  const [creds, setCreds] = useState<Record<string, string>>({});
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(() =>
    Boolean((location.state as { created?: boolean } | null)?.created)
      ? "Connection created."
      : null,
  );
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    Promise.all([api.connections.get(Number(id)), api.googleSheets.config()])
      .then(([conn, nextConfig]) => {
        setConnection(conn);
        setName(conn.name);
        setConfig(nextConfig);
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
      });
      setConnection(updated);
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
    <div className="space-y-6 max-w-lg">
      <div>
        <Button
          type="button"
          variant="ghost"
          onClick={() => navigate("/sheets")}
          className="mb-4 -ml-2 text-muted-foreground hover:text-foreground"
        >
          <ArrowLeft className="size-4" /> Back
        </Button>
        <div className="flex items-center gap-1.5">
          <h1 className="text-2xl font-semibold">Edit connection</h1>
          <GoogleSheetsDocumentationButton config={config} />
        </div>
        <p className="text-sm text-muted-foreground mt-1">
          Update spreadsheet access and tab selection. Saved secrets can be left
          blank to keep the existing value.
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

        {config.fields.map((field) => {
          const hasSavedSecret = connection.secret_fields?.includes(field.key);
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
              {field.type === "textarea" && isSecretField(field) ? (
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
              {help && <p className="text-xs text-muted-foreground">{help}</p>}
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
            onClick={() => navigate("/sheets")}
          >
            Cancel
          </Button>
        </div>
      </form>
    </div>
  );
}

function isSecretField(field: SheetField) {
  return Boolean(field.secret || field.type === "secret");
}
