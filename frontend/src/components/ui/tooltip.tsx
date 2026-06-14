import type { ReactNode } from "react";

import { cn } from "@/lib/utils";

type TooltipSide = "top" | "right" | "bottom" | "left";

const sideClasses: Record<TooltipSide, string> = {
  top: "bottom-[calc(100%+0.5rem)] left-1/2 -translate-x-1/2",
  right: "left-[calc(100%+0.5rem)] top-1/2 -translate-y-1/2",
  bottom: "left-1/2 top-[calc(100%+0.5rem)] -translate-x-1/2",
  left: "right-[calc(100%+0.5rem)] top-1/2 -translate-y-1/2",
};

export function Tooltip({
  children,
  content,
  side = "top",
  className,
}: {
  children: ReactNode;
  content: ReactNode;
  side?: TooltipSide;
  className?: string;
}) {
  return (
    <span className={cn("group/tooltip relative inline-flex", className)}>
      {children}
      <span
        role="tooltip"
        className={cn(
          "pointer-events-none absolute z-30 whitespace-nowrap rounded-md border bg-popover px-2 py-1 text-xs font-medium text-popover-foreground opacity-0 shadow-sm transition-opacity group-hover/tooltip:opacity-100 group-focus-within/tooltip:opacity-100",
          sideClasses[side],
        )}
      >
        {content}
      </span>
    </span>
  );
}
