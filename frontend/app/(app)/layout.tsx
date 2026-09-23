"use client";

import { useRouter } from "next/navigation";
import * as React from "react";

import { ErrorState } from "@/components/common/error-state";
import { AppShell } from "@/components/layout/app-shell";
import { Logo } from "@/components/layout/logo";
import { Skeleton } from "@/components/ui/skeleton";
import { AuthProvider, useAuth } from "@/hooks/use-auth";
import { api, ApiError } from "@/lib/api";

function FullPageLoader() {
  return (
    <div className="flex min-h-screen">
      <div className="hidden w-[244px] flex-col gap-3 border-r bg-sidebar px-4 py-[22px] lg:flex meridian:hidden">
        <Logo className="mb-3 px-2" />
        {Array.from({ length: 10 }).map((_, i) => (
          <Skeleton key={i} className="h-8" />
        ))}
      </div>
      <div className="flex-1 px-4 py-6 sm:px-8">
        <Skeleton className="mb-6 h-[68px] w-full" />
        <Skeleton className="mb-5 h-40 w-full rounded-2xl" />
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
          {Array.from({ length: 4 }).map((_, i) => (
            <Skeleton key={i} className="h-32 rounded-xl" />
          ))}
        </div>
      </div>
    </div>
  );
}

function Gate({ children }: { children: React.ReactNode }) {
  const { me, isLoading, error } = useAuth();
  const router = useRouter();

  React.useEffect(() => {
    if (error instanceof ApiError && error.status === 401) router.replace("/login");
  }, [error, router]);

  if (isLoading || (!me && !error)) return <FullPageLoader />;
  if (error || !me) {
    return (
      <div className="flex min-h-screen items-center justify-center">
        <ErrorState error={error} onRetry={() => window.location.reload()} />
      </div>
    );
  }
  return (
    <AppShell>
      <React.Suspense fallback={<Skeleton className="h-64" />}>{children}</React.Suspense>
    </AppShell>
  );
}

function subscribeStorage(onChange: () => void) {
  window.addEventListener("storage", onChange);
  return () => window.removeEventListener("storage", onChange);
}

/** null while server rendering, then whether a session exists in this browser (kept in sync across tabs). */
function useHasSession(): boolean | null {
  return React.useSyncExternalStore(
    subscribeStorage,
    () => api.isAuthenticated(),
    () => null,
  );
}

export default function AuthenticatedLayout({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const hasSession = useHasSession();

  React.useEffect(() => {
    if (hasSession === false) {
      const next = window.location.pathname + window.location.search;
      router.replace(`/login?next=${encodeURIComponent(next)}`);
    }
  }, [hasSession, router]);

  if (!hasSession) return <FullPageLoader />;
  return (
    <AuthProvider>
      <React.Suspense fallback={<FullPageLoader />}>
        <Gate>{children}</Gate>
      </React.Suspense>
    </AuthProvider>
  );
}
