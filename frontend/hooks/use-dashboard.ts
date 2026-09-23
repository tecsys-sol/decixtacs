"use client";

import { useQuery } from "@tanstack/react-query";

import { useAuth } from "@/hooks/use-auth";
import { api } from "@/lib/api";
import type { Dashboard } from "@/lib/types";

/** Shared dashboard summary (also feeds the sidebar counters). */
export function useDashboard() {
  const { can } = useAuth();
  return useQuery({
    queryKey: ["dashboard"],
    queryFn: () => api.get<Dashboard>("/dashboard"),
    refetchInterval: 60_000,
    enabled: can("devices:read"),
  });
}
