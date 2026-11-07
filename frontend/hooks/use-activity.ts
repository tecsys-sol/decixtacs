"use client";

import { useQuery } from "@tanstack/react-query";
import * as React from "react";

import { useAuth } from "@/hooks/use-auth";
import { useNow } from "@/hooks/use-now";
import { bucketLabel, type TimeRange, type TimeSeries } from "@/lib/aggregate";
import { api } from "@/lib/api";

export const KIND_LABEL: Record<string, string> = {
  authen: "Authentication",
  author: "Authorization",
  acct: "Accounting",
};

/** The viewer's IANA time zone: the server aligns buckets and weekday x hour grids to it. */
export function viewerTz(): string {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
  } catch {
    return "UTC";
  }
}

/** GET /tacacs/activity - counted by the server over the whole window. */
interface TacacsActivity {
  starts: string[]; // wall-clock bucket starts in the viewer's zone, "2026-11-07T06:00"
  series: Record<string, number[]>;
  totals: Record<string, number>;
  kinds: Record<string, number>;
}

/** GET /accounting/activity */
export interface CommandActivity {
  grain: "hour" | "day";
  total: number;
  buckets: { t: string; commands: number; dangerous: number }[];
  weekday_hour: number[][];
}

function useTacacsCounts(range: TimeRange, group: "kind" | "result", enabled = true) {
  const { can } = useAuth();
  const now = useNow();
  // re-key at most every 10 minutes so the window slides without refetching on every clock tick
  const anchor = Math.floor(now / 600_000);
  return useQuery({
    queryKey: ["tacacs", "activity", range, group, anchor],
    queryFn: () => api.get<TacacsActivity>("/tacacs/activity", { range, group, tz: viewerTz() }),
    enabled: enabled && can("accounting:read"),
    placeholderData: (p) => p,
    staleTime: 60_000,
  });
}

function toSeries(a: TacacsActivity, range: TimeRange, order: string[], label: (k: string) => string): TimeSeries {
  // "2026-11-07T06:00" without a zone parses as the browser's local time - the zone sent as tz
  const starts = a.starts.map((s) => new Date(s).getTime());
  const keys = [...order.filter((k) => k in a.series), ...Object.keys(a.series).filter((k) => !order.includes(k))];
  return {
    labels: starts.map((s) => bucketLabel(s, range)),
    starts,
    series: keys.map((k) => ({ name: label(k), data: a.series[k] })),
    counted: Object.values(a.totals).reduce((x, y) => x + y, 0),
  };
}

/** TACACS+ requests per bucket, stacked by type (authentication / authorisation / accounting). */
export function useTacacsActivity(range: TimeRange): {
  series: TimeSeries | null;
  isLoading: boolean;
  error: unknown;
} {
  const q = useTacacsCounts(range, "kind");
  const series = React.useMemo(
    () => (q.data ? toSeries(q.data, range, ["authen", "author", "acct"], (k) => KIND_LABEL[k] ?? k) : null),
    [q.data, range],
  );
  return { series, isLoading: q.isLoading, error: q.error };
}

/** Authentication / authorisation events per bucket by result, with per-result and per-kind totals. */
export function useAuthResults(range: TimeRange): {
  series: TimeSeries | null;
  totals: Record<string, number>;
  kinds: Record<string, number>;
  isLoading: boolean;
  error: unknown;
} {
  const q = useTacacsCounts(range, "result");
  const series = React.useMemo(() => {
    if (!q.data) return null;
    const order = Object.entries(q.data.totals)
      .sort((a, b) => b[1] - a[1])
      .map(([k]) => k);
    return toSeries(q.data, range, order, (k) => k);
  }, [q.data, range]);
  return { series, totals: q.data?.totals ?? {}, kinds: q.data?.kinds ?? {}, isLoading: q.isLoading, error: q.error };
}

/** Accounting commands counted by the server: per hour/day and by weekday x hour. */
export function useCommandActivity(days: number, enabled = true) {
  const { can } = useAuth();
  const now = useNow();
  const anchor = Math.floor(now / 600_000);
  return useQuery({
    queryKey: ["accounting", "activity", "window", days, anchor],
    queryFn: () => api.get<CommandActivity>("/accounting/activity", { days, tz: viewerTz() }),
    enabled: enabled && can("accounting:read"),
    placeholderData: (p) => p,
    staleTime: 60_000,
  });
}
