import { cn } from "@/lib/utils";

export type DateTimeValue = Date | number | string | null | undefined;

function pad(value: number) {
  return String(value).padStart(2, "0");
}

export function formatDateTime(value: DateTimeValue) {
  if (value === null || value === undefined || value === "") return "";

  const date = value instanceof Date ? value : new Date(value);
  if (Number.isNaN(date.getTime())) return "";

  return `${pad(date.getMonth() + 1)}/${pad(date.getDate())}/${date.getFullYear()} ${pad(
    date.getHours(),
  )}:${pad(date.getMinutes())}:${pad(date.getSeconds())}`;
}

export function DateTime({
  value,
  className,
  fallback = "",
}: {
  value: DateTimeValue;
  className?: string;
  fallback?: string;
}) {
  const formatted = formatDateTime(value);
  const date =
    value === null || value === undefined || value === ""
      ? null
      : new Date(value);
  const dateTime =
    date && !Number.isNaN(date.getTime()) ? date.toISOString() : undefined;

  if (!formatted && !fallback) return null;

  return (
    <time
      dateTime={dateTime}
      className={cn("text-xs text-muted-foreground", className)}
    >
      {formatted || fallback}
    </time>
  );
}
