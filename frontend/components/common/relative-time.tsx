"use client";

import { useNow } from "@/hooks/use-now";
import { formatDateTime, formatRelative, parseDate } from "@/lib/utils";

/** Relative timestamp ("5 minutes ago") that refreshes periodically; the absolute time is in the tooltip. */
export function RelativeTime({ value, className }: { value: string | null | undefined; className?: string }) {
  const now = useNow();
  const d = parseDate(value);
  if (!d) return <span className={className}>—</span>;
  return (
    <time dateTime={d.toISOString()} title={formatDateTime(d)} className={className} suppressHydrationWarning>
      {now === 0 ? formatDateTime(d) : formatRelative(d, now)}
    </time>
  );
}
