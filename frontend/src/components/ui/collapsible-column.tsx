import type { ReactNode } from "react";
import { ChevronLeft, ChevronRight } from "lucide-react";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

type CollapsibleColumnProps = {
  collapsed: boolean;
  children: ReactNode;
  className?: string;
  contentClassName?: string;
  collapseLabel?: string;
  expandLabel?: string;
  toggleSide?: "left" | "right";
  onCollapsedChange: (collapsed: boolean) => void;
};

export function CollapsibleColumn({
  collapsed,
  children,
  className,
  contentClassName,
  collapseLabel = "Collapse column",
  expandLabel = "Expand column",
  toggleSide = "right",
  onCollapsedChange,
}: CollapsibleColumnProps) {
  const label = collapsed ? expandLabel : collapseLabel;
  const Icon =
    toggleSide === "right"
      ? collapsed
        ? ChevronRight
        : ChevronLeft
      : collapsed
        ? ChevronLeft
        : ChevronRight;

  return (
    <aside className={cn("relative min-h-0 min-w-0", className)}>
      <Button
        type="button"
        variant="outline"
        size="icon-round"
        className={cn(
          "absolute top-1/2 z-30 grid size-7 -translate-y-1/2 place-items-center rounded-full border bg-background text-muted-foreground shadow-sm transition-colors hover:text-foreground dark:bg-background dark:hover:bg-muted",
          toggleSide === "right"
            ? "right-0 translate-x-1/2"
            : "left-0 -translate-x-1/2",
        )}
        title={label}
        aria-label={label}
        onClick={() => onCollapsedChange(!collapsed)}
      >
        <Icon className="size-4" />
      </Button>

      <div className={cn("h-full min-h-0", contentClassName)}>{children}</div>
    </aside>
  );
}
