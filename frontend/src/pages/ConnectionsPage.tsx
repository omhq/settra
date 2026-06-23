import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Plus } from "lucide-react";
import { api, type Connection, type ConnectionRetryResult } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { useModal } from "@/components/ui/global-modal";
import { ItemCard, ItemGrid } from "@/components/ui/item-grid";
import { RowActions } from "@/components/ui/row-actions";
import { StatusBadge } from "@/components/ui/status-badge";
import { StateMessage } from "@/components/ui/state-message";
import { Timestamp } from "@/components/ui/timestamp";

export default function ConnectionsPage() {
  const navigate = useNavigate();
  const { openModal } = useModal();
  const [connections, setConnections] = useState<Connection[]>([]);
  const [diagnosticsById, setDiagnosticsById] = useState<
    Record<number, ConnectionRetryResult>
  >({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [warning, setWarning] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [retrying, setRetrying] = useState<Set<number>>(new Set());
  const [syncing, setSyncing] = useState<Set<number>>(new Set());

  async function load() {
    setError(null);
    setWarning(null);

    try {
      const [nextConnections, diagnostics] = await Promise.all([
        api.connections.list(),
        loadConnectionDiagnostics(),
      ]);

      setConnections(nextConnections);
      if (diagnostics) setDiagnosticsById(indexDiagnostics(diagnostics));
    } catch (e: any) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }

  async function loadConnectionDiagnostics() {
    try {
      const summary = await api.health.fdw();
      return summary.connections;
    } catch (e: any) {
      setWarning(`Connection diagnostics unavailable. ${e.message}`);
      return null;
    }
  }

  useEffect(() => {
    load();
  }, []);

  async function deleteConnection(id: number) {
    await api.connections.delete(id);
    setConnections((prev) => prev.filter((c) => c.id !== id));
    setDiagnosticsById((prev) => {
      const next = { ...prev };
      delete next[id];
      return next;
    });
  }

  function confirmDelete(connection: Connection) {
    openModal({
      title: "Delete connection?",
      body: (
        <p>
          This removes{" "}
          <span className="font-medium text-foreground">{connection.name}</span>{" "}
          and its saved Steampipe configuration.
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
            Delete connection
          </Button>
        </>
      ),
    });
  }

  async function handleRetry(id: number) {
    setError(null);
    setWarning(null);
    setNotice(null);
    setRetrying((prev) => new Set(prev).add(id));
    try {
      const result = await api.connections.retry(id);
      setConnections((prev) =>
        prev.map((c) => (c.id === id ? { ...c, status: result.status } : c)),
      );
      setDiagnosticsById((prev) => ({ ...prev, [id]: result }));
      const connection = connections.find((c) => c.id === id);
      const name = connection?.name ?? "Connection";
      const diagnostics = retryDiagnostics(result);

      if (result.status === "active") {
        if (diagnostics.length) {
          setWarning(`${name} credentials are valid. ${diagnostics.join(" ")}`);
        } else {
          setNotice(`${name} is active.`);
        }
      } else {
        setError(
          diagnostics.length
            ? `${name} retry failed. ${diagnostics.join(" ")}`
            : `${name} retry failed.`,
        );
      }
    } catch (e: any) {
      setError(e.message);
    } finally {
      setRetrying((prev) => {
        const next = new Set(prev);
        next.delete(id);
        return next;
      });
    }
  }

  async function handleSyncCubeModel(connection: Connection) {
    setError(null);
    setWarning(null);
    setNotice(null);
    setSyncing((prev) => new Set(prev).add(connection.id));
    try {
      const result = await api.semantics.syncModel();
      const diagnostics = await loadConnectionDiagnostics();

      if (diagnostics) setDiagnosticsById(indexDiagnostics(diagnostics));

      setNotice(
        `Cube model refreshed for ${connection.name}. ${result.files.length} files available.`,
      );
    } catch (e: any) {
      setError(e.message);
    } finally {
      setSyncing((prev) => {
        const next = new Set(prev);
        next.delete(connection.id);
        return next;
      });
    }
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold">Connections</h1>
        </div>
        <Button to="/connections/new" variant="primary">
          <Plus className="size-3" />
        </Button>
      </div>

      {loading && (
        <StateMessage
          state="loading"
          variant="banner"
          message="Loading connections"
        />
      )}
      {error && <StateMessage state="error" variant="banner" message={error} />}
      {warning && (
        <StateMessage state="warning" variant="banner" message={warning} />
      )}
      {notice && (
        <StateMessage state="success" variant="banner" message={notice} />
      )}

      {!loading && !error && connections.length === 0 && (
        <StateMessage
          state="empty"
          variant="panel"
          title="No connections yet"
          message="Add a connection before generating Cube model files."
          action={
            <Button to="/connections/new" variant="primary">
              <Plus className="size-3" />
              Add connection
            </Button>
          }
        />
      )}

      {!loading && connections.length > 0 && (
        <ItemGrid>
          {connections.map((c) => {
            const diagnostics = diagnosticsById[c.id];
            const fdwBadge = diagnostics ? fdwBadgeFor(diagnostics) : null;

            return (
              <ItemCard
                key={c.id}
                title={c.name}
                pills={
                  <>
                    <StatusBadge
                      text={
                        c.status === "active" ? "Saved active" : "Saved failed"
                      }
                      color={c.status === "active" ? "green" : "red"}
                    />
                    {fdwBadge && (
                      <StatusBadge
                        text={fdwBadge.text}
                        color={fdwBadge.color}
                      />
                    )}
                    <Badge variant="secondary" className="capitalize">
                      {c.plugin}
                    </Badge>
                  </>
                }
                footer={
                  <RowActions
                    actions={[
                      {
                        key: "sync",
                        title: "Refresh Cube model",
                        ariaLabel: "Refresh Cube model",
                        loading: syncing.has(c.id),
                        disabled: syncing.has(c.id),
                        onClick: () => handleSyncCubeModel(c),
                      },
                      {
                        key: "retry",
                        title: "Retry",
                        ariaLabel: "Retry connection",
                        loading: retrying.has(c.id),
                        disabled: retrying.has(c.id),
                        onClick: () => handleRetry(c.id),
                      },
                      {
                        key: "edit",
                        title: "Edit",
                        ariaLabel: "Edit connection",
                        onClick: () => navigate(`/connections/${c.id}/edit`),
                      },
                      {
                        key: "delete",
                        title: "Delete",
                        ariaLabel: "Delete connection",
                        onClick: () => confirmDelete(c),
                      },
                    ]}
                  />
                }
              >
                <div className="space-y-2">
                  <p>
                    Schema{" "}
                    <span className="font-mono text-foreground">
                      {diagnostics?.slug ?? c.slug}
                    </span>
                  </p>
                  <p>
                    Created <Timestamp value={c.created_at} />
                  </p>
                  <p>
                    FDW exposed {formatCount(diagnostics?.fdw_table_count)}{" "}
                    tables | {formatCount(diagnostics?.fdw_column_count)} raw
                    columns
                  </p>
                  {diagnostics?.fdw_schema_mode && (
                    <p>Schema mode {diagnostics.fdw_schema_mode}</p>
                  )}
                  {diagnostics?.fdw_plugin_instance && (
                    <p className="break-all">
                      Plugin instance {diagnostics.fdw_plugin_instance}
                    </p>
                  )}
                  {diagnostics?.warnings && diagnostics.warnings.length > 0 && (
                    <div className="space-y-1">
                      {diagnostics.warnings.slice(0, 3).map((item, index) => (
                        <p key={`${c.id}-warning-${index}`}>{item}</p>
                      ))}
                    </div>
                  )}
                  {diagnostics?.fdw_error &&
                    !(diagnostics.warnings ?? []).includes(
                      diagnostics.fdw_error,
                    ) && <p>{diagnostics.fdw_error}</p>}
                </div>
              </ItemCard>
            );
          })}
        </ItemGrid>
      )}
    </div>
  );
}

function indexDiagnostics(rows: ConnectionRetryResult[]) {
  return Object.fromEntries(rows.map((row) => [row.id, row]));
}

function fdwBadgeFor(connection: ConnectionRetryResult) {
  const state = String(connection.fdw_state ?? "").toLowerCase();

  if (state === "ready" || state === "connected") {
    return { text: "FDW ready", color: "green" as const };
  }

  if (state === "" || state === "unreachable") {
    return { text: "FDW unavailable", color: "red" as const };
  }

  return { text: `FDW ${connection.fdw_state}`, color: "orange" as const };
}

function formatCount(value: number | null | undefined) {
  return typeof value === "number" ? String(value) : "-";
}

function retryDiagnostics(result: ConnectionRetryResult) {
  const details = [
    result.error,
    result.detail && result.detail !== result.error ? result.detail : null,
    ...(result.warnings ?? []),
  ].filter((value): value is string => Boolean(value));

  return Array.from(new Set(details));
}
