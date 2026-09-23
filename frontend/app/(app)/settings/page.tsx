"use client";

import { KeyValue } from "@/components/common/field";
import { PageHeader } from "@/components/common/page-header";
import { MfaCard } from "@/components/settings/mfa-card";
import { PasswordCard } from "@/components/settings/password-card";
import { TokensCard } from "@/components/settings/tokens-card";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { useAuth } from "@/hooks/use-auth";

export default function SettingsPage() {
  const { me } = useAuth();
  return (
    <>
      <PageHeader title="Account settings" description="Your profile, sign-in security and API access." />
      <div className="grid gap-4 lg:grid-cols-3">
        <Card>
          <CardHeader>
            <CardTitle>Profile</CardTitle>
          </CardHeader>
          <CardContent>
            {me ? (
              <KeyValue
                items={[
                  ["Username", me.username],
                  ["Name", me.full_name],
                  ["Email", me.email],
                  ["Sign-in", <Badge key="a" variant="outline">{me.auth_source}</Badge>],
                  ["Groups", me.groups.length ? me.groups.join(", ") : null],
                  ["Permissions", <span key="p" className="text-xs text-muted-foreground">{me.is_superuser ? "all (superuser)" : `${me.permissions.length} granted`}</span>],
                ]}
              />
            ) : null}
          </CardContent>
        </Card>
        <div className="grid min-w-0 gap-4 lg:col-span-2">
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
