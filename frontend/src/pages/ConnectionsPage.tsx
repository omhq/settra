import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Plus } from "lucide-react";
import {
  api,
  type Connection,
  type ConnectionRetryResult,
  type GoogleSheetsConfig,
} from "@/lib/api";
import { GoogleSheetsDocumentationButton } from "@/components/connections/google-sheets-documentation-button";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { useModal } from "@/components/ui/global-modal";
import { ItemCard, ItemGrid } from "@/components/ui/item-grid";
import { RowActions } from "@/components/ui/row-actions";
import { StateMessage } from "@/components/ui/state-message";
import { Timestamp } from "@/components/ui/timestamp";

export default function ConnectionsPage() {
  const navigate = useNavigate();
  const { openModal } = useModal();
  const [connections, setConnections] = useState<Connection[]>([]);
  const [config, setConfig] = useState<GoogleSheetsConfig | null>(null);
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
      const [nextConnections, nextConfig, diagnostics] = await Promise.all([
        api.connections.list(),
        api.googleSheets.config(),
        loadConnectionDiagnostics(),
      ]);

      setConnections(nextConnections);
      setConfig(nextConfig);
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
      setWarning(`Sheet data diagnostics unavailable. ${e.message}`);
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
      title: "Disconnect sheet data?",
      body: (
        <p>
          This removes access to{" "}
          <span className="font-medium text-foreground">{connection.name}</span>{" "}
          and its saved credentials from Settra.
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
            Disconnect
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
      const name = connection?.name ?? "Sheet data";
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
          <h1 className="text-2xl font-semibold">Sheet data</h1>
        </div>
        <Button to="/sheets/new" variant="primary">
          <Plus className="size-3" />
        </Button>
      </div>

      {loading && (
        <StateMessage
          state="loading"
          variant="banner"
          message="Loading sheet data"
        />
      )}
      {error && (
        <StateMessage
          state="error"
          variant="banner"
          message={error}
          onClose={() => setError(null)}
        />
      )}
      {warning && (
        <StateMessage
          state="warning"
          variant="banner"
          message={warning}
          onClose={() => setWarning(null)}
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

      {!loading && !error && connections.length === 0 && (
        <StateMessage
          state="empty"
          variant="panel"
          title="No sheet data connected"
          message="Connect sheet data to make current values available to agents."
          action={
            <Button to="/sheets/new" variant="primary">
              <Plus className="size-3" />
              Connect sheet data
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
                headerAction={
                  config ? (
                    <GoogleSheetsDocumentationButton config={config} />
                  ) : null
                }
                pills={
                  <>
                    <Badge
                      variant={
                        c.status === "active" ? "success" : "destructive"
                      }
                    >
                      {c.status === "active" ? "Active" : "Failed"}
                    </Badge>
                    {fdwBadge && (
                      <Badge variant={fdwBadge.variant}>{fdwBadge.text}</Badge>
                    )}
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
                        ariaLabel: "Retry sheet data access",
                        loading: retrying.has(c.id),
                        disabled: retrying.has(c.id),
                        onClick: () => handleRetry(c.id),
                      },
                      {
                        key: "edit",
                        title: "Edit",
                        ariaLabel: "Edit sheet data",
                        onClick: () => navigate(`/sheets/${c.id}/edit`),
                      },
                      {
                        key: "delete",
                        title: "Delete",
                        ariaLabel: "Disconnect sheet data",
                        onClick: () => confirmDelete(c),
                      },
                    ]}
                  />
                }
              >
                <div className="space-y-2">
                  <p className="flex items-center gap-1">
                    <span>Schema</span>
                    <span className="font-mono text-foreground">
                      {diagnostics?.slug ?? c.slug}
                    </span>
                  </p>
                  <p className="flex items-center gap-1">
                    <span>Created</span>
                    <span className="text-foreground">
                      <Timestamp value={c.created_at} />
                    </span>
                  </p>
                  <p className="flex items-center gap-1">
                    <span>Available to agents</span>
                    <span className="text-foreground">
                      {formatCount(diagnostics?.fdw_table_count)} tables |{" "}
                      {formatCount(diagnostics?.fdw_column_count)} raw columns
                    </span>
                  </p>
                  {diagnostics?.fdw_schema_mode && (
                    <p className="flex items-center gap-1">
                      <span>Schema mode</span>
                      <span className="text-foreground">
                        {diagnostics.fdw_schema_mode}
                      </span>
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
    return { text: "FDW ready", variant: "success" as const };
  }

  if (state === "" || state === "unreachable") {
    return { text: "FDW unavailable", variant: "destructive" as const };
  }

  return { text: `FDW ${connection.fdw_state}`, variant: "warning" as const };
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
