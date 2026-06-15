import { useEffect, useState } from "react";
import { useLocation, useNavigate, useParams } from "react-router-dom";
import { ArrowLeft } from "lucide-react";
import {
  api,
  type ConnectorField,
  type ModelConfig,
  type ModelProvider,
} from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { SecretInput } from "@/components/ui/secret-input";
import { StateMessage } from "@/components/ui/state-message";

function fieldInputType(field: ConnectorField) {
  if (field.type === "number") return "number";
  return "text";
}

function initialConfig(provider: ModelProvider, model: ModelConfig) {
  return Object.fromEntries(
    provider.fields.map((field) => {
      if (field.type === "secret") return [field.key, ""];
      return [
        field.key,
        (model.config[field.key] as string | number | undefined) ??
          field.default ??
          "",
      ];
    }),
  );
}

export default function EditModelPage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const location = useLocation();
  const [model, setModel] = useState<ModelConfig | null>(null);
  const [provider, setProvider] = useState<ModelProvider | null>(null);
  const [name, setName] = useState("");
  const [config, setConfig] = useState<Record<string, string | number>>({});
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(() =>
    Boolean((location.state as { created?: boolean } | null)?.created)
      ? "Model saved."
      : null,
  );
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    Promise.all([api.models.get(Number(id)), api.modelProviders.list()])
      .then(([modelConfig, providers]) => {
        const providerDef =
          providers.find((item) => item.key === modelConfig.provider) ?? null;
        if (!providerDef) throw new Error("Model provider not found");

        setModel(modelConfig);
        setProvider(providerDef);
        setName(modelConfig.name);
        setConfig(initialConfig(providerDef, modelConfig));
      })
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false));
  }, [id]);

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    if (!provider) return;

    setError(null);
    setNotice(null);
    setSubmitting(true);

    try {
      const updated = await api.models.update(Number(id!), {
        name: name.trim(),
        config,
      });
      setModel(updated);
      setName(updated.name);
      setConfig(initialConfig(provider, updated));
      setNotice("Model updated.");
    } catch (err: any) {
      setError(err.message);
    } finally {
      setSubmitting(false);
    }
  }

  async function revealSavedSecret(fieldKey: string) {
    if (!model || config[fieldKey]) return;
    if (!model.secret_fields.includes(fieldKey)) return;

    setError(null);
    try {
      const secrets = (await api.models.secrets(model.id)).secrets;
      const value = secrets[fieldKey];
      if (!value) throw new Error("Saved secret not found.");

      setConfig((prev) => ({ ...prev, [fieldKey]: value }));
    } catch (err: any) {
      setError(err.message);
      throw err;
    }
  }

  function concealSecret(fieldKey: string) {
    setConfig((prev) => ({ ...prev, [fieldKey]: "" }));
  }

  if (loading)
    return (
      <StateMessage state="loading" variant="panel" message="Loading model" />
    );
  if (!model || !provider)
    return (
      <StateMessage
        state="error"
        variant="panel"
        message={error ?? "Model not found"}
      />
    );

  return (
    <div className="max-w-lg space-y-6">
      <div>
        <Button
          type="button"
          variant="ghost"
          onClick={() => navigate("/models")}
          className="mb-4 -ml-2 text-muted-foreground hover:text-foreground"
        >
          <ArrowLeft className="size-4" /> Back
        </Button>
        <h1 className="text-2xl font-semibold">Edit model</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Update {provider.name}. Leave secret fields blank to keep the saved
          value.
        </p>
      </div>

      {notice && (
        <StateMessage state="success" variant="banner" message={notice} />
      )}

      <form onSubmit={handleSubmit} className="space-y-5">
        <div className="space-y-1.5">
          <Label htmlFor="model-name">Model config name</Label>
          <Input
            id="model-name"
            value={name}
            onChange={(event) => setName(event.target.value)}
            required
          />
        </div>

        {provider.fields.map((field) => (
          <div key={field.key} className="space-y-1.5">
            <Label htmlFor={field.key}>{field.label}</Label>
            {field.type === "secret" ? (
              <SecretInput
                id={field.key}
                placeholder={field.placeholder}
                value={config[field.key] ?? ""}
                onConceal={() => concealSecret(field.key)}
                onReveal={() => revealSavedSecret(field.key)}
                onChange={(event) =>
                  setConfig((prev) => ({
                    ...prev,
                    [field.key]: event.target.value,
                  }))
                }
                required={false}
              />
            ) : (
              <Input
                id={field.key}
                type={fieldInputType(field)}
                min={field.min}
                max={field.max}
                placeholder={field.placeholder}
                value={config[field.key] ?? ""}
                onChange={(event) =>
                  setConfig((prev) => ({
                    ...prev,
                    [field.key]: event.target.value,
                  }))
                }
                required={field.required}
              />
            )}
            {field.help && (
              <p className="text-xs text-muted-foreground">{field.help}</p>
            )}
          </div>
        ))}

        {error && (
          <StateMessage state="error" variant="inline" message={error} />
        )}

        <div className="flex gap-3 pt-2">
          <Button type="submit" variant="primary" disabled={submitting}>
            {submitting ? "Saving..." : "Save changes"}
          </Button>
          <Button
            type="button"
            variant="outline"
            onClick={() => navigate("/models")}
          >
            Cancel
          </Button>
        </div>
      </form>
    </div>
  );
}
