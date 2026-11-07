"use client";

import { useQuery } from "@tanstack/react-query";

import { useAuth } from "@/hooks/use-auth";
import { viewerTz } from "@/hooks/use-activity";
import { useNow } from "@/hooks/use-now";
import type { TimeRange } from "@/lib/aggregate";
import { api } from "@/lib/api";

/** GET /backups/activity - counted by the server over every matching backup, not a capped list. */
export interface BackupActivity {
  total: number;
  outcomes: { changed: number; unchanged: number; failed: number };
  /** the last 30 local days */
  days: { starts: string[]; total: number[]; ok: number[]; changed: number[]; lines_added: number[]; lines_removed: number[] };
  last_24h: { changed: number; unplanned: number };
  /** Changed / Unchanged / Failed per bucket of `range` */
  starts: string[];
  series: Record<string, number[]>;
}

export function useBackupActivity(
  range: TimeRange = "30d",
  filters: { device_id?: string; status?: string; author?: string; changed_only?: boolean } = {},
) {
  const { can } = useAuth();
  const now = useNow();
  // re-key at most every 10 minutes so the window slides without refetching on every clock tick
  const anchor = Math.floor(now / 600_000);
  return useQuery({
    queryKey: ["backups", "activity", range, filters, anchor],
    queryFn: () =>
      api.get<BackupActivity>("/backups/activity", {
        range,
        tz: viewerTz(),
        device_id: filters.device_id,
        status: filters.status,
        author: filters.author,
        changed_only: filters.changed_only || undefined,
      }),
    enabled: can("configs:read"),
    placeholderData: (p) => p,
    staleTime: 60_000,
  });
}
