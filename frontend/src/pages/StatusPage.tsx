import { useCallback, useEffect, useState } from "react";
import { RefreshCw, RotateCcw } from "lucide-react";

import { api, type CubeModelSummary, type SteampipeHealth } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { ItemCard, ItemGrid } from "@/components/ui/item-grid";
import { StateMessage } from "@/components/ui/state-message";
import { Timestamp } from "@/components/ui/timestamp";
import { cn } from "@/lib/utils";

type SteampipeStatus = "connected" | "disconnected" | "loading";
type CubeStatus = "connected" | "disconnected" | "loading";

export default function StatusPage() {
  const [status, setStatus] = useState<SteampipeStatus>("loading");
  const [cubeStatus, setCubeStatus] = useState<CubeStatus>("loading");
  const [checking, setChecking] = useState(false);
  const [summary, setSummary] = useState<SteampipeHealth | null>(null);
  const [cubeSummary, setCubeSummary] = useState<CubeModelSummary | null>(null);
  const [restarting, setRestarting] = useState(false);
  const [lastChecked, setLastChecked] = useState<Date | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const checkSteampipe = useCallback(async () => {
    setChecking(true);
    setError(null);
    const errors: string[] = [];

    try {
      const nextSummary = await api.health.steampipe();
      const { steampipe } = nextSummary;
      setSummary(nextSummary);
      setStatus(steampipe);
    } catch (err: any) {
      setSummary(null);
      setStatus("disconnected");
      errors.push(err.message);
    }

    try {
      const nextCubeSummary = await api.semantics.model();
      setCubeSummary(nextCubeSummary);
      setCubeStatus(
        nextCubeSummary.cube.connected ? "connected" : "disconnected",
      );
    } catch (err: any) {
      setCubeSummary(null);
      setCubeStatus("disconnected");
      errors.push(err.message);
    } finally {
      setError(errors.length > 0 ? errors.join(" ") : null);
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
  const steampipeBadge = serviceBadgeFor(status);
  const cubeBadge = serviceBadgeFor(cubeStatus);

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

      <ItemGrid>
        <ItemCard
          title="Steampipe"
          pills={
            <Badge variant={steampipeBadge.variant}>
              {steampipeBadge.text}
            </Badge>
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
            {lastChecked && (
              <p className="flex items-center gap-1">
                <span>Last checked</span>
                <span className="text-foreground">
                  <Timestamp value={lastChecked} />
                </span>
              </p>
            )}
          </div>
        </ItemCard>

        <ItemCard
          title="Cube Core"
          pills={
            <>
              <Badge variant={cubeBadge.variant}>{cubeBadge.text}</Badge>
              <Badge variant="outline">
                {cubeSummary?.cube.cube_count ?? 0} cubes
              </Badge>
              <Badge variant="outline">
                {cubeSummary?.files.length ?? 0} files
              </Badge>
            </>
          }
          footer={
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
          }
        >
          <div className="space-y-2">
            <p>Semantic model compiler and API</p>
            {cubeSummary?.cube.error && (
              <p className="text-destructive">{cubeSummary.cube.error}</p>
            )}
            {lastChecked && (
              <p className="flex items-center gap-1">
                <span>Last checked</span>
                <span className="text-foreground">
                  <Timestamp value={lastChecked} />
                </span>
              </p>
            )}
          </div>
        </ItemCard>
      </ItemGrid>
    </div>
  );
}

function serviceBadgeFor(status: SteampipeStatus | CubeStatus) {
  if (status === "connected") {
    return { text: "Connected", variant: "success" as const };
  }

  if (status === "disconnected") {
    return { text: "Disconnected", variant: "destructive" as const };
  }

  return { text: "Checking", variant: "warning" as const };
}
