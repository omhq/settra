import { useCallback, useEffect, useState } from "react";
import { RefreshCw, RotateCcw } from "lucide-react";

import {
  api,
  type ConnectionRetryResult,
  type FdwHealthSummary,
} from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { ItemCard, ItemGrid } from "@/components/ui/item-grid";
import { StateMessage } from "@/components/ui/state-message";
import { StatusBadge } from "@/components/ui/status-badge";
import { Timestamp } from "@/components/ui/timestamp";
import { cn } from "@/lib/utils";

type SteampipeStatus = "connected" | "disconnected" | "loading";

export default function StatusPage() {
  const [status, setStatus] = useState<SteampipeStatus>("loading");
  const [checking, setChecking] = useState(false);
  const [summary, setSummary] = useState<FdwHealthSummary | null>(null);
  const [refreshing, setRefreshing] = useState<Set<number>>(new Set());
  const [restarting, setRestarting] = useState(false);
  const [lastChecked, setLastChecked] = useState<Date | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [warning, setWarning] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const checkSteampipe = useCallback(async () => {
    setChecking(true);
    setError(null);
    setWarning(null);

    try {
      const nextSummary = await api.health.fdw();
      const { steampipe } = nextSummary;
      setSummary(nextSummary);
      setStatus(steampipe);
    } catch (err: any) {
      setStatus("disconnected");
      setError(err.message);
    } finally {
      setLastChecked(new Date());
      setChecking(false);
    }
  }, []);

  useEffect(() => {
    void checkSteampipe();
    const interval = window.setInterval(() => void checkSteampipe(), 30_000);
    return () => window.clearInterval(interval);
  }, [checkSteampipe]);

  async function handleRefreshConnection(connection: ConnectionRetryResult) {
    setRefreshing((prev) => new Set(prev).add(connection.id));
    setError(null);
    setWarning(null);
    setNotice(null);

    try {
      const result = await api.health.refreshFdw(connection.id);
      const diagnostics = resultWarnings(result);

      if (diagnostics.length) {
        setWarning(
          `${connection.name ?? "Connection"} refreshed. ${diagnostics.join(" ")}`,
        );
      } else {
        setNotice(`${connection.name ?? "Connection"} FDW metadata refreshed.`);
      }

      await checkSteampipe();
    } catch (err: any) {
      setError(err.message);
    } finally {
      setRefreshing((prev) => {
        const next = new Set(prev);
        next.delete(connection.id);
        return next;
      });
    }
  }

  async function handleRestartSteampipe() {
    setRestarting(true);
    setError(null);
    setWarning(null);
    setNotice(null);

    try {
      const result = await api.health.restartSteampipe();
      setNotice(
        result.output
          ? `Steampipe restart requested. ${result.output}`
          : "Steampipe restart requested.",
      );
      await checkSteampipe();
    } catch (err: any) {
      setError(err.message);
    } finally {
      setRestarting(false);
    }
  }

  const connections = summary?.connections ?? [];
  const restartSupported = Boolean(summary?.actions.restart_supported);

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold">Status</h1>
      </div>

      {checking && !summary && (
        <StateMessage
          state="loading"
          variant="banner"
          message="Checking Steampipe and FDW providers"
        />
      )}
      {error && <StateMessage state="error" variant="banner" message={error} />}
      {warning && (
        <StateMessage state="warning" variant="banner" message={warning} />
      )}
      {notice && (
        <StateMessage state="success" variant="banner" message={notice} />
      )}

      <ItemGrid>
        <ItemCard
          title="Steampipe"
          pills={
            <StatusBadge
              text={
                status === "loading"
                  ? "Checking"
                  : status === "connected"
                    ? "Connected"
                    : "Disconnected"
              }
              color={
                status === "loading"
                  ? "orange"
                  : status === "connected"
                    ? "green"
                    : "red"
              }
            />
          }
          footer={
            <>
              <Button
                type="button"
                variant="outline"
                size="sm"
                disabled={restarting || !restartSupported}
                onClick={() => void handleRestartSteampipe()}
              >
                <RotateCcw
                  className={cn("size-3.5", restarting && "animate-spin")}
                />
                Restart service
              </Button>
              <Button
                type="button"
                variant="ghost"
                size="icon"
                className="size-8 text-muted-foreground hover:text-foreground"
                title="Refresh"
                aria-label="Refresh status"
                disabled={checking}
                onClick={() => void checkSteampipe()}
              >
                <RefreshCw
                  className={cn("size-4", checking && "animate-spin")}
                />
              </Button>
            </>
          }
        >
          <div className="space-y-2">
            <p>PostgreSQL FDW query service</p>
            <p>
              FDW cache refresh is available for connection metadata. Service
              restart{" "}
              {restartSupported ? "is configured." : "is not configured."}
            </p>
            {lastChecked && (
              <p>
                Last checked <Timestamp value={lastChecked} />
              </p>
            )}
          </div>
        </ItemCard>
      </ItemGrid>

      {!checking && summary && connections.length === 0 && (
        <StateMessage
          state="empty"
          variant="panel"
          title="No FDW providers yet"
          message="Add a connection to inspect its Steampipe registration and refresh its metadata cache from here."
        />
      )}

      {connections.length > 0 && (
        <div className="space-y-3">
          <div>
            <h2 className="text-sm font-medium text-foreground">
              FDW Providers
            </h2>
          </div>
          <ItemGrid>
            {connections.map((connection) => {
              const fdwBadge = fdwBadgeFor(connection);

              return (
                <ItemCard
                  key={connection.id}
                  title={
                    connection.name ??
                    connection.slug ??
                    `Connection ${connection.id}`
                  }
                  pills={
                    <>
                      <StatusBadge
                        text={fdwBadge.text}
                        color={fdwBadge.color}
                      />
                      <Badge variant="secondary" className="capitalize">
                        {connection.plugin ?? "unknown"}
                      </Badge>
                      <Badge variant="outline">
                        {connection.status === "active"
                          ? "Saved active"
                          : "Saved failed"}
                      </Badge>
                    </>
                  }
                  footer={
                    <Button
                      type="button"
                      variant="outline"
                      size="sm"
                      disabled={refreshing.has(connection.id)}
                      onClick={() => void handleRefreshConnection(connection)}
                    >
                      <RefreshCw
                        className={cn(
                          "size-3.5",
                          refreshing.has(connection.id) && "animate-spin",
                        )}
                      />
                      Refresh FDW
                    </Button>
                  }
                >
                  <div className="space-y-2">
                    <p>
                      Schema{" "}
                      <span className="font-mono text-foreground">
                        {connection.slug ?? "unknown"}
                      </span>
                    </p>
                    <p>
                      Tables exposed {formatCount(connection.fdw_table_count)} |
                      Columns exposed {formatCount(connection.fdw_column_count)}
                    </p>
                    {connection.fdw_schema_mode && (
                      <p>Schema mode {connection.fdw_schema_mode}</p>
                    )}
                    {connection.fdw_plugin_instance && (
                      <p className="break-all">
                        Plugin instance {connection.fdw_plugin_instance}
                      </p>
                    )}
                    {connection.fdw_config_file && (
                      <p className="break-all">
                        Config {connection.fdw_config_file}
                      </p>
                    )}
                    {connection.warnings && connection.warnings.length > 0 && (
                      <div className="space-y-1">
                        {connection.warnings.slice(0, 3).map((item, index) => (
                          <p key={`${connection.id}-warning-${index}`}>
                            {item}
                          </p>
                        ))}
                      </div>
                    )}
                    {connection.fdw_error &&
                      !(connection.warnings ?? []).includes(
                        connection.fdw_error,
                      ) && <p>{connection.fdw_error}</p>}
                  </div>
                </ItemCard>
              );
            })}
          </ItemGrid>
        </div>
      )}
    </div>
  );
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

function resultWarnings(result: ConnectionRetryResult) {
  return Array.from(
    new Set(
      [result.detail, result.error, ...(result.warnings ?? [])].filter(
        (value): value is string => Boolean(value),
      ),
    ),
  );
}
