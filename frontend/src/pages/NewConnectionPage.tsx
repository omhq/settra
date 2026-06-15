import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { ArrowLeft } from "lucide-react";
import { api, type Connector, type ConnectorField } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ItemCard, ItemGrid } from "@/components/ui/item-grid";
import { Label } from "@/components/ui/label";
import { SecretInput } from "@/components/ui/secret-input";
import { StateMessage } from "@/components/ui/state-message";

function SelectConnector({
  connectors,
  onSelect,
}: {
  connectors: Connector[];
  onSelect: (c: Connector) => void;
}) {
  const navigate = useNavigate();

  return (
    <div className="space-y-6">
      <div>
        <Button
          type="button"
          variant="ghost"
          onClick={() => navigate("/connections")}
          className="mb-4 -ml-2 text-muted-foreground hover:text-foreground"
        >
          <ArrowLeft className="size-4" /> Back
        </Button>
        <h1 className="text-2xl font-semibold">Add connection</h1>
        <p className="text-sm text-muted-foreground mt-1">
          Choose a data source to connect
        </p>
      </div>
      <ItemGrid>
        {connectors.map((c) => (
          <ItemCard
            key={c.key}
            title={c.name}
            footer={
              <Button
                type="button"
                size="sm"
                variant="primary"
                onClick={() => onSelect(c)}
              >
                Select
              </Button>
            }
          >
            <div className="space-y-3">
              <p>{c.description}</p>
            </div>
          </ItemCard>
        ))}
      </ItemGrid>
    </div>
  );
}

// ── Step 2: fill in the form ──────────────────────────────────────────────────

function ConfigureConnector({
  connector,
  onBack,
}: {
  connector: Connector;
  onBack: () => void;
}) {
  const navigate = useNavigate();
  const [name, setName] = useState("");
  const [creds, setCreds] = useState<Record<string, string>>(() =>
    Object.fromEntries(
      connector.fields.map((f) => [f.key, String(f.default ?? "")]),
    ),
  );
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      const connection = await api.connections.create({
        name: name.trim(),
        plugin: connector.key,
        credentials: creds,
      });
      await api.semantics.introspect(connection.id).catch(() => undefined);
      navigate(`/connections/${connection.id}/edit`, {
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
          title={`Connect ${connector.name}`}
          pills={<Badge variant="secondary">{connector.plugin}</Badge>}
          footer={
            <>
              <Button type="button" variant="outline" onClick={onBack}>
                Cancel
              </Button>
              <Button type="submit" variant="primary" disabled={submitting}>
                {submitting ? "Connecting..." : "Save connection"}
              </Button>
            </>
          }
        >
          <div className="space-y-5 text-foreground">
            <p className="text-sm text-muted-foreground">
              {connector.description}
            </p>
            <div className="space-y-1.5">
              <Label htmlFor="conn-name">Connection name</Label>
              <Input
                id="conn-name"
                placeholder={`My ${connector.name} account`}
                value={name}
                onChange={(e) => setName(e.target.value)}
                required
              />
              <p className="text-xs text-muted-foreground">
                A label to identify this connection. You can add multiple{" "}
                {connector.name} accounts.
              </p>
            </div>

            {connector.fields.map((field: ConnectorField) => (
              <div key={field.key} className="space-y-1.5">
                <Label htmlFor={field.key}>{field.label}</Label>
                {field.type === "textarea" ? (
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
                    required={field.required}
                    rows={8}
                    className="min-h-32 w-full rounded-md border border-input bg-background px-3 py-2 text-sm shadow-sm outline-none transition-colors placeholder:text-muted-foreground focus-visible:ring-2 focus-visible:ring-ring"
                  />
                ) : field.type === "secret" ? (
                  <SecretInput
                    id={field.key}
                    placeholder={field.placeholder}
                    value={creds[field.key] ?? ""}
                    onChange={(e) =>
                      setCreds((prev) => ({
                        ...prev,
                        [field.key]: e.target.value,
                      }))
                    }
                    required={field.required}
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
          </div>
        </ItemCard>
      </form>
    </div>
  );
}

// ── Page ─────────────────────────────────────────────────────────────────────

export default function NewConnectionPage() {
  const [connectors, setConnectors] = useState<Connector[]>([]);
  const [selected, setSelected] = useState<Connector | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.connectors
      .list()
      .then(setConnectors)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  if (loading)
    return (
      <StateMessage
        state="loading"
        variant="panel"
        message="Loading connectors"
      />
    );
  if (error)
    return <StateMessage state="error" variant="panel" message={error} />;

  if (selected) {
    return (
      <ConfigureConnector
        connector={selected}
        onBack={() => setSelected(null)}
      />
    );
  }

  return <SelectConnector connectors={connectors} onSelect={setSelected} />;
}
