import { useEffect, useMemo, useState } from "react";
import { useLocation, useNavigate, useParams } from "react-router-dom";
import { ArrowLeft, Check, Copy } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ItemCard, ItemGrid } from "@/components/ui/item-grid";
import { Label } from "@/components/ui/label";
import {
  MultiSelect,
  type MultiSelectOption,
} from "@/components/ui/multi-select";
import { SecretInput } from "@/components/ui/secret-input";
import { SelectMenu, type SelectMenuOption } from "@/components/ui/select-menu";
import { StateMessage } from "@/components/ui/state-message";
import {
  channelWebhookPath,
  channelWebhookUrl,
  defaultPublicApiUrl,
  readStoredPublicApiUrl,
  storePublicApiUrl,
  telegramSetWebhookCurl,
} from "@/lib/channels";
import {
  api,
  type Connection,
  type ConnectorField,
  type MessagingConfig,
  type MessagingProvider,
  type ModelConfig,
} from "@/lib/api";

type ChannelFormValue = string | number | boolean;
type ChannelFormValues = Record<string, ChannelFormValue>;

const progressModeOptions: SelectMenuOption[] = [
  {
    value: "compact",
    label: "Compact",
    description: "Send a small number of progress updates.",
  },
  {
    value: "silent",
    label: "Silent",
    description: "Send only the final response.",
  },
  {
    value: "verbose",
    label: "Verbose",
    description: "Send each visible chat step.",
  },
];

function initialValues(
  provider: MessagingProvider,
  channel?: MessagingConfig | null,
) {
  return Object.fromEntries(
    provider.fields.map((field) => {
      if (field.type === "secret") return [field.key, ""];

      const saved = channel?.config[field.key] as ChannelFormValue | undefined;
      return [
        field.key,
        saved ?? field.default ?? (field.type === "boolean" ? false : ""),
      ];
    }),
  ) as ChannelFormValues;
}

function fieldInputType(field: ConnectorField) {
  if (field.type === "number") return "number";
  return "text";
}

function providerByKey(providers: MessagingProvider[], key: string) {
  return providers.find((provider) => provider.key === key) ?? null;
}

function SelectProvider({
  providers,
  onSelect,
}: {
  providers: MessagingProvider[];
  onSelect: (provider: MessagingProvider) => void;
}) {
  const navigate = useNavigate();

  return (
    <div className="space-y-6">
      <div>
        <Button
          type="button"
          variant="ghost"
          onClick={() => navigate("/channels")}
          className="mb-4 -ml-2 text-muted-foreground hover:text-foreground"
        >
          <ArrowLeft className="size-4" /> Back
        </Button>
        <h1 className="text-2xl font-semibold">Add channel</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Choose a mounted channel provider
        </p>
      </div>

      {providers.length === 0 ? (
        <StateMessage
          state="empty"
          variant="panel"
          title="No channel providers mounted"
          message="Mounted channel definitions appear here after the backend discovers them."
        />
      ) : (
        <ItemGrid>
          {providers.map((provider) => (
            <ItemCard
              key={provider.key}
              title={provider.name}
              pills={
                <>
                  {provider.delivery_modes.map((mode) => (
                    <Badge
                      key={mode}
                      variant="secondary"
                      className="capitalize"
                    >
                      {mode}
                    </Badge>
                  ))}
                </>
              }
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
      )}
    </div>
  );
}

function WebhookEndpoint({
  channel,
  provider,
}: {
  channel: MessagingConfig;
  provider: MessagingProvider;
}) {
  const [copiedKey, setCopiedKey] = useState<string | null>(null);
  const [publicApiUrl, setPublicApiUrl] = useState(defaultPublicApiUrl);
  const webhookUrl = channelWebhookUrl(provider.key, channel.id, publicApiUrl);
  const setWebhookCurl = telegramSetWebhookCurl({ webhookUrl });
  const setWebhookCurlWithSecret = telegramSetWebhookCurl({
    webhookUrl,
    includeSecret: true,
  });

  useEffect(() => {
    if (readStoredPublicApiUrl()) return;

    let cancelled = false;

    api.config
      .get()
      .then((config) => {
        if (cancelled || !config.public_api_url) return;
        setPublicApiUrl((current) =>
          readStoredPublicApiUrl() ? current : config.public_api_url,
        );
      })
      .catch(() => undefined);

    return () => {
      cancelled = true;
    };
  }, []);

  function updatePublicApiUrl(value: string) {
    setPublicApiUrl(value);
    storePublicApiUrl(value);
  }

  async function copyText(key: string, text: string) {
    await navigator.clipboard.writeText(text);
    setCopiedKey(key);
    window.setTimeout(() => setCopiedKey(null), 1500);
  }

  return (
    <div className="space-y-4">
      <div className="space-y-1.5">
        <Label htmlFor="channel-public-api-url">Public API URL</Label>
        <Input
          id="channel-public-api-url"
          placeholder="https://example.ngrok-free.app"
          value={publicApiUrl}
          onChange={(event) => updatePublicApiUrl(event.target.value)}
        />
        <p className="text-xs text-muted-foreground">
          Defaults from the server runtime config. Local edits are saved in this
          browser.
        </p>
      </div>

      <CopyBlock
        label="Webhook URL"
        copied={copiedKey === "webhook"}
        text={webhookUrl}
        onCopy={() => copyText("webhook", webhookUrl)}
      />

      {provider.key === "telegram" && (
        <div className="space-y-3">
          <CopyBlock
            label="Telegram setWebhook"
            copied={copiedKey === "telegram-webhook"}
            text={setWebhookCurl}
            multiline
            onCopy={() => copyText("telegram-webhook", setWebhookCurl)}
          />
          <CopyBlock
            label="Telegram setWebhook with secret"
            copied={copiedKey === "telegram-webhook-secret"}
            text={setWebhookCurlWithSecret}
            multiline
            onCopy={() =>
              copyText("telegram-webhook-secret", setWebhookCurlWithSecret)
            }
          />
        </div>
      )}
    </div>
  );
}

function CopyBlock({
  label,
  text,
  copied,
  multiline = false,
  onCopy,
}: {
  label: string;
  text: string;
  copied: boolean;
  multiline?: boolean;
  onCopy: () => Promise<void>;
}) {
  return (
    <div className="space-y-1.5">
      <Label>{label}</Label>
      <div className="flex min-w-0 gap-2">
        <code className="min-w-0 flex-1 overflow-x-auto whitespace-pre-wrap rounded-lg border bg-muted/30 px-2.5 py-2 text-xs leading-5 text-foreground">
          {text}
        </code>
        <Button
          type="button"
          variant="outline"
          size="icon"
          title={copied ? "Copied" : `Copy ${label}`}
          aria-label={copied ? "Copied" : `Copy ${label}`}
          className={multiline ? "mt-0.5" : undefined}
          onClick={() => void onCopy()}
        >
          {copied ? <Check className="size-4" /> : <Copy className="size-4" />}
        </Button>
      </div>
    </div>
  );
}

function ProviderSetupHint({
  provider,
  channel,
}: {
  provider: MessagingProvider;
  channel?: MessagingConfig | null;
}) {
  if (provider.key !== "telegram") return null;

  const webhookPath = channel
    ? channelWebhookPath(provider.key, channel.id)
    : null;

  return (
    <StateMessage
      state="info"
      variant="inline"
      message={
        <div className="space-y-2">
          <p>
            Register Telegram with your public API host plus the webhook path.
          </p>
          {webhookPath ? (
            <code className="block break-all rounded-md bg-background px-2 py-1 text-xs text-foreground">
              {webhookPath}
            </code>
          ) : (
            <p>Save the channel to generate the webhook path.</p>
          )}
          <p>
            Add <code>secret_token</code> only when Webhook Secret Token is set.
          </p>
        </div>
      }
    />
  );
}

function ChannelForm({
  mode,
  provider,
  channel,
  connections,
  models,
  initialNotice,
  onBack,
}: {
  mode: "new" | "edit";
  provider: MessagingProvider;
  channel?: MessagingConfig | null;
  connections: Connection[];
  models: ModelConfig[];
  initialNotice?: string | null;
  onBack: () => void;
}) {
  const navigate = useNavigate();
  const [name, setName] = useState(channel?.name ?? "");
  const [values, setValues] = useState<ChannelFormValues>(() =>
    initialValues(provider, channel),
  );
  const [connectionIds, setConnectionIds] = useState<string[]>(() =>
    (channel?.connection_ids ?? []).map(String),
  );
  const [modelConfigId, setModelConfigId] = useState<string | null>(
    channel?.model_config_id ? String(channel.model_config_id) : null,
  );
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(initialNotice ?? null);

  const connectionOptions = useMemo<MultiSelectOption[]>(
    () =>
      connections.map((connection) => ({
        value: String(connection.id),
        label: connection.name,
        description: connection.plugin,
        disabled: connection.status !== "active",
      })),
    [connections],
  );
  const activeConnectionIds = useMemo(
    () =>
      new Set(
        connections
          .filter((connection) => connection.status === "active")
          .map((connection) => String(connection.id)),
      ),
    [connections],
  );

  const modelOptions = useMemo<SelectMenuOption[]>(
    () =>
      models.map((model) => ({
        value: String(model.id),
        label: model.name,
        description: `${model.provider} / ${model.model}`,
        disabled: model.status !== "active",
      })),
    [models],
  );
  const activeModelIds = useMemo(
    () =>
      new Set(
        models
          .filter((model) => model.status === "active")
          .map((model) => String(model.id)),
      ),
    [models],
  );

  const submitDisabled =
    submitting ||
    !name.trim() ||
    !modelConfigId ||
    !activeModelIds.has(modelConfigId) ||
    connectionIds.length === 0 ||
    !connectionIds.every((connectionId) =>
      activeConnectionIds.has(connectionId),
    );

  function updateValue(key: string, value: ChannelFormValue) {
    setValues((prev) => ({ ...prev, [key]: value }));
  }

  async function revealSavedSecret(fieldKey: string) {
    if (mode !== "edit" || !channel || values[fieldKey]) return;
    if (!channel.secret_fields.includes(fieldKey)) return;

    setError(null);
    try {
      const secrets = (await api.messaging.configs.secrets(channel.id)).secrets;
      const value = secrets[fieldKey];
      if (!value) throw new Error("Saved secret not found.");

      updateValue(fieldKey, value);
    } catch (err: any) {
      setError(err.message);
      throw err;
    }
  }

  function concealSecret(fieldKey: string) {
    updateValue(fieldKey, "");
  }

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    if (!modelConfigId) return;

    setError(null);
    setNotice(null);
    setSubmitting(true);

    const body = {
      name: name.trim(),
      config: values,
      model_config_id: Number(modelConfigId),
      connection_ids: connectionIds.map(Number),
    };

    try {
      if (mode === "new") {
        const created = await api.messaging.configs.create({
          ...body,
          provider: provider.key,
        });
        navigate(`/channels/${created.id}/edit`, {
          replace: true,
          state: { created: true },
        });
        return;
      }

      if (!channel) return;
      const updated = await api.messaging.configs.update(channel.id, body);
      setName(updated.name);
      setValues(initialValues(provider, updated));
      setConnectionIds(updated.connection_ids.map(String));
      setModelConfigId(String(updated.model_config_id));
      setNotice("Channel updated.");
    } catch (err: any) {
      setError(err.message);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="max-w-2xl space-y-6">
      <div>
        <Button
          type="button"
          variant="ghost"
          onClick={onBack}
          className="mb-4 -ml-2 text-muted-foreground hover:text-foreground"
        >
          <ArrowLeft className="size-4" /> Back
        </Button>
        <h1 className="text-2xl font-semibold">
          {mode === "new" ? "Add channel" : "Edit channel"}
        </h1>
        <p className="mt-1 text-sm text-muted-foreground">
          {provider.name} receives mobile chat messages and routes them through
          Settra chat.
        </p>
      </div>

      {notice && (
        <StateMessage state="success" variant="banner" message={notice} />
      )}

      <form onSubmit={handleSubmit}>
        <ItemCard
          title={mode === "new" ? `Configure ${provider.name}` : channel?.name}
          pills={
            <>
              <Badge variant="secondary">{provider.name}</Badge>
              {provider.delivery_modes.map((mode) => (
                <Badge key={mode} variant="outline" className="capitalize">
                  {mode}
                </Badge>
              ))}
            </>
          }
          footer={
            <>
              <Button type="button" variant="outline" onClick={onBack}>
                Cancel
              </Button>
              <Button type="submit" variant="primary" disabled={submitDisabled}>
                {submitting ? "Saving..." : "Save channel"}
              </Button>
            </>
          }
          className="min-h-0"
        >
          <div className="space-y-5 text-foreground">
            {provider.description && (
              <p className="text-sm text-muted-foreground">
                {provider.description}
              </p>
            )}

            {mode === "edit" && channel && (
              <WebhookEndpoint channel={channel} provider={provider} />
            )}

            <ProviderSetupHint provider={provider} channel={channel} />

            <div className="space-y-1.5">
              <Label htmlFor="channel-name">Channel name</Label>
              <Input
                id="channel-name"
                placeholder={`${provider.name} support`}
                value={name}
                onChange={(event) => setName(event.target.value)}
                required
              />
            </div>

            <div className="space-y-1.5">
              <Label htmlFor="channel-model">Default model</Label>
              <SelectMenu
                value={modelConfigId}
                onChange={setModelConfigId}
                options={modelOptions}
                placeholder="Select model"
                triggerClassName="h-8"
              />
            </div>

            <div className="space-y-1.5">
              <Label htmlFor="channel-connections">Default connections</Label>
              <MultiSelect
                value={connectionIds}
                onChange={setConnectionIds}
                options={connectionOptions}
                placeholder="Select connections"
                triggerClassName="h-8"
              />
            </div>

            {activeConnectionIds.size === 0 && (
              <StateMessage
                state="warning"
                variant="inline"
                message="Add an active connection before saving a channel."
              />
            )}
            {activeModelIds.size === 0 && (
              <StateMessage
                state="warning"
                variant="inline"
                message="Add an active model before saving a channel."
              />
            )}

            {provider.fields.map((field) => {
              const hasSavedSecret =
                mode === "edit" &&
                field.type === "secret" &&
                Boolean(channel?.secret_fields.includes(field.key));
              const required = Boolean(
                field.required && !(field.type === "secret" && mode === "edit"),
              );
              const help = [
                field.help,
                hasSavedSecret
                  ? "Saved. Leave blank to keep the existing value."
                  : null,
              ]
                .filter(Boolean)
                .join(" ");

              if (field.key === "progress_mode") {
                return (
                  <div key={field.key} className="space-y-1.5">
                    <Label htmlFor={field.key}>{field.label}</Label>
                    <SelectMenu
                      value={String(values[field.key] ?? "compact")}
                      onChange={(value) => updateValue(field.key, value)}
                      options={progressModeOptions}
                      placeholder="Select mode"
                      triggerClassName="h-8"
                    />
                    {help && (
                      <p className="text-xs text-muted-foreground">{help}</p>
                    )}
                  </div>
                );
              }

              if (field.type === "boolean") {
                return (
                  <div key={field.key} className="space-y-1.5">
                    <label className="flex items-center gap-2 text-sm font-medium">
                      <input
                        id={field.key}
                        type="checkbox"
                        checked={Boolean(values[field.key])}
                        onChange={(event) =>
                          updateValue(field.key, event.target.checked)
                        }
                        className="size-4 rounded border-input"
                      />
                      {field.label}
                    </label>
                    {help && (
                      <p className="text-xs text-muted-foreground">{help}</p>
                    )}
                  </div>
                );
              }

              return (
                <div key={field.key} className="space-y-1.5">
                  <Label htmlFor={field.key}>{field.label}</Label>
                  {field.type === "textarea" ? (
                    <textarea
                      id={field.key}
                      placeholder={field.placeholder}
                      value={String(values[field.key] ?? "")}
                      onChange={(event) =>
                        updateValue(field.key, event.target.value)
                      }
                      required={required}
                      rows={8}
                      className="min-h-32 w-full rounded-lg border border-input bg-transparent px-2.5 py-2 text-sm shadow-sm outline-none transition-colors placeholder:text-muted-foreground focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50"
                    />
                  ) : field.type === "secret" ? (
                    <SecretInput
                      id={field.key}
                      placeholder={field.placeholder}
                      value={String(values[field.key] ?? "")}
                      onConceal={() => concealSecret(field.key)}
                      onReveal={() => revealSavedSecret(field.key)}
                      onChange={(event) =>
                        updateValue(field.key, event.target.value)
                      }
                      required={required}
                    />
                  ) : (
                    <Input
                      id={field.key}
                      type={fieldInputType(field)}
                      min={field.min}
                      max={field.max}
                      placeholder={field.placeholder}
                      value={String(values[field.key] ?? "")}
                      onChange={(event) =>
                        updateValue(field.key, event.target.value)
                      }
                      required={required}
                    />
                  )}
                  {help && (
                    <p className="text-xs text-muted-foreground">{help}</p>
                  )}
                </div>
              );
            })}

            {error && (
              <StateMessage state="error" variant="inline" message={error} />
            )}
          </div>
        </ItemCard>
      </form>
    </div>
  );
}

function useChannelFormData(mode: "new" | "edit") {
  const { id } = useParams<{ id: string }>();
  const [providers, setProviders] = useState<MessagingProvider[]>([]);
  const [connections, setConnections] = useState<Connection[]>([]);
  const [models, setModels] = useState<ModelConfig[]>([]);
  const [channel, setChannel] = useState<MessagingConfig | null>(null);
  const [selectedProvider, setSelectedProvider] =
    useState<MessagingProvider | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const requests: [
      Promise<MessagingProvider[]>,
      Promise<Connection[]>,
      Promise<ModelConfig[]>,
      Promise<MessagingConfig | null>,
    ] = [
      api.messaging.providers.list(),
      api.connections.list(),
      api.models.list(),
      mode === "edit" && id
        ? api.messaging.configs.get(Number(id))
        : Promise.resolve(null),
    ];

    Promise.all(requests)
      .then(([providerItems, connectionItems, modelItems, channelConfig]) => {
        setProviders(providerItems);
        setConnections(connectionItems);
        setModels(modelItems);
        setChannel(channelConfig);

        if (mode === "edit" && channelConfig) {
          const provider = providerByKey(providerItems, channelConfig.provider);
          if (!provider) throw new Error("Channel provider not found");
          setSelectedProvider(provider);
        }
      })
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false));
  }, [id, mode]);

  return {
    providers,
    connections,
    models,
    channel,
    selectedProvider,
    setSelectedProvider,
    loading,
    error,
  };
}

export function NewChannelPage() {
  const data = useChannelFormData("new");

  if (data.loading)
    return (
      <StateMessage
        state="loading"
        variant="panel"
        message="Loading channels"
      />
    );
  if (data.error)
    return <StateMessage state="error" variant="panel" message={data.error} />;

  if (!data.selectedProvider) {
    return (
      <SelectProvider
        providers={data.providers}
        onSelect={data.setSelectedProvider}
      />
    );
  }

  return (
    <ChannelForm
      mode="new"
      provider={data.selectedProvider}
      connections={data.connections}
      models={data.models}
      onBack={() => data.setSelectedProvider(null)}
    />
  );
}

export function EditChannelPage() {
  const navigate = useNavigate();
  const location = useLocation();
  const data = useChannelFormData("edit");
  const initialNotice = Boolean(
    (location.state as { created?: boolean } | null)?.created,
  )
    ? "Channel saved."
    : null;

  if (data.loading)
    return (
      <StateMessage state="loading" variant="panel" message="Loading channel" />
    );
  if (data.error || !data.channel || !data.selectedProvider) {
    return (
      <StateMessage
        state="error"
        variant="panel"
        message={data.error ?? "Channel not found"}
      />
    );
  }

  return (
    <ChannelForm
      mode="edit"
      provider={data.selectedProvider}
      channel={data.channel}
      connections={data.connections}
      models={data.models}
      initialNotice={initialNotice}
      onBack={() => navigate("/channels")}
    />
  );
}
