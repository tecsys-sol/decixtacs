"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import * as React from "react";

import { api, ApiError, onSessionExpired, tenantStorage } from "@/lib/api";
import type { Me } from "@/lib/types";

interface AuthContextValue {
  me: Me | undefined;
  isLoading: boolean;
  error: unknown;
  /** true if the user holds the permission (superusers hold everything) */
  can: (permission: string | undefined | null) => boolean;
  tenant: string | null;
  switchTenant: (slug: string | null) => void;
  logout: () => Promise<void>;
}

const AuthContext = React.createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const qc = useQueryClient();
  // AuthProvider only renders client-side (after the session check), so storage is available.
  const [tenant, setTenant] = React.useState<string | null>(() => tenantStorage.get());

  const meQuery = useQuery({
    queryKey: ["auth", "me"],
    queryFn: () => api.get<Me>("/auth/me"),
    staleTime: 5 * 60_000,
    retry: (count, err) => !(err instanceof ApiError && (err.status === 401 || err.status === 403)) && count < 2,
  });

  React.useEffect(
    () =>
      onSessionExpired(() => {
        qc.clear();
        const next = typeof window !== "undefined" ? window.location.pathname + window.location.search : "/";
        router.replace(`/login?next=${encodeURIComponent(next)}&expired=1`);
      }),
    [qc, router],
  );

  const me = meQuery.data;
  const permissions = React.useMemo(() => new Set(me?.permissions ?? []), [me]);

  const can = React.useCallback(
    (p: string | undefined | null) => {
      if (!p) return true;
      if (!me) return false;
      return me.is_superuser || permissions.has(p);
    },
    [me, permissions],
  );

  const switchTenant = React.useCallback(
    (slug: string | null) => {
      tenantStorage.set(slug);
      setTenant(slug);
      // Every cached response belongs to the previous tenant.
      qc.removeQueries({ predicate: (q) => !(q.queryKey[0] === "auth" || q.queryKey[0] === "tenants") });
      void qc.invalidateQueries();
    },
    [qc],
  );

  const logout = React.useCallback(async () => {
    await api.logout();
    tenantStorage.set(null);
    qc.clear();
    router.replace("/login");
  }, [qc, router]);

  const value = React.useMemo<AuthContextValue>(
    () => ({ me, isLoading: meQuery.isLoading, error: meQuery.error, can, tenant, switchTenant, logout }),
    [me, meQuery.isLoading, meQuery.error, can, tenant, switchTenant, logout],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const ctx = React.useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside <AuthProvider>");
  return ctx;
}

export function useCan(permission: string | undefined | null): boolean {
  return useAuth().can(permission);
}
