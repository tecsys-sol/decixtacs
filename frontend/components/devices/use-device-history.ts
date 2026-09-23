"use client";

import { useQuery } from "@tanstack/react-query";

import { api } from "@/lib/api";
import type { CommitInfo } from "@/lib/types";

export function useDeviceHistory(deviceId: string, limit = 200) {
  return useQuery({
    queryKey: ["device", deviceId, "history", limit],
    queryFn: () => api.get<CommitInfo[]>(`/devices/${deviceId}/history`, { limit }),
  });
}
