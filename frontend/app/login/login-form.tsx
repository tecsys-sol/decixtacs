"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { ArrowLeft, KeyRound, LogIn, ShieldCheck } from "lucide-react";
import * as React from "react";

import { Field } from "@/components/common/field";
import { Logo } from "@/components/layout/logo";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { api, ApiError, errorMessage } from "@/lib/api";

function safeNext(next: string | null): string {
  // Only allow same-origin relative paths to avoid open redirects.
  if (!next || !next.startsWith("/") || next.startsWith("//") || next.startsWith("/login")) return "/dashboard";
  return next;
}

export function LoginForm() {
  const router = useRouter();
  const params = useSearchParams();
  const next = safeNext(params.get("next"));
  const [username, setUsername] = React.useState("");
  const [password, setPassword] = React.useState("");
  const [tenant, setTenant] = React.useState("");
  const [showTenant, setShowTenant] = React.useState(false);
  const [otp, setOtp] = React.useState("");
  const [mfa, setMfa] = React.useState(false);
  const [error, setError] = React.useState<string | null>(params.get("expired") ? "Your session has expired. Please sign in again." : null);
  const [loading, setLoading] = React.useState(false);
  const [ssoLoading, setSsoLoading] = React.useState(false);
  const otpRef = React.useRef<HTMLInputElement>(null);

  React.useEffect(() => {
    if (api.isAuthenticated()) router.replace(next);
  }, [router, next]);

  React.useEffect(() => {
    if (mfa) otpRef.current?.focus();
  }, [mfa]);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setLoading(true);
    try {
      await api.login({
        username: username.trim(),
        password,
        tenant: tenant.trim() || null,
        otp: mfa ? otp.trim() : null,
      });
      router.replace(next);
    } catch (err) {
      if (err instanceof ApiError && err.code === "mfa_required") {
        setMfa(true);
        setError(null);
      } else {
        setError(errorMessage(err));
        if (mfa) setOtp("");
      }
    } finally {
      setLoading(false);
    }
  }

  async function sso() {
    setSsoLoading(true);
    setError(null);
    try {
      const r = await api.get<{ authorization_url: string }>("/auth/oidc/authorize", { tenant: tenant.trim() || null }, { auth: false });
      window.location.assign(r.authorization_url);
    } catch (err) {
      setError(err instanceof ApiError && err.status === 404 ? "Single sign-on is not enabled." : errorMessage(err));
      setSsoLoading(false);
    }
  }

  return (
    <div className="rise relative w-full max-w-sm">
      <Logo className="mb-8" subtitle="Network access & configuration" />
      <h1 className="font-display text-2xl font-bold tracking-[-0.02em]">{mfa ? "Two-factor authentication" : "Sign in"}</h1>
      <p className="mb-6 mt-1 text-sm text-ink-3">
        {mfa ? "Enter the 6-digit code from your authenticator app." : "Network access & configuration management"}
      </p>
      <form onSubmit={submit} className="grid gap-4" noValidate>
        {mfa ? (
          <Field label="One-time password" htmlFor="otp">
            <Input
              id="otp"
              ref={otpRef}
              inputMode="numeric"
              autoComplete="one-time-code"
              pattern="[0-9]*"
              maxLength={8}
              value={otp}
              onChange={(e) => setOtp(e.target.value.replace(/\D/g, ""))}
              className="text-center font-mono text-lg tracking-[0.5em]"
              placeholder="000000"
              required
            />
          </Field>
        ) : (
          <>
            <Field label="Username" htmlFor="username">
              <Input
                id="username"
                autoComplete="username"
                autoFocus
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                required
              />
            </Field>
            <Field label="Password" htmlFor="password">
              <Input
                id="password"
                type="password"
                autoComplete="current-password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
              />
            </Field>
            {showTenant ? (
              <Field label="Organisation" htmlFor="tenant" hint="Tenant slug; leave empty for the default organisation.">
                <Input id="tenant" value={tenant} onChange={(e) => setTenant(e.target.value)} autoComplete="organization" />
              </Field>
            ) : (
              <button
                type="button"
                className="-mt-2 justify-self-start rounded-sm text-xs font-semibold text-accent-foreground hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                onClick={() => setShowTenant(true)}
              >
                Sign in to a specific organisation
              </button>
            )}
          </>
        )}
        {error ? (
          <p role="alert" className="rounded-md border border-danger/20 bg-danger-soft px-3 py-2 text-xs font-semibold text-danger">
            {error}
          </p>
        ) : null}
        <Button
          type="submit"
          loading={loading}
          disabled={mfa ? otp.length < 6 : !username || !password}
          className="w-full"
        >
          {mfa ? <ShieldCheck /> : <LogIn />} {mfa ? "Verify" : "Sign in"}
        </Button>
        {mfa ? (
          <Button
            type="button"
            variant="ghost"
            size="sm"
            onClick={() => {
              setMfa(false);
              setOtp("");
            }}
          >
            <ArrowLeft /> Back
          </Button>
        ) : (
          <>
            <div className="flex items-center gap-2 text-[11px] font-bold uppercase tracking-[0.08em] text-label">
              <span className="h-px flex-1 bg-border" /> or <span className="h-px flex-1 bg-border" />
            </div>
            <Button type="button" variant="outline" onClick={sso} loading={ssoLoading}>
              <KeyRound /> Single sign-on
            </Button>
          </>
        )}
      </form>
    </div>
  );
}
