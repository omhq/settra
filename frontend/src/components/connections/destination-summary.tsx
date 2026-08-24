import { Database } from "lucide-react";

import type { Destination } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Label } from "@/components/ui/label";

export function DestinationSummary({
  destination,
}: {
  destination: Destination;
}) {
  const location = destination.location;

  return (
    <div className="space-y-1.5">
      <Label>Destination</Label>
      <div className="space-y-3 rounded-md border border-border bg-muted/20 p-4">
        <div className="flex items-start justify-between gap-3">
          <div className="flex min-w-0 items-start gap-3">
            <div className="rounded-md border border-border bg-background p-2 text-muted-foreground">
              <Database className="size-4" />
            </div>
            <div className="min-w-0">
              <p className="font-medium text-foreground">{destination.name}</p>
              <p className="text-xs text-muted-foreground">
                PostgreSQL destination managed by this Settra deployment
              </p>
            </div>
          </div>
          <div className="flex shrink-0 gap-1.5">
            {destination.is_default && <Badge variant="outline">Default</Badge>}
            {destination.is_builtin && (
              <Badge variant="outline">Built in</Badge>
            )}
          </div>
        </div>

        {location && (
          <p className="font-mono text-xs text-foreground">
            {location.host}:{location.port}/{location.database}
            {destination.schema ? ` · schema ${destination.schema}` : ""}
          </p>
        )}

        <p className="text-xs text-muted-foreground">
          Source and destination are stored separately. This is the only enabled
          destination for now; additional destinations can be added later
          without changing the source definition.
        </p>
      </div>
    </div>
  );
}
