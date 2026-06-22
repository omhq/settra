import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { ArrowLeft } from "lucide-react";
import { api, type ConnectorField, type ModelProvider } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ItemCard, ItemGrid } from "@/components/ui/item-grid";
import { Label } from "@/components/ui/label";
import { SecretInput } from "@/components/ui/secret-input";
import { StateMessage } from "@/components/ui/state-message";

function initialConfig(provider: ModelProvider) {
  return Object.fromEntries(
    provider.fields.map((field) => [field.key, field.default ?? ""]),
  );
}

function fieldInputType(field: ConnectorField) {
  if (field.type === "number") return "number";
  return "text";
}

function SelectProvider({
  providers,
  onSelect,
}: {
  providers: ModelProvider[];
  onSelect: (provider: ModelProvider) => void;
}) {
  const navigate = useNavigate();

  return (
    <div className="space-y-6">
      <div>
        <Button
          type="button"
          variant="ghost"
          onClick={() => navigate("/models")}
          className="mb-4 -ml-2 text-muted-foreground hover:text-foreground"
        >
          <ArrowLeft className="size-4" /> Back
        </Button>
        <h1 className="text-2xl font-semibold">Add model</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Choose a model provider
        </p>
      </div>

      <ItemGrid>
        {providers.map((provider) => (
          <ItemCard
            key={provider.key}
            title={provider.name}
            footer={
              <Button
                type="button"
                size="sm"
                variant="primary"
                onClick={() => onSelect(provider)}
              >
                Select
              </Button>
            }
          >
            {provider.description}
          </ItemCard>
        ))}
      </ItemGrid>
    </div>
  );
}

function ConfigureModel({
  provider,
  onBack,
}: {
  provider: ModelProvider;
  onBack: () => void;
}) {
  const navigate = useNavigate();
  const [name, setName] = useState("");
  const [config, setConfig] = useState<Record<string, string | number>>(() =>
    initialConfig(provider),
  );
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    setError(null);
    setSubmitting(true);

    try {
      const model = await api.models.create({
        name: name.trim(),
        provider: provider.key,
        config,
      });
      navigate(`/models/${model.id}/edit`, {
        replace: true,
        state: { created: true },
      });
    } catch (err: any) {
      setError(err.message);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="max-w-lg space-y-4">
      <div>
        <Button
          type="button"
          variant="ghost"
          onClick={onBack}
          className="mb-4 -ml-2 text-muted-foreground hover:text-foreground"
        >
          <ArrowLeft className="size-4" /> Back
        </Button>
      </div>

      <form onSubmit={handleSubmit}>
        <ItemCard
          title={`Configure ${provider.name}`}
          pills={<Badge variant="secondary">{provider.key}</Badge>}
          footer={
            <>
              <Button type="button" variant="outline" onClick={onBack}>
                Cancel
              </Button>
              <Button type="submit" variant="primary" disabled={submitting}>
                {submitting ? "Saving..." : "Save model"}
              </Button>
            </>
          }
        >
          <div className="space-y-5 text-foreground">
            {provider.description && (
              <p className="text-sm text-muted-foreground">
                {provider.description}
              </p>
            )}
            <div className="space-y-1.5">
              <Label htmlFor="model-name">Model config name</Label>
              <Input
                id="model-name"
                value={name}
                onChange={(event) => setName(event.target.value)}
                placeholder={`${provider.name} analytics`}
                required
              />
              <p className="text-xs text-muted-foreground">
                A label to identify this model configuration.
              </p>
            </div>

            {provider.fields.map((field) => (
              <div key={field.key} className="space-y-1.5">
                <Label htmlFor={field.key}>{field.label}</Label>
                {field.type === "secret" ? (
                  <SecretInput
                    id={field.key}
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
              </div>
            ))}

            {error && (
              <StateMessage state="error" variant="inline" message={error} />
            )}
          </div>
        </ItemCard>
      </form>
    </div>
  );
}

export default function NewModelPage() {
  const [providers, setProviders] = useState<ModelProvider[]>([]);
  const [selected, setSelected] = useState<ModelProvider | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.modelProviders
      .list()
      .then(setProviders)
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false));
  }, []);

  if (loading)
    return (
      <StateMessage
        state="loading"
        variant="panel"
        message="Loading model providers"
      />
    );
  if (error)
    return <StateMessage state="error" variant="panel" message={error} />;

  if (selected) {
    return (
      <ConfigureModel provider={selected} onBack={() => setSelected(null)} />
    );
  }

  return <SelectProvider providers={providers} onSelect={setSelected} />;
}
