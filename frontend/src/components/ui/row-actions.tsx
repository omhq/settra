import type * as React from "react";
import {
  Ban,
  Check,
  EyeOff,
  FlaskConical,
  Pencil,
  RefreshCw,
  RotateCcw,
  RotateCw,
  Search,
  Trash2,
  X,
  type LucideIcon,
} from "lucide-react";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

const rowActionSpecs = {
  sync: { title: "Sync", icon: RefreshCw, order: 10 },
  retry: { title: "Retry", icon: RotateCw, order: 20 },
  test: { title: "Test", icon: FlaskConical, order: 30 },
  approve: { title: "Approve", icon: Check, order: 40 },
  review: { title: "Review", icon: Search, order: 50 },
  edit: { title: "Edit", icon: Pencil, order: 60 },
  reject: { title: "Reject", icon: X, order: 70, danger: true },
  hide: { title: "Hide", icon: EyeOff, order: 80 },
  disable: { title: "Disable", icon: Ban, order: 90 },
  reset: { title: "Reset", icon: RotateCcw, order: 100 },
  dismiss: { title: "Dismiss", icon: X, order: 110 },
  delete: { title: "Delete", icon: Trash2, order: 120, danger: true },
} as const satisfies Record<
  string,
  { title: string; icon: LucideIcon; order: number; danger?: boolean }
>;

export type RowActionKey = keyof typeof rowActionSpecs;

export type RowAction = {
  key: RowActionKey;
  title?: string;
  ariaLabel?: string;
  icon?: React.ReactNode;
  danger?: boolean;
  disabled?: boolean;
  loading?: boolean;
  order?: number;
  className?: string;
  onClick: () => void | Promise<void>;
};

export function RowActions({
  actions,
  className,
  children,
  ...props
}: React.ComponentProps<"div"> & { actions?: RowAction[] }) {
  const orderedActions = actions
    ? [...actions].sort((left, right) => actionOrder(left) - actionOrder(right))
    : null;

  return (
    <div className={cn("flex items-center gap-1", className)} {...props}>
      {orderedActions
        ? orderedActions.map((action) => (
            <RowActionButton
              key={`${action.key}-${action.title ?? action.ariaLabel ?? ""}`}
              title={action.title ?? rowActionSpecs[action.key].title}
              aria-label={
                action.ariaLabel ??
                action.title ??
                rowActionSpecs[action.key].title
              }
              danger={actionDanger(action)}
              disabled={action.disabled || action.loading}
              className={action.className}
              onClick={() => {
                void action.onClick();
              }}
            >
              {actionIcon(action)}
            </RowActionButton>
          ))
        : children}
    </div>
  );
}

export function RowActionButton({
  className,
  danger = false,
  title,
  "aria-label": ariaLabel,
  ...props
}: React.ComponentProps<typeof Button> & {
  danger?: boolean;
  title: string;
  "aria-label"?: string;
}) {
  return (
    <Button
      variant="ghost"
      size="icon"
      title={title}
      aria-label={ariaLabel ?? title}
      className={cn(
        "size-8 text-muted-foreground",
        danger ? "hover:text-destructive" : "hover:text-foreground",
        className,
      )}
      {...props}
    />
  );
}

function actionOrder(action: RowAction) {
  return action.order ?? rowActionSpecs[action.key].order;
}

function actionDanger(action: RowAction) {
  const spec = rowActionSpecs[action.key];

  return action.danger ?? ("danger" in spec ? spec.danger : false);
}

function actionIcon(action: RowAction) {
  if (action.icon) return action.icon;

  const Icon = rowActionSpecs[action.key].icon;

  return <Icon className={cn("size-4", action.loading && "animate-spin")} />;
}
