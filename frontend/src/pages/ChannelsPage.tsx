import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Check, Copy, Plus } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { useModal } from "@/components/ui/global-modal";
import { ItemCard, ItemGrid } from "@/components/ui/item-grid";
import { RowActions } from "@/components/ui/row-actions";
import { StateMessage } from "@/components/ui/state-message";
import { StatusBadge } from "@/components/ui/status-badge";
import { Timestamp } from "@/components/ui/timestamp";
import {
  channelWebhookUrl,
  defaultPublicApiUrl,
  readStoredPublicApiUrl,
} from "@/lib/channels";
import {
  api,
  type Connection,
  type MessagingConfig,
  type MessagingProvider,
  type ModelConfig,
} from "@/lib/api";

export default function ChannelsPage() {
  const navigate = useNavigate();
  const { openModal } = useModal();
  const [configs, setConfigs] = useState<MessagingConfig[]>([]);
  const [providers, setProviders] = useState<MessagingProvider[]>([]);
  const [connections, setConnections] = useState<Connection[]>([]);
  const [models, setModels] = useState<ModelConfig[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [copiedConfigId, setCopiedConfigId] = useState<number | null>(null);
  const [publicApiUrl, setPublicApiUrl] = useState(defaultPublicApiUrl);

  async function load() {
    setError(null);
    try {
      const [
        providerItems,
        configItems,
        connectionItems,
        modelItems,
        runtimeConfig,
      ] = await Promise.all([
        api.messaging.providers.list(),
        api.messaging.configs.list(),
        api.connections.list(),
        api.models.list(),
        api.config.get().catch(() => ({ public_api_url: "" })),
      ]);
      setProviders(providerItems);
      setConfigs(configItems);
      setConnections(connectionItems);
      setModels(modelItems);
      if (!readStoredPublicApiUrl() && runtimeConfig.public_api_url) {
        setPublicApiUrl(runtimeConfig.public_api_url);
      }
    } catch (err: any) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void load();
  }, []);

  const providerByKey = useMemo(
    () => new Map(providers.map((provider) => [provider.key, provider])),
    [providers],
  );
  const connectionById = useMemo(
    () => new Map(connections.map((connection) => [connection.id, connection])),
    [connections],
  );
  const modelById = useMemo(
    () => new Map(models.map((model) => [model.id, model])),
    [models],
  );

  async function deleteChannel(channel: MessagingConfig) {
    setError(null);
    setNotice(null);
    try {
      await api.messaging.configs.delete(channel.id);
      setConfigs((prev) => prev.filter((item) => item.id !== channel.id));
      setNotice("Channel deleted");
    } catch (err: any) {
      setError(err.message);
    }
  }

  function confirmDelete(channel: MessagingConfig) {
    openModal({
      title: "Delete channel?",
      body: (
        <p>
          This deletes{" "}
          <span className="font-medium text-foreground">{channel.name}</span>{" "}
          and stops inbound messages for its webhook config.
        </p>
      ),
      actions: ({ close }) => (
        <>
          <Button type="button" variant="outline" onClick={close}>
            Cancel
          </Button>
          <Button
            type="button"
            variant="destructive"
            onClick={() => {
              close();
              void deleteChannel(channel);
            }}
          >
            Delete channel
          </Button>
        </>
      ),
    });
  }

  async function copyWebhook(channel: MessagingConfig) {
    const url = channelWebhookUrl(channel.provider, channel.id, publicApiUrl);
    await navigator.clipboard.writeText(url);
    setCopiedConfigId(channel.id);
    window.setTimeout(() => setCopiedConfigId(null), 1500);
  }

  return (
    <div className="space-y-6">
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0">
          <h1 className="text-2xl font-semibold">Channels</h1>
          {providers.length > 0 && (
            <div className="mt-2 flex flex-wrap items-center gap-1.5">
              {providers.map((provider) => (
                <Badge key={provider.key} variant="secondary">
                  {provider.name}
                </Badge>
              ))}
            </div>
          )}
        </div>
        <Button to="/channels/new" variant="primary" aria-label="Add channel">
          <Plus className="size-3" />
        </Button>
      </div>

      {loading && (
        <StateMessage
          state="loading"
          variant="banner"
          message="Loading channels"
        />
      )}
      {error && <StateMessage state="error" variant="banner" message={error} />}
      {notice && (
        <StateMessage state="success" variant="banner" message={notice} />
      )}

      {!loading && !error && configs.length === 0 && (
        <StateMessage
          state="empty"
          variant="panel"
          title="No channels configured"
          message="Mounted channel providers will appear when you add a channel config."
          action={
            <Button to="/channels/new" variant="primary">
              <Plus className="size-3" /> Add channel
            </Button>
          }
        />
      )}

      {!loading && !error && configs.length > 0 && (
        <ItemGrid>
          {configs.map((channel) => {
            const provider = providerByKey.get(channel.provider);
            const model = modelById.get(channel.model_config_id);
            const selectedConnections = channel.connection_ids
              .map((id) => connectionById.get(id))
              .filter(Boolean) as Connection[];
            const webhookUrl = channelWebhookUrl(
              channel.provider,
              channel.id,
              publicApiUrl,
            );
            const copied = copiedConfigId === channel.id;

            return (
              <ItemCard
                key={channel.id}
                title={channel.name}
                pills={
                  <>
                    <StatusBadge text="Active" color="green" />
                    <Badge variant="secondary">
                      {provider?.name ?? channel.provider}
                    </Badge>
                    {provider?.delivery_modes.map((mode) => (
                      <Badge
                        key={mode}
                        variant="outline"
                        className="capitalize"
                      >
                        {mode}
                      </Badge>
                    ))}
                  </>
                }
                footer={
                  <RowActions
                    actions={[
                      {
                        key: "edit",
                        title: "Edit",
                        ariaLabel: "Edit channel",
                        onClick: () => navigate(`/channels/${channel.id}/edit`),
                      },
                      {
                        key: "delete",
                        title: "Delete",
                        ariaLabel: "Delete channel",
                        onClick: () => confirmDelete(channel),
                      },
                    ]}
                  />
                }
              >
                <div className="space-y-3">
                  <div className="space-y-1.5">
                    <p>
                      <span className="text-foreground">Model:</span>{" "}
                      {model?.name ?? `Model ${channel.model_config_id}`}
                    </p>
                    <p>
                      <span className="text-foreground">Connections:</span>{" "}
                      {selectedConnections.length > 0
                        ? selectedConnections
                            .map((connection) => connection.name)
                            .join(", ")
                        : channel.connection_ids
                            .map((connectionId) => `#${connectionId}`)
                            .join(", ")}
                    </p>
                    <p>
                      Updated <Timestamp value={channel.updated_at} />
                    </p>
                  </div>

                  <div className="flex min-w-0 items-center gap-2 rounded-lg border bg-muted/30 px-2 py-1.5">
                    <code className="min-w-0 flex-1 truncate text-xs text-foreground">
                      {webhookUrl}
                    </code>
                    <Button
                      type="button"
                      variant="ghost"
                      size="icon-sm"
                      title={copied ? "Copied" : "Copy webhook endpoint"}
                      aria-label={copied ? "Copied" : "Copy webhook endpoint"}
                      onClick={() => void copyWebhook(channel)}
                    >
                      {copied ? (
                        <Check className="size-3.5" />
                      ) : (
                        <Copy className="size-3.5" />
                      )}
                    </Button>
                  </div>
                </div>
              </ItemCard>
            );
          })}
        </ItemGrid>
      )}
    </div>
  );
}
