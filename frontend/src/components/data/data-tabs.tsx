import type { ReactNode } from "react";
import { Link, useLocation } from "react-router-dom";

import { cn } from "@/lib/utils";

const items = [
  { label: "Connections", href: "/data" },
  { label: "Pipes", href: "/data/pipes" },
  { label: "Collections", href: "/data/collections" },
];

export function DataTabs({ action }: { action?: ReactNode }) {
  const { pathname } = useLocation();

  return (
    <div className="flex items-end gap-3 border-b">
      <nav className="flex items-center gap-1" aria-label="Data sections">
        {items.map((item) => {
          const active =
            item.href === "/data"
              ? pathname === "/data"
              : item.href === "/data/pipes"
                ? pathname === "/data/pipes" ||
                  /^\/data\/(new|\d+\/edit)$/.test(pathname)
                : pathname.startsWith(item.href);

          return (
            <Link
              key={item.href}
              to={item.href}
              className={cn(
                "relative px-3 py-2 text-sm font-medium text-muted-foreground transition-colors hover:text-foreground",
                active &&
                  "text-foreground after:absolute after:inset-x-0 after:-bottom-px after:h-0.5 after:bg-primary",
              )}
            >
              {item.label}
            </Link>
          );
        })}
      </nav>
      {action && <div className="ml-auto pb-1">{action}</div>}
    </div>
  );
}
