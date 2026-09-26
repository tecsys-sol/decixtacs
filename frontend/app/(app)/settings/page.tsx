"use client";

import { PageHeader } from "@/components/common/page-header";
import { AppearanceCard } from "@/components/settings/appearance-card";
import { MfaCard } from "@/components/settings/mfa-card";
import { PasswordCard } from "@/components/settings/password-card";
import { ProfileCard } from "@/components/settings/profile-card";
import { TokensCard } from "@/components/settings/tokens-card";

export default function SettingsPage() {
  return (
    <>
      <PageHeader title="Account settings" description="Your profile, appearance, sign-in security and API access." />
      <div className="grid gap-4 lg:grid-cols-3">
        <ProfileCard />
        <div className="grid min-w-0 gap-4 lg:col-span-2">
          <AppearanceCard />
          <MfaCard />
          <PasswordCard />
        </div>
        <div className="min-w-0 lg:col-span-3">
          <TokensCard />
        </div>
      </div>
    </>
  );
}
