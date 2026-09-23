"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import QRCode from "qrcode";
import { ShieldCheck, Smartphone } from "lucide-react";
import * as React from "react";

import { Field } from "@/components/common/field";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { useAuth } from "@/hooks/use-auth";
import { toast } from "@/hooks/use-toast";
import { api, errorMessage } from "@/lib/api";
import type { MfaSetupOut } from "@/lib/types";

export function MfaCard() {
  const { me } = useAuth();
  const qc = useQueryClient();
  const [setup, setSetup] = React.useState<MfaSetupOut | null>(null);
  const [rendered, setRendered] = React.useState<{ uri: string; dataUrl: string } | null>(null);
  const [otp, setOtp] = React.useState("");
  const qr = setup && rendered?.uri === setup.otpauth_uri ? rendered.dataUrl : null;

  React.useEffect(() => {
    if (!setup) return;
    let cancelled = false;
    const uri = setup.otpauth_uri;
    QRCode.toDataURL(uri, { margin: 1, width: 200, errorCorrectionLevel: "M" })
      .then((dataUrl) => {
        if (!cancelled) setRendered({ uri, dataUrl });
      })
      .catch(() => {
        /* the secret is shown as text as a fallback */
      });
    return () => {
      cancelled = true;
    };
  }, [setup]);

  const start = useMutation({
    mutationFn: () => api.post<MfaSetupOut>("/auth/mfa/setup"),
    onSuccess: (s) => {
      setSetup(s);
      setOtp("");
    },
    onError: (e) => toast.error("Could not start MFA enrolment", errorMessage(e)),
  });
  const verify = useMutation({
    mutationFn: () => api.post("/auth/mfa/verify", { otp }),
    onSuccess: () => {
      toast.success("Two-factor authentication enabled");
      setSetup(null);
      void qc.invalidateQueries({ queryKey: ["auth", "me"] });
    },
    onError: (e) => toast.error("Verification failed", errorMessage(e)),
  });

  if (me?.auth_source && me.auth_source !== "local") {
    return (
      <Card>
        <CardHeader>
          <CardTitle>Two-factor authentication</CardTitle>
          <CardDescription>Your account authenticates via {me.auth_source.toUpperCase()}; MFA is enforced by your identity provider.</CardDescription>
        </CardHeader>
      </Card>
    );
  }

  return (
    <Card>
      <CardHeader className="flex-row items-start justify-between">
        <div>
          <CardTitle>Two-factor authentication</CardTitle>
          <CardDescription>Time-based one-time passwords (TOTP) from an authenticator app.</CardDescription>
        </div>
        {me?.mfa_enabled ? (
          <Badge variant="success">
            <ShieldCheck /> Enabled
          </Badge>
        ) : (
          <Badge variant="warning">Disabled</Badge>
        )}
      </CardHeader>
      <CardContent className="grid gap-4">
        {setup ? (
          <div className="grid gap-4 sm:grid-cols-[200px_1fr]">
            <div className="flex h-[200px] w-[200px] items-center justify-center rounded-lg border bg-white p-1">
              {qr ? (
                // eslint-disable-next-line @next/next/no-img-element
                <img src={qr} alt="QR code for your authenticator app" width={200} height={200} />
              ) : (
                <span className="text-xs text-neutral-500">Generating…</span>
              )}
            </div>
            <form
              className="grid content-start gap-3"
              onSubmit={(e) => {
                e.preventDefault();
                verify.mutate();
              }}
            >
              <p className="text-sm">
                Scan the QR code with your authenticator app, or enter the secret manually:
              </p>
              <code className="break-all rounded-md border bg-muted/40 px-2 py-1 font-mono text-xs">{setup.secret}</code>
              <Field label="6-digit code" htmlFor="mfa-otp">
                <Input
                  id="mfa-otp"
                  inputMode="numeric"
                  autoComplete="one-time-code"
                  maxLength={8}
                  value={otp}
                  onChange={(e) => setOtp(e.target.value.replace(/\D/g, ""))}
                  className="w-40 text-center font-mono tracking-[0.3em]"
                />
              </Field>
              <div className="flex gap-2">
                <Button type="submit" loading={verify.isPending} disabled={otp.length < 6}>
                  Verify & enable
                </Button>
                <Button type="button" variant="ghost" onClick={() => setSetup(null)}>
                  Cancel
                </Button>
              </div>
            </form>
          </div>
        ) : (
          <div>
            <Button variant={me?.mfa_enabled ? "outline" : "default"} onClick={() => start.mutate()} loading={start.isPending}>
              <Smartphone /> {me?.mfa_enabled ? "Re-enrol authenticator" : "Set up authenticator"}
            </Button>
            {me?.mfa_enabled ? (
              <p className="mt-2 text-xs text-muted-foreground">Re-enrolling disables MFA until the new authenticator is verified.</p>
            ) : null}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
