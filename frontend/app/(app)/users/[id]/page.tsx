"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useParams, useRouter } from "next/navigation";
import { KeyRound, LockOpen, ShieldOff, Trash2 } from "lucide-react";
import * as React from "react";

import { ConfirmDialog } from "@/components/common/confirm-dialog";
import { ErrorState } from "@/components/common/error-state";
import { Field, KeyValue } from "@/components/common/field";
import { PageHeader } from "@/components/common/page-header";
import { RelativeTime } from "@/components/common/relative-time";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { useAuth } from "@/hooks/use-auth";
import { useGroups } from "@/hooks/use-lookups";
import { useNow } from "@/hooks/use-now";
import { useOnChange } from "@/hooks/use-reset";
import { toast } from "@/hooks/use-toast";
import { api, errorMessage } from "@/lib/api";
import type { User, UserPatch } from "@/lib/types";
import { formatDateTime } from "@/lib/utils";

export default function UserDetailPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const qc = useQueryClient();
  const { can, me } = useAuth();
  const groups = useGroups();
  const writable = can("users:write");
  const q = useQuery({ queryKey: ["users", "detail", id], queryFn: () => api.get<User>(`/users/${id}`) });
  const [form, setForm] = React.useState({ email: "", full_name: "", is_active: true, group_ids: [] as string[] });
  const [password, setPassword] = React.useState("");
  const [confirmDelete, setConfirmDelete] = React.useState(false);

  useOnChange(q.data, (u) => {
    if (u) setForm({ email: u.email ?? "", full_name: u.full_name ?? "", is_active: u.is_active, group_ids: u.groups.map((g) => g.id) });
  });
  const now = useNow();

  const patch = useMutation({
    mutationFn: (body: UserPatch) => api.patch<User>(`/users/${id}`, body),
    onSuccess: (u) => {
      qc.setQueryData(["users", "detail", id], u);
      void qc.invalidateQueries({ queryKey: ["users"] });
    },
    onError: (e) => toast.error("Update failed", errorMessage(e)),
  });
  const del = useMutation({
    mutationFn: () => api.delete(`/users/${id}`),
    onSuccess: () => {
      toast.success("User deleted");
      void qc.invalidateQueries({ queryKey: ["users"] });
      router.replace("/users");
    },
  });

  if (q.isLoading) return <Skeleton className="h-96" />;
  if (q.error || !q.data) return <ErrorState error={q.error} onRetry={() => void q.refetch()} />;
  const u = q.data;
  const locked = u.locked_until ? new Date(u.locked_until).getTime() > now : false;

  return (
    <>
      <PageHeader
        breadcrumbs={[{ label: "Users", href: "/users" }, { label: u.username }]}
        title={
          <span className="flex items-center gap-2">
            {u.username}
            {u.is_superuser ? <Badge variant="warning">superuser</Badge> : null}
            {locked ? <Badge variant="danger">locked</Badge> : null}
          </span>
        }
        description={u.full_name ?? undefined}
        actions={
          writable && me?.id !== u.id ? (
            <Button variant="outline" onClick={() => setConfirmDelete(true)}>
              <Trash2 /> Delete
            </Button>
          ) : null
        }
      />
      <div className="grid gap-4 lg:grid-cols-3">
        <Card className="lg:col-span-2">
          <CardHeader>
            <CardTitle>Profile</CardTitle>
          </CardHeader>
          <CardContent>
            <form
              className="grid gap-3"
              onSubmit={(e) => {
                e.preventDefault();
                patch.mutate(
                  { email: form.email.trim() || null, full_name: form.full_name.trim() || null, is_active: form.is_active, group_ids: form.group_ids },
                  { onSuccess: () => toast.success("User updated") },
                );
              }}
            >
              <div className="grid gap-3 sm:grid-cols-2">
                <Field label="Full name" htmlFor="full">
                  <Input id="full" value={form.full_name} onChange={(e) => setForm({ ...form, full_name: e.target.value })} disabled={!writable} />
                </Field>
                <Field label="Email" htmlFor="email">
                  <Input id="email" type="email" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} disabled={!writable} />
                </Field>
              </div>
              <Field label="Groups">
                <div className="flex flex-wrap gap-x-4 gap-y-2 rounded-md border p-2">
                  {(groups.data ?? []).map((g) => (
                    <Checkbox
                      key={g.id}
                      label={g.name}
                      disabled={!writable}
                      checked={form.group_ids.includes(g.id)}
                      onCheckedChange={(c) => setForm({ ...form, group_ids: c ? [...form.group_ids, g.id] : form.group_ids.filter((x) => x !== g.id) })}
                    />
                  ))}
                </div>
              </Field>
              <Checkbox label="Active" checked={form.is_active} disabled={!writable || me?.id === u.id} onCheckedChange={(c) => setForm({ ...form, is_active: c })} />
              {writable ? (
                <div>
                  <Button type="submit" loading={patch.isPending}>
                    Save changes
                  </Button>
                </div>
              ) : null}
            </form>
          </CardContent>
        </Card>
        <div className="grid content-start gap-4">
          <Card>
            <CardHeader>
              <CardTitle>Account</CardTitle>
            </CardHeader>
            <CardContent>
              <KeyValue
                items={[
                  ["Source", <Badge key="s" variant="outline">{u.auth_source}</Badge>],
                  ["MFA", u.mfa_enabled ? <Badge key="m" variant="success">Enabled</Badge> : <Badge key="m" variant="muted">Disabled</Badge>],
                  ["Last login", <RelativeTime key="l" value={u.last_login_at} />],
                  ["Locked until", u.locked_until ? formatDateTime(u.locked_until) : null],
                  ["Created", formatDateTime(u.created_at)],
                ]}
              />
            </CardContent>
          </Card>
          {writable ? (
            <Card>
              <CardHeader>
                <CardTitle>Security actions</CardTitle>
                <CardDescription>All actions are recorded in the audit log.</CardDescription>
              </CardHeader>
              <CardContent className="grid gap-3">
                {u.auth_source === "local" ? (
                  <form
                    className="grid gap-2"
                    onSubmit={(e) => {
                      e.preventDefault();
                      patch.mutate({ password }, { onSuccess: () => { setPassword(""); toast.success("Password reset"); } });
                    }}
                  >
                    <Field label="New password" htmlFor="npw">
                      <Input id="npw" type="password" autoComplete="new-password" value={password} onChange={(e) => setPassword(e.target.value)} />
                    </Field>
                    <Button type="submit" variant="outline" size="sm" disabled={!password} loading={patch.isPending && !!password}>
                      <KeyRound /> Reset password
                    </Button>
                  </form>
                ) : null}
                <Button variant="outline" size="sm" disabled={!u.mfa_enabled} onClick={() => patch.mutate({ reset_mfa: true }, { onSuccess: () => toast.success("MFA reset", "The user must enrol again.") })}>
                  <ShieldOff /> Reset MFA
                </Button>
                <Button variant="outline" size="sm" disabled={!locked} onClick={() => patch.mutate({ unlock: true }, { onSuccess: () => toast.success("Account unlocked") })}>
                  <LockOpen /> Unlock account
                </Button>
              </CardContent>
            </Card>
          ) : null}
        </div>
      </div>
      <ConfirmDialog
        open={confirmDelete}
        onOpenChange={setConfirmDelete}
        title={`Delete ${u.username}?`}
        description="The user loses portal access immediately. TACACS+ mappings are removed on the next deploy."
        destructive
        confirmLabel="Delete user"
        loading={del.isPending}
        onConfirm={() => del.mutate()}
      />
    </>
  );
}
