import { useEffect, useRef, useState, type ReactNode } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { Cloud, Plus, Unplug } from "lucide-react";

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
import { notify } from "@/components/ui/global-toast";
import { ItemCard, ItemGrid } from "@/components/ui/item-grid";
import { RowActions } from "@/components/ui/row-actions";
import { StateMessage } from "@/components/ui/state-message";
import { Timestamp } from "@/components/ui/timestamp";
import { Tooltip } from "@/components/ui/tooltip";
import { useDeploymentMode } from "@/config/product-provider";
import { WorkspaceDependencyImpactSummary } from "@/components/collections/DependencyImpactSummary";
import { SourceDetail } from "@/components/data/source-detail";
import { useWorkspaceChange } from "@/realtime/workspace-events";

export default function ConnectionsPage({
  view = "connections",
}: {
  view?: "connections" | "sources";
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
  const [selectedConnectionId, setSelectedConnectionId] = useState<
    number | null
  >(null);
  const [loading, setLoading] = useState(true);
  const [working, setWorking] = useState<Set<number>>(new Set());
  const [schemaLoading, setSchemaLoading] = useState<Set<number>>(new Set());
  const [error, setError] = useState<string | null>(null);
  const loadVersion = useRef(0);

  async function load(background = false) {
    const version = ++loadVersion.current;
    setError(null);
    if (!background) setLoading(true);
    try {
      if (view === "connections") {
        const [nextOauth, nextPostgres] = await Promise.all([
          api.googleOAuth.status(),
          managed ? Promise.resolve(null) : api.health.postgres(),
        ]);
        if (version !== loadVersion.current) return;
        setOauth(nextOauth);
        setPostgres(nextPostgres);
      } else {
        const [nextConnections, nextOauth, loader] = await Promise.all([
          api.connections.list(),
          api.googleOAuth.status(),
          api.health.data(),
        ]);
        if (version !== loadVersion.current) return;
        setConnections(nextConnections);
        setOauth(nextOauth);
        setDiagnostics(
          Object.fromEntries(loader.connections.map((item) => [item.id, item])),
        );
      }
      if (
        version === loadVersion.current &&
        searchParams.get("google") === "error"
      ) {
        setError("Google authorization was canceled or denied.");
      }
    } catch (err: any) {
      if (version === loadVersion.current) setError(err.message);
    } finally {
      if (version === loadVersion.current) setLoading(false);
    }
  }

  useEffect(() => {
    if (deploymentMode === null) return;
    if (searchParams.get("google") === "connected") {
      notify.success("Google account connected.");
    }
    void load();
  }, [view, deploymentMode]);

  useWorkspaceChange(["connections", "google_oauth"], () => {
    if (deploymentMode !== null) void load(true);
  });

  async function connectGoogle() {
    setError(null);
    try {
      const { authorization_url } = await api.googleOAuth.start();
      window.location.assign(authorization_url);
    } catch (err: any) {
      setError(err.message);
      notify.error(err.message);
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
      notify.success(
        managed
          ? "Google disconnected. Previously synchronized data remains available."
          : result.note,
      );
      await load();
    } catch (err: any) {
      setError(err.message);
      notify.error(err.message);
    }
  }

  async function syncConnection(connection: Connection) {
    setError(null);
    setWorking((current) => new Set(current).add(connection.id));
    try {
      const result = await api.connections.sync(connection.id);
      notify.success(
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
      notify.error(err.message);
      await load();
    } finally {
      setWorking((current) => {
        const next = new Set(current);
        next.delete(connection.id);
        return next;
      });
    }
  }

  async function showSource(connection: Connection) {
    setSelectedConnectionId(connection.id);
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

  async function confirmDelete(connection: Connection) {
    setError(null);
    try {
      const impact = await api.connections.deletionImpact(connection.id);
      openModal({
        title: "Remove source?",
        body: (
          <div className="space-y-3">
            <p>
              {managed
                ? `This removes the sync definition for ${connection.name}. Its previously synchronized data is retained.`
                : `This removes the sync definition for ${connection.name}. Its last PostgreSQL snapshot is retained.`}
            </p>
            <WorkspaceDependencyImpactSummary impact={impact} />
          </div>
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
    } catch (err: any) {
      setError(err.message);
    }
  }

  async function deleteConnection(id: number) {
    try {
      await api.connections.delete(id);
      setConnections((current) => current.filter((item) => item.id !== id));
      if (selectedConnectionId === id) setSelectedConnectionId(null);
      notify.success(
        managed
          ? "Source removed. Its previously synchronized data was retained."
          : "Source removed. Its PostgreSQL snapshot was retained.",
      );
    } catch (err: any) {
      setError(err.message);
      notify.error(err.message);
    }
  }

  const postgresConnected = postgres?.postgres === "connected";
  const googleSyncReady = Boolean(oauth?.connected && oauth?.scope_ready);
  const pickerReady = Boolean(oauth?.picker_ready);
  const selectedConnection = connections.find(
    (connection) => connection.id === selectedConnectionId,
  );
  const selectedDiagnostic = selectedConnection
    ? diagnostics[selectedConnection.id]
    : undefined;
  const selectedSchema = selectedConnection
    ? schemas[selectedConnection.id]
    : undefined;

  return (
    <div className="space-y-7">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-2xl font-semibold">
          {view === "sources" ? "Sources" : "Connections"}
        </h1>
        {view === "sources" &&
          (pickerReady ? (
            <Tooltip content="New source">
              <Button
                to="/data/new"
                variant="primary"
                size="icon"
                aria-label="New source"
              >
                <Plus />
              </Button>
            </Tooltip>
          ) : (
            <Tooltip content="New source">
              <Button
                type="button"
                variant="primary"
                size="icon"
                aria-label="New source"
                disabled
              >
                <Plus />
              </Button>
            </Tooltip>
          ))}
      </div>

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

      {!loading && view === "sources" && (
        <section>
          {selectedConnection ? (
            <SourceDetail
              name={selectedConnection.name}
              status={selectedConnection.status}
              managed={managed}
              destinationName={selectedConnection.destination.name}
              destinationSchema={selectedConnection.destination_schema}
              lastSyncedAt={selectedConnection.last_synced_at}
              loading={schemaLoading.has(selectedConnection.id)}
              tables={
                selectedSchema
                  ? Object.entries(selectedSchema.tables).map(
                      ([tableName, table]) => ({
                        key: tableName,
                        name: tableName,
                        columnCount: table.columns.length,
                        description: table.description,
                        columns: table.columns,
                      }),
                    )
                  : undefined
              }
              notices={
                selectedConnection.last_sync_error ||
                (selectedDiagnostic?.warnings ?? []).length > 0 ? (
                  <div className="space-y-2 text-sm">
                    {selectedConnection.last_sync_error && (
                      <p className="text-destructive">
                        {selectedConnection.last_sync_error}
                      </p>
                    )}
                    {(selectedDiagnostic?.warnings ?? []).map((warning) => (
                      <p
                        key={warning}
                        className="text-amber-700 dark:text-amber-300"
                      >
                        {warning}
                      </p>
                    ))}
                  </div>
                ) : undefined
              }
              onClose={() => setSelectedConnectionId(null)}
            />
          ) : connections.length === 0 ? (
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
                const isSyncing = working.has(connection.id);

                return (
                  <ItemCard
                    key={connection.id}
                    title={
                      <button
                        type="button"
                        className="cursor-pointer text-left hover:text-primary hover:underline"
                        onClick={() => void showSource(connection)}
                      >
                        {connection.name}
                      </button>
                    }
                    pills={
                      connection.status === "failed" ? (
                        <Badge variant="destructive">Disconnected</Badge>
                      ) : undefined
                    }
                    footer={
                      <RowActions
                        actions={[
                          {
                            key: "view",
                            title: "View source",
                            ariaLabel: "View source",
                            loading: schemaLoading.has(connection.id),
                            onClick: () => void showSource(connection),
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
                            onClick: () => void confirmDelete(connection),
                          },
                        ]}
                      />
                    }
                  >
                    <div className="space-y-3">
                      <div className="space-y-2 text-sm">
                        {!managed && (
                          <>
                            <Metric
                              label="Destination"
                              value={connection.destination.name}
                            />
                            <Metric
                              label="Schema"
                              value={connection.destination_schema}
                            />
                          </>
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
