"use client";

import { useQuery } from "@tanstack/react-query";

import { useAuth } from "@/hooks/use-auth";
import { api } from "@/lib/api";
import type {
  Credential,
  Device,
  DeviceGroup,
  Group,
  Page,
  Platform,
  Role,
  Site,
  User,
  Vendor,
} from "@/lib/types";

const LOOKUP_STALE = 5 * 60_000;

export function useSites() {
  return useQuery({ queryKey: ["sites"], queryFn: () => api.get<Site[]>("/sites"), staleTime: LOOKUP_STALE });
}

export function usePlatforms() {
  return useQuery({ queryKey: ["platforms"], queryFn: () => api.get<Platform[]>("/platforms"), staleTime: LOOKUP_STALE });
}

export function useVendors() {
  return useQuery({ queryKey: ["vendors"], queryFn: () => api.get<Vendor[]>("/vendors"), staleTime: LOOKUP_STALE });
}

export function useCredentials() {
  return useQuery({ queryKey: ["credentials"], queryFn: () => api.get<Credential[]>("/credentials"), staleTime: LOOKUP_STALE });
}

export function useDeviceGroups() {
  return useQuery({
    queryKey: ["device-groups"],
    queryFn: () => api.get<DeviceGroup[]>("/device-groups"),
    staleTime: LOOKUP_STALE,
  });
}

export function useGroups() {
  const { can } = useAuth();
  return useQuery({
    queryKey: ["groups"],
    queryFn: () => api.get<Group[]>("/groups"),
    staleTime: LOOKUP_STALE,
    enabled: can("users:read"),
  });
}

export function useRoles() {
  const { can } = useAuth();
  return useQuery({ queryKey: ["roles"], queryFn: () => api.get<Role[]>("/roles"), staleTime: LOOKUP_STALE, enabled: can("users:read") });
}

/** All users (for pickers / id -> name resolution). */
export function useAllUsers() {
  const { can } = useAuth();
  return useQuery({
    queryKey: ["users", "all"],
    queryFn: () => api.get<Page<User>>("/users", { limit: 500 }).then((p) => p.items),
    staleTime: LOOKUP_STALE,
    enabled: can("users:read"),
  });
}

/** Device id -> hostname map for tables that only carry ids. */
export function useDeviceNames() {
  const q = useQuery({
    queryKey: ["devices", "names"],
    queryFn: () => api.get<Page<Device>>("/devices", { limit: 500 }).then((p) => p.items),
    staleTime: LOOKUP_STALE,
  });
  const map = new Map<string, string>();
  for (const d of q.data ?? []) map.set(d.id, d.hostname);
  return { ...q, map };
}
