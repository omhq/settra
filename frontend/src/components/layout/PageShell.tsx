import type { ReactNode } from "react";

import { cn } from "@/lib/utils";

export default function PageShell({
  children,
  className,
}: {
  children: ReactNode;
  className?: string;
}) {
  return (
    <div className={cn("h-full overflow-y-auto p-6", className)}>
      {children}
    </div>
  );
}
