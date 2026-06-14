import type { ReactNode } from "react";
import { X } from "lucide-react";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

type DetailColumnProps = {
  title: ReactNode;
  subtitle?: ReactNode;
  children: ReactNode;
  onClose?: () => void;
  className?: string;
};

export function DetailColumn({
  title,
  subtitle,
  children,
  onClose,
  className,
}: DetailColumnProps) {
  return (
    <aside
      className={cn("flex min-h-0 flex-col border-l bg-background", className)}
    >
      <div className="flex items-start justify-between gap-3 border-b px-4 py-3">
        <div className="min-w-0">
          <h2 className="truncate text-sm font-semibold">{title}</h2>
          {subtitle && (
            <div className="mt-1 text-xs text-muted-foreground">{subtitle}</div>
          )}
        </div>
        {onClose && (
          <Button
            type="button"
            variant="ghost"
            size="icon-sm"
            title="Close details"
            aria-label="Close details"
            onClick={onClose}
          >
            <X className="size-4" />
          </Button>
        )}
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto px-4 py-3">{children}</div>
    </aside>
  );
}
