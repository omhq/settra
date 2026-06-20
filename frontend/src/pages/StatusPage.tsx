import { useCallback, useEffect, useState } from "react";
import { RefreshCw, RotateCcw } from "lucide-react";

import { api, type SteampipeHealth } from "@/lib/api";
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
  const [summary, setSummary] = useState<SteampipeHealth | null>(null);
  const [restarting, setRestarting] = useState(false);
  const [lastChecked, setLastChecked] = useState<Date | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const checkSteampipe = useCallback(async () => {
    setChecking(true);
    setError(null);

    try {
      const nextSummary = await api.health.steampipe();
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

  async function handleRestartSteampipe() {
    setRestarting(true);
    setError(null);
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
          message="Checking Steampipe"
        />
      )}
      {error && <StateMessage state="error" variant="banner" message={error} />}
      {notice && (
        <StateMessage state="success" variant="banner" message={notice} />
      )}

      <div className="space-y-3">
        <h2 className="font-medium text-foreground">Providers</h2>
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
                  Restart
                </Button>
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  disabled={checking}
                  onClick={() => void checkSteampipe()}
                >
                  <RefreshCw
                    className={cn("size-3.5", checking && "animate-spin")}
                  />
                  Refresh
                </Button>
              </>
            }
          >
            <div className="space-y-2">
              <p>PostgreSQL FDW query service</p>
              <p>
                Service restart{" "}
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
      </div>
    </div>
  );
}
