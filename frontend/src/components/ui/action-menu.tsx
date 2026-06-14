import { useEffect, useRef, useState, type ReactNode } from "react";
import { MoreVertical } from "lucide-react";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

export type ActionMenuAction = {
  label: string;
  icon?: ReactNode;
  danger?: boolean;
  disabled?: boolean;
  onSelect: () => void;
};

export function ActionMenu({
  actions,
  disabled,
  label = "More actions",
  className,
}: {
  actions: ActionMenuAction[];
  disabled?: boolean;
  label?: string;
  className?: string;
}) {
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;

    function handlePointerDown(event: PointerEvent) {
      if (!rootRef.current?.contains(event.target as Node)) setOpen(false);
    }

    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") setOpen(false);
    }

    document.addEventListener("pointerdown", handlePointerDown);
    document.addEventListener("keydown", handleKeyDown);
    return () => {
      document.removeEventListener("pointerdown", handlePointerDown);
      document.removeEventListener("keydown", handleKeyDown);
    };
  }, [open]);

  return (
    <div ref={rootRef} className={cn("relative", className)}>
      <Button
        type="button"
        variant="ghost"
        size="icon"
        aria-label={label}
        aria-haspopup="menu"
        aria-expanded={open}
        disabled={disabled}
        className="size-7 text-muted-foreground hover:text-foreground"
        onClick={() => setOpen((current) => !current)}
      >
        <MoreVertical className="size-4" />
      </Button>

      {open && !disabled && (
        <div
          role="menu"
          className="absolute right-0 z-30 mt-1 min-w-36 rounded-lg border bg-popover p-1 text-popover-foreground shadow-lg"
        >
          {actions.map((action) => (
            <button
              key={action.label}
              type="button"
              role="menuitem"
              disabled={action.disabled}
              className={cn(
                "flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-sm transition-colors hover:bg-muted focus-visible:bg-muted focus-visible:outline-none",
                action.danger && "text-destructive hover:text-destructive",
                action.disabled && "cursor-not-allowed opacity-50",
              )}
              onClick={() => {
                setOpen(false);
                action.onSelect();
              }}
            >
              {action.icon && <span className="shrink-0">{action.icon}</span>}
              <span>{action.label}</span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
