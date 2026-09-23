"use client";

import { useQuery } from "@tanstack/react-query";

import { useAuth } from "@/hooks/use-auth";
import { useNow } from "@/hooks/use-now";
import { api } from "@/lib/api";
import type { Backup, Page } from "@/lib/types";

/** API maximum page size for /backups */
export const BACKUP_STATS_LIMIT = 500;

/** Backups collected in the last `days` days (newest first, capped at 500) for charts. */
export function useRecentBackups(days = 30, filters: { device_id?: string; status?: string; author?: string; changed_only?: boolean } = {}) {
  const { can } = useAuth();
  const now = useNow();
  const anchor = Math.floor(now / 600_000) * 600_000;
  const since = new Date(anchor - days * 86_400_000).toISOString();
  return useQuery({
    queryKey: ["backups", "stats", days, filters, anchor],
    queryFn: () =>
      api.get<Page<Backup>>("/backups", {
        since,
        limit: BACKUP_STATS_LIMIT,
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
