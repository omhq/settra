import { useCallback, useEffect, useState } from "react";
import { RefreshCw } from "lucide-react";

import { api, type MCPRequestPage } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { ItemCard, ItemGrid } from "@/components/ui/item-grid";
import { StateMessage } from "@/components/ui/state-message";
import { Timestamp } from "@/components/ui/timestamp";

const numberFormatter = new Intl.NumberFormat();

export default function RequestsPage() {
  const [data, setData] = useState<MCPRequestPage | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadRequests = useCallback(
    async (cursor: number | null = null, append = false) => {
      if (append) {
        setLoadingMore(true);
      } else {
        setLoading(true);
      }
      setError(null);

      try {
        const next = await api.requests.list(cursor);
        setData((current) =>
          append && current
            ? {
                ...next,
                requests: [...current.requests, ...next.requests],
              }
            : next,
        );
      } catch (err: unknown) {
        setError(errorMessage(err));
      } finally {
        if (append) {
          setLoadingMore(false);
        } else {
          setLoading(false);
        }
      }
    },
    [],
  );

  useEffect(() => {
    void loadRequests();
  }, [loadRequests]);

  if (loading && !data) {
    return (
      <StateMessage state="loading" variant="page" message="Loading requests" />
    );
  }

  const summary = data?.summary;
  const failedRequests = summary?.failed_requests ?? 0;
  const totalRequests = summary?.total_requests ?? 0;
  const errorRate = totalRequests ? (failedRequests / totalRequests) * 100 : 0;

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold">Requests</h1>
          <p className="mt-1 max-w-3xl text-sm text-muted-foreground">
            MCP tool and resource activity. Token counts are payload-size
            estimates; prompts, arguments, results, and chat transcripts are not
            stored.
          </p>
        </div>
        <Button
          type="button"
          variant="outline"
          disabled={loading || loadingMore}
          onClick={() => void loadRequests()}
        >
          <RefreshCw className={loading ? "size-4 animate-spin" : "size-4"} />
          Refresh
        </Button>
      </div>

      {error && (
        <StateMessage
          state="error"
          variant="banner"
          message={error}
          onClose={() => setError(null)}
        />
      )}

      <ItemGrid className="sm:grid-cols-2 xl:grid-cols-4">
        <MetricCard
          label="Retained requests"
          value={formatNumber(totalRequests)}
        />
        <MetricCard
          label="Estimated tokens"
          value={formatNumber(summary?.estimated_tokens ?? 0)}
          detail={`${formatNumber(summary?.estimated_input_tokens ?? 0)} in · ${formatNumber(summary?.estimated_output_tokens ?? 0)} out`}
        />
        <MetricCard
          label="Error rate"
          value={`${errorRate.toFixed(errorRate < 10 ? 1 : 0)}%`}
          detail={`${formatNumber(failedRequests)} failed`}
        />
        <MetricCard
          label="Average duration"
          value={formatDuration(summary?.average_duration_ms ?? 0)}
        />
      </ItemGrid>

      {!data?.requests.length ? (
        <StateMessage
          state="empty"
          variant="panel"
          title="No MCP requests yet"
          message="Tool calls and resource reads will appear here."
        />
      ) : (
        <section className="overflow-hidden rounded-lg border bg-card">
          <div className="flex flex-wrap items-center justify-between gap-2 border-b px-4 py-3">
            <h2 className="text-sm font-medium">Recent requests</h2>
            <Badge variant="outline">
              Keeping up to {formatNumber(data.tracking.history_limit)}
            </Badge>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full min-w-[860px] text-left text-sm">
              <thead className="border-b bg-muted/40 text-xs text-muted-foreground">
                <tr>
                  <th scope="col" className="px-4 py-2.5 font-medium">
                    Time
                  </th>
                  <th scope="col" className="px-4 py-2.5 font-medium">
                    Request
                  </th>
                  <th scope="col" className="px-4 py-2.5 font-medium">
                    Status
                  </th>
                  <th
                    scope="col"
                    className="px-4 py-2.5 text-right font-medium"
                  >
                    Duration
                  </th>
                  <th
                    scope="col"
                    className="px-4 py-2.5 text-right font-medium"
                  >
                    Est. tokens
                  </th>
                  <th
                    scope="col"
                    className="px-4 py-2.5 text-right font-medium"
                  >
                    Payload
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y">
                {data.requests.map((request) => (
                  <tr key={request.id} className="hover:bg-muted/25">
                    <td className="whitespace-nowrap px-4 py-3 text-muted-foreground">
                      <Timestamp value={request.created_at} />
                    </td>
                    <td className="max-w-md px-4 py-3">
                      <div className="flex items-center gap-2">
                        <Badge variant="secondary">{request.kind}</Badge>
                        <span className="truncate font-mono text-xs">
                          {request.name}
                        </span>
                      </div>
                      {request.error_type && (
                        <p className="mt-1 text-xs text-destructive">
                          {request.error_type}
                        </p>
                      )}
                    </td>
                    <td className="px-4 py-3">
                      <Badge
                        variant={
                          request.status === "success"
                            ? "success"
                            : "destructive"
                        }
                      >
                        {request.status}
                      </Badge>
                    </td>
                    <td className="whitespace-nowrap px-4 py-3 text-right tabular-nums">
                      {formatDuration(request.duration_ms)}
                    </td>
                    <td className="whitespace-nowrap px-4 py-3 text-right tabular-nums">
                      {formatNumber(request.estimated_tokens)}
                    </td>
                    <td className="whitespace-nowrap px-4 py-3 text-right tabular-nums text-muted-foreground">
                      {formatBytes(
                        request.request_bytes + request.response_bytes,
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {data.next_cursor !== null && (
            <div className="flex justify-center border-t px-4 py-3">
              <Button
                type="button"
                variant="outline"
                disabled={loadingMore}
                onClick={() => void loadRequests(data.next_cursor, true)}
              >
                {loadingMore ? "Loading…" : "Load more"}
              </Button>
            </div>
          )}
        </section>
      )}
    </div>
  );
}

function MetricCard({
  label,
  value,
  detail,
}: {
  label: string;
  value: string;
  detail?: string;
}) {
  return (
    <ItemCard title={label} className="min-h-28" contentClassName="gap-1">
      <p className="text-2xl font-semibold tabular-nums text-foreground">
        {value}
      </p>
      {detail && <p className="text-xs">{detail}</p>}
    </ItemCard>
  );
}

function errorMessage(error: unknown): string {
  return error instanceof Error
    ? error.message
    : "Could not load MCP requests.";
}

function formatNumber(value: number): string {
  return numberFormatter.format(Math.round(value));
}

function formatDuration(value: number): string {
  if (value < 1000) return `${Math.round(value)} ms`;
  return `${(value / 1000).toFixed(value < 10_000 ? 1 : 0)} s`;
}

function formatBytes(value: number): string {
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`;
  return `${(value / (1024 * 1024)).toFixed(1)} MB`;
}
