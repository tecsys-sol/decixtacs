import type { Metadata } from "next";
import { Suspense } from "react";

import { HeroNetwork } from "@/components/illustrations";
import { AppFooter } from "@/components/layout/app-footer";

import { LoginForm } from "./login-form";

export const metadata: Metadata = { title: "Sign in" };

export default function LoginPage() {
  return (
    <div className="flex min-h-screen flex-col bg-background">
      <div className="flex flex-1 items-center justify-center px-4 py-10">
        <div className="grid w-full max-w-[980px] overflow-hidden rounded-2xl border bg-card lg:grid-cols-[1fr_1.1fr]">
          <div className="flex items-center justify-center p-6 sm:p-10">
            <Suspense>
              <LoginForm />
            </Suspense>
          </div>
          <div
            className="relative hidden flex-col justify-between gap-6 bg-[var(--ill-softer)] p-10 lg:flex"
            aria-hidden
          >
            <div className="flex flex-col gap-2">
              <span className="inline-flex items-center gap-2 text-[12.5px] font-bold text-success">
                <span className="live h-2 w-2 rounded-full bg-[var(--ill-green)]" />
                Configuration, access and peering in one place
              </span>
              <p className="max-w-sm font-display text-2xl font-bold leading-snug tracking-[-0.02em] text-foreground">
                Back up every config, review every change, account for every
                command.
              </p>
            </div>
            <HeroNetwork className="h-[190px] w-full" />
          </div>
        </div>
      </div>
      <AppFooter className="border-t-0" />
    </div>
  );
}
