import type { ReactNode } from "react";
import {
  AlertCircle,
  CheckCircle2,
  Info,
  Loader2,
  SearchX,
  TriangleAlert,
  X,
  type LucideIcon,
} from "lucide-react";

import { cn } from "@/lib/utils";

type StateMessageState =
  | "loading"
  | "error"
  | "empty"
  | "info"
  | "success"
  | "warning";
type StateMessageVariant = "inline" | "banner" | "panel" | "page";

type StateConfig = {
  Icon: LucideIcon;
  iconClassName: string;
  containerClassName: string;
  defaultTitle: string;
};

const stateConfig: Record<StateMessageState, StateConfig> = {
  loading: {
    Icon: Loader2,
    iconClassName: "text-muted-foreground",
    containerClassName: "border-none text-muted-foreground",
    defaultTitle: "Loading",
  },
  error: {
    Icon: AlertCircle,
    iconClassName: "text-destructive",
    containerClassName:
      "border-destructive/25 bg-destructive/5 text-destructive",
    defaultTitle: "Something went wrong",
  },
  empty: {
    Icon: SearchX,
    iconClassName: "text-muted-foreground",
    containerClassName: "text-muted-foreground",
    defaultTitle: "Nothing here yet",
  },
  info: {
    Icon: Info,
    iconClassName: "text-primary",
    containerClassName: "border-primary/20 bg-primary/5 text-foreground",
    defaultTitle: "Heads up",
  },
  success: {
    Icon: CheckCircle2,
    iconClassName: "text-emerald-700 dark:text-emerald-400",
    containerClassName:
      "border-emerald-700/20 bg-emerald-500/5 text-emerald-800 dark:border-emerald-400/25 dark:text-emerald-300",
    defaultTitle: "Success",
  },
  warning: {
    Icon: TriangleAlert,
    iconClassName: "text-orange-700 dark:text-orange-400",
    containerClassName:
      "border-orange-300 bg-orange-500/5 text-orange-800 dark:border-orange-400/25 dark:text-orange-300",
    defaultTitle: "Attention needed",
  },
};

type StateMessageProps = {
  state: StateMessageState;
  title?: ReactNode;
  message?: ReactNode;
  action?: ReactNode;
  variant?: StateMessageVariant;
  className?: string;
  onClose?: () => void;
  closeLabel?: string;
};

export function StateMessage({
  state,
  title,
  message,
  action,
  variant = "banner",
  className,
  onClose,
  closeLabel = "",
}: StateMessageProps) {
  const config = stateConfig[state];
  const Icon = config.Icon;
  const isLoading = state === "loading";
  const isEmpty = state === "empty";
  const isCompact = variant === "inline" || variant === "banner";
  const resolvedTitle = title ?? (message ? undefined : config.defaultTitle);

  return (
    <div
      role={state === "error" ? "alert" : "status"}
      aria-live={isLoading ? "polite" : undefined}
      className={cn(
        "relative",
        !isEmpty && "rounded-lg border",
        config.containerClassName,
        variant === "inline" &&
          "flex items-start gap-2 px-3 py-2 text-sm leading-5",
        variant === "banner" &&
          "flex items-start gap-3 px-3 py-2.5 text-sm leading-5",
        variant === "panel" &&
          "flex min-h-44 flex-col items-center justify-center px-6 py-10 text-center",
        variant === "page" &&
          "flex h-full min-h-64 flex-col items-center justify-center px-6 py-10 text-center",
        onClose && "pr-11",
        className,
      )}
    >
      {onClose && (
        <button
          type="button"
          aria-label={closeLabel}
          title={closeLabel}
          onClick={onClose}
          className="absolute top-2 right-2 inline-flex size-7 cursor-pointer items-center justify-center rounded-md text-current/70 transition-colors hover:bg-background/70 hover:text-current focus-visible:ring-3 focus-visible:ring-ring/50 focus-visible:outline-none"
        >
          <X className="size-4" />
        </button>
      )}

      <span
        className={cn(
          "grid shrink-0 place-items-center",
          !isEmpty && "rounded-lg",
          isCompact
            ? "mt-0.5 size-5"
            : cn("mb-4 size-10", !isEmpty && "bg-background/80"),
          config.iconClassName,
        )}
      >
        <Icon
          className={cn(
            isCompact ? "size-4" : "size-5",
            isLoading && "animate-spin",
          )}
        />
      </span>

      <div className={cn(!isCompact && "max-w-md")}>
        {resolvedTitle && (
          <p
            className={cn(
              "font-medium text-foreground",
              isCompact ? "text-sm" : "text-base",
            )}
          >
            {resolvedTitle}
          </p>
        )}
        {message && (
          <div
            className={cn(
              resolvedTitle && "mt-1",
              state === "error" ? "text-destructive" : "text-current",
              !isCompact && "text-sm",
            )}
          >
            {message}
          </div>
        )}
        {action && (
          <div
            className={cn(isCompact ? "mt-2 flex items-center gap-2" : "mt-4")}
          >
            {action}
          </div>
        )}
      </div>
    </div>
  );
}
