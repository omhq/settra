import type { ComponentProps, ReactNode } from "react";

import { cn } from "@/lib/utils";

function ItemGrid({ className, ...props }: ComponentProps<"div">) {
  return (
    <div
      className={cn(
        "grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3",
        className,
      )}
      {...props}
    />
  );
}

function ItemCard({
  title,
  pills,
  footer,
  children,
  className,
  contentClassName,
  bodyClassName,
  footerClassName,
  ...props
}: Omit<ComponentProps<"div">, "title"> & {
  title: ReactNode;
  pills?: ReactNode;
  footer?: ReactNode;
  children?: ReactNode;
  contentClassName?: string;
  bodyClassName?: string;
  footerClassName?: string;
}) {
  return (
    <div
      className={cn(
        "flex min-h-40 min-w-0 flex-col overflow-hidden rounded-[8px] border bg-card text-card-foreground transition-colors",
        className,
      )}
      {...props}
    >
      <div className={cn("flex flex-1 flex-col gap-3 p-4", contentClassName)}>
        <div className="min-w-0 space-y-2">
          <h3 className="break-words text-sm font-medium leading-snug">
            {title}
          </h3>
          {pills && (
            <div className="flex flex-wrap items-center gap-1.5">{pills}</div>
          )}
        </div>
        {children && (
          <div
            className={cn(
              "min-w-0 text-sm text-muted-foreground",
              bodyClassName,
            )}
          >
            {children}
          </div>
        )}
      </div>
      {footer && (
        <div
          className={cn(
            "mt-auto flex items-center justify-end gap-2 px-4 pb-3",
            footerClassName,
          )}
        >
          {footer}
        </div>
      )}
    </div>
  );
}

export { ItemCard, ItemGrid };
