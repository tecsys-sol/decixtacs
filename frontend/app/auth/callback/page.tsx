"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Loader2 } from "lucide-react";
import * as React from "react";

import { Card } from "@/components/ui/card";
import { api, errorMessage } from "@/lib/api";
import type { TokenOut } from "@/lib/types";

function Callback() {
  const params = useSearchParams();
  const router = useRouter();
  const [exchangeError, setExchangeError] = React.useState<string | null>(null);
  const done = React.useRef(false);
  const code = params.get("code");
  const state = params.get("state");
  const idpError = params.get("error_description") || params.get("error");
  const error = idpError || (!code || !state ? "Missing authorisation code." : exchangeError);

  React.useEffect(() => {
    if (done.current || idpError || !code || !state) return;
    done.current = true;
    api
      .get<TokenOut>("/auth/oidc/callback", { code, state }, { auth: false })
      .then((t) => {
        api.setSession(t);
        router.replace("/dashboard");
      })
      .catch((e) => setExchangeError(errorMessage(e)));
  }, [code, state, idpError, router]);

  return (
    <Card className="w-full max-w-sm p-6 text-center">
      {error ? (
        <>
          <p className="text-sm font-medium text-destructive">Single sign-on failed</p>
          <p className="mt-1 text-xs text-muted-foreground">{error}</p>
          <Link href="/login" className="mt-4 inline-block text-sm text-primary hover:underline">
            Back to sign in
          </Link>
        </>
      ) : (
        <p className="flex items-center justify-center gap-2 text-sm text-muted-foreground">
          <Loader2 className="h-4 w-4 animate-spin" /> Completing sign-in…
        </p>
      )}
    </Card>
  );
}

export default function OidcCallbackPage() {
  return (
    <div className="flex min-h-screen items-center justify-center px-4">
      <React.Suspense>
        <Callback />
      </React.Suspense>
    </div>
  );
}
