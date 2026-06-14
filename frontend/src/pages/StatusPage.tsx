import { useCallback, useEffect, useState } from "react";
import { RefreshCw } from "lucide-react";

import { api } from "@/lib/api";
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
  const [lastChecked, setLastChecked] = useState<Date | null>(null);
  const [error, setError] = useState<string | null>(null);

  const checkSteampipe = useCallback(async () => {
    setChecking(true);
    setError(null);

    try {
      const { steampipe } = await api.health.steampipe();
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

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold">Status</h1>
      </div>

      {error && <StateMessage state="error" variant="banner" message={error} />}

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
              <RefreshCw className={cn("size-4", checking && "animate-spin")} />
            </Button>
          }
        >
          <div className="space-y-2">
            <p>PostgreSQL FDW query service</p>
            {lastChecked && (
              <p>
                Last checked <Timestamp value={lastChecked} />
              </p>
            )}
          </div>
        </ItemCard>
      </ItemGrid>
    </div>
  );
}
