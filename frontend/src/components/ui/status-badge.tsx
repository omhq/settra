import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

export type StatusBadgeColor = "green" | "red" | "orange";

const statusBadgeClasses: Record<StatusBadgeColor, string> = {
  green:
    "border-emerald-200 bg-emerald-500/10 text-emerald-700 dark:border-emerald-500/20 dark:bg-emerald-500/15 dark:text-emerald-300",
  red: "border-destructive/20 bg-destructive/10 text-destructive dark:border-destructive/30 dark:bg-destructive/20",
  orange:
    "border-orange-200 bg-orange-500/10 text-orange-700 dark:border-orange-500/20 dark:bg-orange-500/15 dark:text-orange-300",
};

export function StatusBadge({
  text,
  color = "orange",
  className,
  title,
}: {
  text: string;
  color?: StatusBadgeColor;
  className?: string;
  title?: string;
}) {
  return (
    <Badge
      variant="outline"
      title={title}
      className={cn(statusBadgeClasses[color], className)}
    >
      {text}
    </Badge>
  );
}
