import { useEffect, useState, type ReactNode } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { Cloud, Database, Plus, RefreshCw, Rows3, Unplug } from "lucide-react";

import {
  api,
  type Connection,
  type ConnectionMetadata,
  type ConnectionRetryResult,
  type GoogleOAuthStatus,
  type PostgresHealth,
} from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { useModal } from "@/components/ui/global-modal";
import { ItemCard, ItemGrid } from "@/components/ui/item-grid";
import { RowActions } from "@/components/ui/row-actions";
import { StateMessage } from "@/components/ui/state-message";
import { Timestamp } from "@/components/ui/timestamp";
import { Tooltip } from "@/components/ui/tooltip";
import { DataTabs } from "@/components/data/data-tabs";
import { useDeploymentMode } from "@/config/product-provider";

export default function ConnectionsPage({
  view = "connections",
}: {
  view?: "connections" | "pipes";
}) {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const { openModal } = useModal();
  const deploymentMode = useDeploymentMode();
  const managed = deploymentMode === "managed";
  const [connections, setConnections] = useState<Connection[]>([]);
  const [oauth, setOauth] = useState<GoogleOAuthStatus | null>(null);
  const [postgres, setPostgres] = useState<PostgresHealth | null>(null);
  const [diagnostics, setDiagnostics] = useState<
    Record<number, ConnectionRetryResult>
  >({});
  const [schemas, setSchemas] = useState<Record<number, ConnectionMetadata>>(
    {},
  );
  const [expandedSchema, setExpandedSchema] = useState<number | null>(null);
  const [loading, setLoading] = useState(true);
  const [working, setWorking] = useState<Set<number>>(new Set());
  const [schemaLoading, setSchemaLoading] = useState<Set<number>>(new Set());
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(() =>
    searchParams.get("google") === "connected"
      ? "Google account connected."
      : null,
  );

  async function load() {
    setError(null);
    setLoading(true);
    try {
      if (view === "connections") {
        const nextOauth = await api.googleOAuth.status();
        setOauth(nextOauth);
        if (!managed) {
          setPostgres(await api.health.postgres());
        } else {
          setPostgres(null);
        }
      } else {
        const [nextConnections, nextOauth, loader] = await Promise.all([
          api.connections.list(),
          api.googleOAuth.status(),
          api.health.data(),
        ]);
        setConnections(nextConnections);
        setOauth(nextOauth);
        setDiagnostics(
          Object.fromEntries(loader.connections.map((item) => [item.id, item])),
        );
      }
      if (searchParams.get("google") === "error") {
        setError("Google authorization was canceled or denied.");
      }
    } catch (err: any) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    if (deploymentMode === null) return;
    void load();
  }, [view, deploymentMode]);

  async function connectGoogle() {
    setError(null);
    try {
      const { authorization_url } = await api.googleOAuth.start();
      window.location.assign(authorization_url);
    } catch (err: any) {
      setError(err.message);
    }
  }

  function confirmDisconnectGoogle() {
    openModal({
      title: "Disconnect Google?",
      body: (
        <p>
          {managed
            ? "Scheduled syncs will stop. Previously synchronized data remains available."
            : "Scheduled loads will stop. Existing PostgreSQL snapshots remain queryable through Cube."}
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
              void disconnectGoogle();
            }}
          >
            Disconnect
          </Button>
        </>
      ),
    });
  }

  async function disconnectGoogle() {
    try {
      const result = await api.googleOAuth.disconnect();
      setNotice(
        managed
          ? "Google disconnected. Previously synchronized data remains available."
          : result.note,
      );
      await load();
    } catch (err: any) {
      setError(err.message);
    }
  }

  async function syncConnection(connection: Connection) {
    setError(null);
    setNotice(null);
    setWorking((current) => new Set(current).add(connection.id));
    try {
      const result = await api.connections.sync(connection.id);
      setNotice(
        `${connection.name} synchronized ${result.row_count} rows across ${result.table_count} tables.`,
      );
      setSchemas((current) => {
        const next = { ...current };
        delete next[connection.id];
        return next;
      });
      await load();
    } catch (err: any) {
      setError(err.message);
      await load();
    } finally {
      setWorking((current) => {
        const next = new Set(current);
        next.delete(connection.id);
        return next;
      });
    }
  }

  async function toggleSchema(connection: Connection) {
    if (expandedSchema === connection.id) {
      setExpandedSchema(null);
      return;
    }

    setExpandedSchema(connection.id);
    if (schemas[connection.id]) return;

    setSchemaLoading((current) => new Set(current).add(connection.id));
    try {
      const metadata = await api.connections.metadata(connection.id);
      setSchemas((current) => ({ ...current, [connection.id]: metadata }));
    } catch (err: any) {
      setError(err.message);
    } finally {
      setSchemaLoading((current) => {
        const next = new Set(current);
        next.delete(connection.id);
        return next;
      });
    }
  }

  function confirmDelete(connection: Connection) {
    openModal({
      title: "Remove source?",
      body: (
        <p>
          {managed
            ? `This removes the sync definition for ${connection.name}. Its previously synchronized data is retained.`
            : `This removes the sync definition for ${connection.name}. Its last PostgreSQL snapshot is retained.`}
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
              void deleteConnection(connection.id);
            }}
          >
            Remove source
          </Button>
        </>
      ),
    });
  }

  async function deleteConnection(id: number) {
    try {
      await api.connections.delete(id);
      setConnections((current) => current.filter((item) => item.id !== id));
      setNotice(
        managed
          ? "Source removed. Its previously synchronized data was retained."
          : "Source removed. Its PostgreSQL snapshot was retained.",
      );
    } catch (err: any) {
      setError(err.message);
    }
  }

  const postgresConnected = postgres?.postgres === "connected";
  const googleSyncReady = Boolean(oauth?.connected && oauth?.scope_ready);
  const pickerReady = Boolean(oauth?.picker_ready);

  return (
    <div className="space-y-7">
      <DataTabs
        action={
          view === "pipes" ? (
            pickerReady ? (
              <Tooltip content="New pipe">
                <Button
                  to="/data/new"
                  variant="primary"
                  size="icon"
                  aria-label="New pipe"
                >
                  <Plus />
                </Button>
              </Tooltip>
            ) : (
              <Tooltip content="New pipe">
                <Button
                  type="button"
                  variant="primary"
                  size="icon"
                  aria-label="New pipe"
                  disabled
                >
                  <Plus />
                </Button>
              </Tooltip>
            )
          ) : undefined
        }
      />

      {loading && (
        <StateMessage state="loading" variant="banner" message="Loading data" />
      )}
      {error && (
        <StateMessage
          state="error"
          variant="banner"
          message={error}
          onClose={() => setError(null)}
        />
      )}
      {notice && (
        <StateMessage
          state="success"
          variant="banner"
          message={notice}
          onClose={() => setNotice(null)}
        />
      )}

      {!loading && view === "connections" && (
        <section>
          <ItemGrid>
            <ItemCard
              title="Google Drive"
              pills={
                <Badge
                  variant={
                    oauth?.requires_reconnect
                      ? "warning"
                      : oauth?.connected
                        ? "success"
                        : "warning"
                  }
                >
                  {oauth?.requires_reconnect
                    ? "Reconnect required"
                    : oauth?.connected
                      ? "Connected"
                      : "Not connected"}
                </Badge>
              }
              footer={
                oauth?.requires_reconnect ? (
                  <>
                    <Button
                      type="button"
                      variant="primary"
                      size="sm"
                      disabled={!oauth.configured}
                      onClick={() => void connectGoogle()}
                    >
                      <Cloud className="size-3.5" /> Reconnect Google
                    </Button>
                    <Button
                      type="button"
                      variant="outline"
                      size="sm"
                      onClick={confirmDisconnectGoogle}
                    >
                      <Unplug className="size-3.5" /> Disconnect
                    </Button>
                  </>
                ) : oauth?.connected ? (
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    onClick={confirmDisconnectGoogle}
                  >
                    <Unplug className="size-3.5" /> Disconnect
                  </Button>
                ) : (
                  <Button
                    type="button"
                    variant="primary"
                    size="sm"
                    disabled={!oauth?.configured}
                    onClick={() => void connectGoogle()}
                  >
                    <Cloud className="size-3.5" /> Connect Google
                  </Button>
                )
              }
            >
              <div className="space-y-2">
                <p>
                  {managed
                    ? "Google Drive account used to select and sync source files"
                    : "File-specific Google OAuth source"}
                </p>
                {oauth?.email && (
                  <p className="text-foreground">{oauth.email}</p>
                )}
                {!oauth?.configured && (
                  <p className="text-amber-700 dark:text-amber-300">
                    {managed ? (
                      "Google Drive connections are currently unavailable. Please contact support."
                    ) : (
                      <>
                        Configure GOOGLE_OAUTH_CLIENT_ID and
                        GOOGLE_OAUTH_CLIENT_SECRET. Redirect URI:{" "}
                        {oauth?.redirect_uri}
                      </>
                    )}
                  </p>
                )}
                {oauth?.requires_reconnect && (
                  <p className="text-amber-700 dark:text-amber-300">
                    Reconnect once to replace the broad Drive scope with access
                    only to files selected through Google Picker.
                  </p>
                )}
                {oauth?.connected && !oauth.picker_configured && (
                  <p className="text-amber-700 dark:text-amber-300">
                    {managed
                      ? "Google Drive file selection is currently unavailable. Please contact support."
                      : "Configure GOOGLE_PICKER_API_KEY and GOOGLE_PICKER_APP_ID to enable Drive file selection."}
                  </p>
                )}
              </div>
            </ItemCard>

            {!managed && (
              <ItemCard
                title="Managed PostgreSQL destination"
                pills={
                  <>
                    <Badge
                      variant={postgresConnected ? "success" : "destructive"}
                    >
                      {postgresConnected ? "Connected" : "Unavailable"}
                    </Badge>
                  </>
                }
              >
                <div className="space-y-2">
                  {postgres?.destination && (
                    <p className="font-mono text-foreground">
                      {postgres.destination.host}:{postgres.destination.port}/
                      {postgres.destination.database}
                    </p>
                  )}
                  {postgres?.version && <p>PostgreSQL {postgres.version}</p>}
                </div>
              </ItemCard>
            )}
          </ItemGrid>
        </section>
      )}

      {!loading && view === "pipes" && (
        <section>
          {connections.length === 0 ? (
            <StateMessage
              state="empty"
              variant="panel"
              title="No Google Drive sources"
              message={
                pickerReady
                  ? "Add a Sheet, CSV, Excel, or Parquet file to create its first durable snapshot."
                  : managed
                    ? "Google Drive file selection is currently unavailable. Reconnect Google from Connections or contact support."
                    : "Finish Google Picker setup before adding a Drive source."
              }
              action={
                pickerReady ? (
                  <Button to="/data/new" variant="primary">
                    <Plus className="size-3.5" /> Add source
                  </Button>
                ) : undefined
              }
            />
          ) : (
            <ItemGrid>
              {connections.map((connection) => {
                const diagnostic = diagnostics[connection.id];
                const schema = schemas[connection.id];
                const isOpen = expandedSchema === connection.id;
                const isSyncing = working.has(connection.id);

                return (
                  <ItemCard
                    key={connection.id}
                    title={connection.name}
                    pills={
                      <>
                        <Badge variant={statusVariant(connection.status)}>
                          {connection.status}
                        </Badge>
                      </>
                    }
                    footer={
                      <RowActions
                        actions={[
                          {
                            key: "view",
                            title: isOpen ? "Hide schema" : "View schema",
                            ariaLabel: isOpen ? "Hide schema" : "View schema",
                            loading: schemaLoading.has(connection.id),
                            onClick: () => void toggleSchema(connection),
                          },
                          {
                            key: "sync",
                            title: "Sync now",
                            ariaLabel: "Sync Drive file now",
                            loading: isSyncing,
                            disabled: isSyncing || !googleSyncReady,
                            onClick: () => void syncConnection(connection),
                          },
                          {
                            key: "edit",
                            title: "Edit YAML and source",
                            ariaLabel: "Edit source",
                            onClick: () =>
                              navigate(`/data/${connection.id}/edit`),
                          },
                          {
                            key: "delete",
                            title: "Remove source",
                            ariaLabel: "Remove source",
                            onClick: () => confirmDelete(connection),
                          },
                        ]}
                      />
                    }
                  >
                    <div className="space-y-3">
                      <div className="space-y-2 text-sm">
                        <Metric
                          label="Destination"
                          value={
                            managed
                              ? "Managed destination"
                              : connection.destination.name
                          }
                        />
                        {!managed && (
                          <Metric
                            label="Schema"
                            value={connection.destination_schema}
                          />
                        )}
                        <Metric
                          label="Tables"
                          value={String(diagnostic?.table_count ?? "-")}
                        />
                        <Metric
                          label="Columns"
                          value={String(diagnostic?.column_count ?? "-")}
                        />
                        <Metric
                          label="Last sync"
                          value={
                            connection.last_synced_at ? (
                              <Timestamp value={connection.last_synced_at} />
                            ) : (
                              "Never"
                            )
                          }
                        />
                      </div>

                      {connection.last_sync_error && (
                        <p className="text-destructive">
                          {connection.last_sync_error}
                        </p>
                      )}

                      {(diagnostic?.warnings ?? []).map((warning) => (
                        <p
                          key={warning}
                          className="text-amber-700 dark:text-amber-300"
                        >
                          {warning}
                        </p>
                      ))}

                      {isOpen && (
                        <SchemaView
                          metadata={schema}
                          loading={schemaLoading.has(connection.id)}
                        />
                      )}
                    </div>
                  </ItemCard>
                );
              })}
            </ItemGrid>
          )}
        </section>
      )}
    </div>
  );
}

function Metric({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div className="flex items-baseline gap-1.5">
      <span>{label}</span>
      <span className="font-medium text-foreground">{value}</span>
    </div>
  );
}

function SchemaView({
  metadata,
  loading,
}: {
  metadata?: ConnectionMetadata;
  loading: boolean;
}) {
  if (loading) {
    return (
      <div className="flex items-center gap-2 rounded-lg border p-3">
        <RefreshCw className="size-3.5 animate-spin" /> Loading schema
      </div>
    );
  }

  if (!metadata) return null;
  const tables = Object.entries(metadata.tables);

  return (
    <div className="space-y-3 border-t pt-3">
      <div className="flex items-center gap-2 text-sm font-medium">
        <Rows3 className="size-4" /> Synchronized schema
      </div>
      <div className="space-y-3">
        {tables.map(([name, table]) => (
          <div key={name} className="w-full overflow-hidden rounded-lg border">
            <div className="flex items-center gap-2 border-b bg-muted/35 px-3 py-2">
              <Database className="size-3.5" />
              <span className="font-mono text-sm font-medium">{name}</span>
              <Badge variant="outline" className="ml-auto">
                {table.columns.length} columns
              </Badge>
            </div>
            {table.description && (
              <p className="border-b px-3 py-2 text-xs text-muted-foreground">
                {table.description}
              </p>
            )}
            <div className="max-h-52 overflow-auto">
              {table.columns.map((column) => (
                <div
                  key={column.name}
                  className="flex items-start justify-between gap-3 border-b px-3 py-2 text-xs last:border-b-0"
                >
                  <div>
                    <p className="font-mono text-foreground">{column.name}</p>
                    {column.description && (
                      <p className="mt-0.5 text-muted-foreground">
                        {column.description}
                      </p>
                    )}
                  </div>
                  <span className="shrink-0 font-mono text-muted-foreground">
                    {column.type}
                  </span>
                </div>
              ))}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function statusVariant(status: Connection["status"]) {
  if (status === "active") return "success" as const;
  if (status === "failed") return "destructive" as const;
  return "warning" as const;
}
