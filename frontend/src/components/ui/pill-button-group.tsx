import type { ReactNode } from "react";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

export type PillButtonGroupItem = {
  id: string | number;
  label: ReactNode;
  count?: ReactNode;
  detail?: ReactNode;
  active?: boolean;
  disabled?: boolean;
  title?: string;
  ariaLabel?: string;
  onClick: () => void;
};

export function PillButtonGroup({
  label,
  ariaLabel,
  items,
  className,
  labelClassName,
  listClassName,
}: {
  label?: ReactNode;
  ariaLabel?: string;
  items: PillButtonGroupItem[];
  className?: string;
  labelClassName?: string;
  listClassName?: string;
}) {
  const groupLabel =
    ariaLabel ?? (typeof label === "string" ? label : undefined);

  return (
    <div className={cn(label && "space-y-2", className)}>
      {label && (
        <p className={cn("text-base font-semibold", labelClassName)}>{label}</p>
      )}
      <div
        role="group"
        aria-label={groupLabel}
        className={cn("flex flex-wrap gap-1.5", listClassName)}
      >
        {items.map((item) => (
          <Button
            key={item.id}
            type="button"
            variant="outline"
            title={item.title}
            aria-label={itemAriaLabel(item)}
            aria-pressed={item.active}
            disabled={item.disabled}
            className={cn(
              "h-8 gap-1.5 px-3",
              item.active
                ? "border-primary/30 bg-primary/10 text-primary hover:bg-primary/15 hover:text-primary"
                : "text-muted-foreground hover:bg-muted hover:text-foreground",
            )}
            onClick={item.onClick}
          >
            <span>{item.label}</span>
            {item.count !== undefined && (
              <span
                className={cn(
                  "text-xs",
                  item.active ? "text-primary/75" : "text-muted-foreground",
                )}
              >
                {item.count}
              </span>
            )}
            {item.detail !== undefined && (
              <span
                className={cn(
                  "text-xs capitalize",
                  item.active ? "text-primary/75" : "text-muted-foreground",
                )}
              >
                {item.detail}
              </span>
            )}
          </Button>
        ))}
      </div>
    </div>
  );
}

function itemAriaLabel(item: PillButtonGroupItem) {
  if (item.ariaLabel) return item.ariaLabel;

  const label = primitiveText(item.label);
  const detail = primitiveText(item.detail);
  const count = primitiveText(item.count);
  const parts = [label, detail, count].filter(Boolean);

  return parts.length ? parts.join(", ") : undefined;
}

function primitiveText(value: ReactNode) {
  if (typeof value === "string" || typeof value === "number") {
    return String(value);
  }

  return undefined;
}
