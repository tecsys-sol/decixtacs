"use client";

import { useQuery } from "@tanstack/react-query";
import * as React from "react";

import { useAuth } from "@/hooks/use-auth";
import { useNow } from "@/hooks/use-now";
import { bucketSeries, rangeStart, type TimeRange, type TimeSeries } from "@/lib/aggregate";
import { api } from "@/lib/api";
import type { AuthEvent, CommandLog, Page } from "@/lib/types";
import { parseDate } from "@/lib/utils";

/** records fetched per source for client-side charts (API maximum) */
export const ACTIVITY_LIMIT = 1000;

export const KIND_LABEL: Record<string, string> = {
  authen: "Authentication",
  author: "Authorization",
  acct: "Accounting",
};

/** Accounting commands since the start of a window (newest first, capped). */
export function useCommandsSince(range: TimeRange | "7d-fixed", enabled = true) {
  const { can } = useAuth();
  const now = useNow();
  // re-key at most every 10 minutes so the window slides without refetching on every clock tick
  const anchor = Math.floor(now / 600_000) * 600_000;
  const start = new Date(rangeStart(range === "7d-fixed" ? "7d" : range, anchor)).toISOString();
  return useQuery({
    queryKey: ["accounting", "since", range, anchor],
    queryFn: () => api.get<Page<CommandLog>>("/accounting/commands", { start, limit: ACTIVITY_LIMIT }),
    enabled: enabled && can("accounting:read"),
    placeholderData: (p) => p,
    staleTime: 60_000,
  });
}

/** Latest TACACS+ authentication / authorisation events (the API has no time filter; capped). */
export function useAuthEvents(enabled = true) {
  const { can } = useAuth();
  return useQuery({
    queryKey: ["tacacs", "events", "recent", ACTIVITY_LIMIT],
    queryFn: () => api.get<Page<AuthEvent>>("/tacacs/events", { limit: ACTIVITY_LIMIT }),
    enabled: enabled && can("accounting:read"),
    staleTime: 60_000,
  });
}

export function isTruncated(p: Page<unknown> | undefined): boolean {
  return !!p && p.total > p.items.length;
}

/** events are newest-first: the window is incomplete only if the oldest loaded one is inside it */
function eventsTruncated(p: Page<AuthEvent> | undefined, since: number): boolean {
  if (!p || p.total <= p.items.length || !p.items.length) return false;
  const oldest = parseDate(p.items[p.items.length - 1].timestamp);
  return !!oldest && oldest.getTime() > since;
}

/** TACACS+ requests per bucket, stacked by type (authentication / authorisation / accounting). */
export function useTacacsActivity(range: TimeRange): {
  series: TimeSeries | null;
  isLoading: boolean;
  error: unknown;
  truncated: boolean;
} {
  const now = useNow();
  const commands = useCommandsSince(range);
  const events = useAuthEvents();
  const series = React.useMemo(() => {
    if (!commands.data && !events.data) return null;
    const t = now;
    const rows: { t: string; kind: string }[] = [
      ...(events.data?.items ?? []).map((e) => ({ t: e.timestamp, kind: KIND_LABEL[e.kind] ?? e.kind })),
      ...(commands.data?.items ?? []).map((c) => ({ t: c.timestamp, kind: "Accounting" })),
    ];
    return bucketSeries(rows, (r) => r.t, range, t, { group: (r) => r.kind, groupOrder: ["Authentication", "Authorization", "Accounting"] });
  }, [commands.data, events.data, range, now]);
  return {
    series,
    isLoading: commands.isLoading || events.isLoading,
    error: commands.error ?? events.error,
    truncated: isTruncated(commands.data) || eventsTruncated(events.data, rangeStart(range, now)),
  };
}
