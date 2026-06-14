import {
  DateTime,
  formatDateTime,
  type DateTimeValue,
} from "@/components/ui/datetime";

type TimestampValue = DateTimeValue;

export const formatTimestamp = formatDateTime;

export function Timestamp({
  value,
  className,
  fallback = "",
}: {
  value: TimestampValue;
  className?: string;
  fallback?: string;
}) {
  return <DateTime value={value} className={className} fallback={fallback} />;
}
