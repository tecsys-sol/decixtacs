"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { KeyRound, Plus } from "lucide-react";
import * as React from "react";

import { ConfirmDialog, useConfirm } from "@/components/common/confirm-dialog";
import { EmptyState } from "@/components/common/empty-state";
import { Field } from "@/components/common/field";
import { RelativeTime } from "@/components/common/relative-time";
import { SecretDialog } from "@/components/common/secret-dialog";
import { TableState } from "@/components/common/table-skeleton";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { useAuth } from "@/hooks/use-auth";
import { toast } from "@/hooks/use-toast";
import { useNow } from "@/hooks/use-now";
import { useOnOpen } from "@/hooks/use-reset";
import { api, errorMessage } from "@/lib/api";
import type { ApiToken, ApiTokenCreated } from "@/lib/types";
import { formatDateTime } from "@/lib/utils";

export function TokensCard() {
  const { me } = useAuth();
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["auth", "tokens"], queryFn: () => api.get<ApiToken[]>("/auth/tokens") });
  const [open, setOpen] = React.useState(false);
  const [name, setName] = React.useState("");
  const [expires, setExpires] = React.useState("");
  const [allScopes, setAllScopes] = React.useState(true);
  const [scopes, setScopes] = React.useState<string[]>([]);
  const [secret, setSecret] = React.useState<string | null>(null);
  const confirm = useConfirm<ApiToken>();
  const now = useNow();

  useOnOpen(open, () => {
    setName("");
    setExpires("");
    setAllScopes(true);
    setScopes([]);
  });

  const create = useMutation({
    mutationFn: () =>
      api.post<ApiTokenCreated>("/auth/tokens", {
        name: name.trim(),
        scopes: allScopes ? [] : scopes,
        expires_at: expires ? new Date(`${expires}T23:59:59`).toISOString() : null,
      }),
    onSuccess: (t) => {
      setOpen(false);
      setSecret(t.token);
      void qc.invalidateQueries({ queryKey: ["auth", "tokens"] });
    },
    onError: (e) => toast.error("Could not create token", errorMessage(e)),
  });
  const revoke = useMutation({
    mutationFn: (t: ApiToken) => api.delete(`/auth/tokens/${t.id}`),
    onSuccess: () => {
      toast.success("Token revoked");
      confirm.close();
      void qc.invalidateQueries({ queryKey: ["auth", "tokens"] });
    },
  });

  const list = q.data ?? [];
  const perms = me?.permissions ?? [];
  return (
    <Card>
      <CardHeader className="flex-row items-center justify-between">
        <div>
          <CardTitle>API tokens</CardTitle>
          <CardDescription>Personal tokens for automation. Scopes can only narrow your own permissions.</CardDescription>
        </div>
        <Button size="sm" onClick={() => setOpen(true)}>
          <Plus /> New token
        </Button>
      </CardHeader>
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Name</TableHead>
            <TableHead>Prefix</TableHead>
            <TableHead className="w-full">Scopes</TableHead>
            <TableHead>Last used</TableHead>
            <TableHead>Expires</TableHead>
            <TableHead />
          </TableRow>
        </TableHeader>
        <TableBody>
          <TableState cols={6} isLoading={q.isLoading} error={q.error} onRetry={() => void q.refetch()} isEmpty={list.length === 0} empty={<EmptyState icon={KeyRound} title="No API tokens" />} />
          {list.map((t) => {
            const expired = t.expires_at ? new Date(t.expires_at).getTime() < now : false;
            return (
              <TableRow key={t.id} className={t.revoked || expired ? "opacity-60" : undefined}>
                <TableCell className="whitespace-nowrap font-medium">{t.name}</TableCell>
                <TableCell className="font-mono text-xs">{t.token_prefix}…</TableCell>
                <TableCell>
                  <div className="flex flex-wrap gap-1">
                    {t.scopes.length ? t.scopes.map((s) => <Badge key={s} variant="secondary" className="font-mono">{s}</Badge>) : <span className="text-xs text-muted-foreground">all of your permissions</span>}
                  </div>
                </TableCell>
                <TableCell className="whitespace-nowrap text-xs">
                  <RelativeTime value={t.last_used_at} />
                </TableCell>
                <TableCell className="whitespace-nowrap text-xs">{t.expires_at ? formatDateTime(t.expires_at) : "never"}</TableCell>
                <TableCell>
                  {t.revoked ? (
                    <Badge variant="muted">Revoked</Badge>
                  ) : expired ? (
                    <Badge variant="muted">Expired</Badge>
                  ) : (
                    <Button size="xs" variant="outline" onClick={() => confirm.ask(t)}>
                      Revoke
                    </Button>
                  )}
                </TableCell>
              </TableRow>
            );
          })}
        </TableBody>
      </Table>
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="max-w-xl">
          <DialogHeader>
            <DialogTitle>Create API token</DialogTitle>
            <DialogDescription>Use it as a Bearer token. It is shown only once.</DialogDescription>
          </DialogHeader>
          <form
            className="grid gap-3"
            onSubmit={(e) => {
              e.preventDefault();
              create.mutate();
            }}
          >
            <div className="grid gap-3 sm:grid-cols-[1fr_180px]">
              <Field label="Name" htmlFor="tname" required>
                <Input id="tname" value={name} onChange={(e) => setName(e.target.value)} placeholder="ansible-ci" />
              </Field>
              <Field label="Expires" htmlFor="texp" hint="Optional">
                <Input id="texp" type="date" value={expires} min={new Date().toISOString().slice(0, 10)} onChange={(e) => setExpires(e.target.value)} />
              </Field>
            </div>
            <Checkbox label="Grant all of my permissions" checked={allScopes} onCheckedChange={setAllScopes} />
            {allScopes ? null : (
              <div className="grid max-h-56 gap-1 overflow-y-auto rounded-md border p-2 sm:grid-cols-2">
                {perms.map((p) => (
                  <Checkbox
                    key={p}
                    label={<code className="font-mono text-xs">{p}</code>}
                    checked={scopes.includes(p)}
                    onCheckedChange={(c) => setScopes((s) => (c ? [...s, p] : s.filter((x) => x !== p)))}
                  />
                ))}
              </div>
            )}
            <DialogFooter>
              <Button type="button" variant="outline" onClick={() => setOpen(false)}>
                Cancel
              </Button>
              <Button type="submit" loading={create.isPending} disabled={!name.trim() || (!allScopes && scopes.length === 0)}>
                Create token
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
      <SecretDialog secret={secret} title="New API token" description="Send it as 'Authorization: Bearer <token>'." onClose={() => setSecret(null)} />
      <ConfirmDialog open={confirm.open} onOpenChange={confirm.onOpenChange} title={`Revoke ${confirm.target?.name ?? ""}?`} description="Automation using this token stops working immediately." destructive confirmLabel="Revoke" loading={revoke.isPending} onConfirm={() => confirm.target && revoke.mutate(confirm.target)} />
    </Card>
  );
}
