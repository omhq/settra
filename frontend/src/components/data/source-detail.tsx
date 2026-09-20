import type { ReactNode } from "react";
import { ChevronRight, Database, RefreshCw, Rows3 } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Timestamp } from "@/components/ui/timestamp";
import type { ConnectionMetadataColumn } from "@/lib/api";

export type SourceDetailTable = {
  key: string;
  name: string;
  columnCount: number;
  description?: string;
  columns?: ConnectionMetadataColumn[];
};

export function SourceDetail({
  name,
  status,
  tableCount,
  managed,
  destinationName,
  destinationSchema,
  lastSyncedAt,
  tables,
  loading,
  notices,
  onClose,
  renderTableContent,
}: {
  name: string;
  status: string;
  tableCount: number;
  managed: boolean;
  destinationName?: string;
  destinationSchema: string;
  lastSyncedAt?: string | null;
  tables?: SourceDetailTable[];
  loading: boolean;
  notices?: ReactNode;
  onClose: () => void;
  renderTableContent?: (table: SourceDetailTable) => ReactNode;
}) {
  return (
    <section className="space-y-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h2 className="break-words text-lg font-semibold">{name}</h2>
          <div className="mt-2 flex flex-wrap gap-1.5">
            <Badge variant={statusVariant(status)}>{status}</Badge>
            <Badge variant="outline">{tableCount} tables</Badge>
          </div>
        </div>
        <Button type="button" variant="outline" onClick={onClose}>
          Close
        </Button>
      </div>

      <div className="space-y-2 text-sm text-muted-foreground">
        {!managed && (
          <>
            <Metric
              label="Destination"
              value={destinationName ?? "Destination"}
            />
            <Metric label="Schema" value={destinationSchema} />
          </>
        )}
        <Metric
          label="Last sync"
          value={lastSyncedAt ? <Timestamp value={lastSyncedAt} /> : "Never"}
        />
      </div>

      {notices}

      <SynchronizedSchema
        tables={tables}
        loading={loading}
        renderTableContent={renderTableContent}
      />
    </section>
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

function SynchronizedSchema({
  tables,
  loading,
  renderTableContent,
}: {
  tables?: SourceDetailTable[];
  loading: boolean;
  renderTableContent?: (table: SourceDetailTable) => ReactNode;
}) {
  if (loading) {
    return (
      <div className="flex items-center gap-2 rounded-lg border p-4 text-sm">
        <RefreshCw className="size-3.5 animate-spin" /> Loading schema
      </div>
    );
  }

  if (!tables || tables.length === 0) return null;

  return (
    <div className="space-y-4 border-t pt-5">
      <div className="flex items-center gap-2 text-sm font-medium">
        <Rows3 className="size-4" /> Synchronized schema
      </div>
      <div className="space-y-4">
        {tables.map((table) => (
          <div
            key={table.key}
            className="w-full overflow-hidden rounded-lg border"
          >
            <div className="flex items-center gap-2 border-b bg-muted/35 px-4 py-3">
              <Database className="size-3.5" />
              <span className="font-mono text-sm font-medium">
                {table.name}
              </span>
              <Badge variant="outline" className="ml-auto">
                {table.columnCount} columns
              </Badge>
            </div>
            {table.description && (
              <p className="border-b px-4 py-3 text-xs leading-5 text-muted-foreground">
                {table.description}
              </p>
            )}
            {table.columns && table.columns.length > 0 && (
              <details className="group text-xs">
                <summary className="flex cursor-pointer list-none items-center gap-2 px-4 py-3 font-medium outline-none select-none hover:bg-muted/30 focus-visible:ring-3 focus-visible:ring-inset focus-visible:ring-ring/50 [&::-webkit-details-marker]:hidden">
                  <ChevronRight className="size-3.5 shrink-0 text-muted-foreground transition-transform group-open:rotate-90" />
                  <span>View columns</span>
                </summary>
                <div className="border-t">
                  {table.columns.map((column) => (
                    <div
                      key={column.name}
                      className="flex items-start justify-between gap-4 border-b px-4 py-2.5 last:border-b-0"
                    >
                      <div className="min-w-0">
                        <p className="break-words font-mono text-foreground">
                          {column.name}
                        </p>
                        {column.description && (
                          <p className="mt-1 leading-5 text-muted-foreground">
                            {column.description}
                          </p>
                        )}
                      </div>
                      <div className="flex shrink-0 flex-wrap justify-end gap-x-2 font-mono text-muted-foreground">
                        <span>{column.type}</span>
                        {column.nullable && <span>Nullable</span>}
                      </div>
                    </div>
                  ))}
                </div>
              </details>
            )}
            {renderTableContent && (
              <div className="border-t">{renderTableContent(table)}</div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

function statusVariant(status: string) {
  if (status === "active") return "success" as const;
  if (status === "failed") return "destructive" as const;
  return "warning" as const;
}
