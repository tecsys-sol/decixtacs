"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { KeyRound, Plus, Trash2, UserCog } from "lucide-react";
import * as React from "react";

import { ConfirmDialog, useConfirm } from "@/components/common/confirm-dialog";
import { EmptyState } from "@/components/common/empty-state";
import { Field } from "@/components/common/field";
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
import { SimpleSelect } from "@/components/ui/select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { useAuth } from "@/hooks/use-auth";
import { useAllUsers } from "@/hooks/use-lookups";
import { toast } from "@/hooks/use-toast";
import { useNow } from "@/hooks/use-now";
import { useOnOpen } from "@/hooks/use-reset";
import { api, errorMessage } from "@/lib/api";
import type { TacacsMapping, TacacsMappingIn } from "@/lib/types";
import { formatDateTime, isoToLocalInput, localInputToIso } from "@/lib/utils";

/**
 * Create a mapping, or (with `replace`) set a new password: the API has no update endpoint, so the
 * mapping is re-created with the same attributes and the new password.
 */
function MappingDialog({
  open,
  onOpenChange,
  replace,
}: {
  open: boolean;
  onOpenChange: (o: boolean) => void;
  replace?: TacacsMapping;
}) {
  const qc = useQueryClient();
  const users = useAllUsers();
  const [f, setF] = React.useState<TacacsMappingIn & { valid_local: string }>({ user_id: "", auth_method: "crypt", enabled: true, valid_local: "" });
  const [password, setPassword] = React.useState("");
  const [confirmPw, setConfirmPw] = React.useState("");

  useOnOpen(open, () => {
    setF({
      user_id: replace?.user_id ?? "",
      tacacs_username: replace?.tacacs_username ?? "",
      auth_method: replace?.auth_method ?? "crypt",
      enabled: replace?.enabled ?? true,
      valid_local: isoToLocalInput(replace?.valid_until),
    });
    setPassword("");
    setConfirmPw("");
  });

  const save = useMutation({
    mutationFn: async () => {
      const body: TacacsMappingIn = {
        user_id: f.user_id,
        tacacs_username: f.tacacs_username?.trim() || null,
        auth_method: f.auth_method,
        enabled: f.enabled,
        valid_until: localInputToIso(f.valid_local) ?? null,
        password: f.auth_method === "crypt" && password ? password : null,
      };
      if (replace) await api.delete(`/tacacs/users/${replace.id}`);
      return api.post<TacacsMapping>("/tacacs/users", body);
    },
    onSuccess: () => {
      toast.success(replace ? "Password updated" : "TACACS+ user mapped", "Deploy the TACACS+ configuration to apply it.");
      void qc.invalidateQueries({ queryKey: ["tacacs", "users"] });
      onOpenChange(false);
    },
    onError: (e) => {
      void qc.invalidateQueries({ queryKey: ["tacacs", "users"] });
      toast.error("Could not save mapping", errorMessage(e));
    },
  });

  const pwMismatch = password !== confirmPw;
  const needsPw = !!replace;
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{replace ? `Set password · ${replace.tacacs_username}` : "Map user to TACACS+"}</DialogTitle>
          <DialogDescription>
            {replace
              ? "The mapping is re-created with the new device password."
              : "Grants a platform user a TACACS+ identity. Access is governed by the policies of the user's groups."}
          </DialogDescription>
        </DialogHeader>
        <form
          className="grid gap-3"
          onSubmit={(e) => {
            e.preventDefault();
            if (!pwMismatch) save.mutate();
          }}
        >
          {replace ? null : (
            <>
              <Field label="Platform user" htmlFor="muser" required>
                <SimpleSelect
                  id="muser"
                  value={f.user_id}
                  onValueChange={(v) => setF({ ...f, user_id: v })}
                  placeholder="Select user"
                  options={(users.data ?? []).map((u) => ({ value: u.id, label: `${u.username}${u.full_name ? ` · ${u.full_name}` : ""}` }))}
                />
              </Field>
              <div className="grid gap-3 sm:grid-cols-2">
                <Field label="TACACS+ username" htmlFor="mname" hint="Defaults to the platform username">
                  <Input id="mname" value={f.tacacs_username ?? ""} onChange={(e) => setF({ ...f, tacacs_username: e.target.value })} className="font-mono" />
                </Field>
                <Field label="Authentication" htmlFor="mauth">
                  <SimpleSelect id="mauth" value={f.auth_method ?? "crypt"} onValueChange={(v) => setF({ ...f, auth_method: v })} options={[{ value: "crypt", label: "Local password (crypt)" }, { value: "ldap", label: "LDAP" }]} />
                </Field>
              </div>
              <Field label="Valid until" htmlFor="mvalid" hint="Optional expiry for temporary access">
                <Input id="mvalid" type="datetime-local" value={f.valid_local} onChange={(e) => setF({ ...f, valid_local: e.target.value })} />
              </Field>
            </>
          )}
          {f.auth_method === "crypt" ? (
            <div className="grid gap-3 sm:grid-cols-2">
              <Field label="Device password" htmlFor="mpw" required={needsPw}>
                <Input id="mpw" type="password" autoComplete="new-password" value={password} onChange={(e) => setPassword(e.target.value)} />
              </Field>
              <Field label="Confirm password" htmlFor="mpw2" error={confirmPw && pwMismatch ? "Passwords do not match" : null}>
                <Input id="mpw2" type="password" autoComplete="new-password" value={confirmPw} onChange={(e) => setConfirmPw(e.target.value)} />
              </Field>
            </div>
          ) : null}
          {replace ? null : <Checkbox label="Enabled" checked={f.enabled ?? true} onCheckedChange={(c) => setF({ ...f, enabled: c })} />}
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
              Cancel
            </Button>
            <Button type="submit" loading={save.isPending} disabled={!f.user_id || pwMismatch || (needsPw && !password)}>
              {replace ? "Set password" : "Create mapping"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

export function UsersTab() {
  const { can } = useAuth();
  const qc = useQueryClient();
  const users = useAllUsers();
  const q = useQuery({ queryKey: ["tacacs", "users"], queryFn: () => api.get<TacacsMapping[]>("/tacacs/users") });
  const [createOpen, setCreateOpen] = React.useState(false);
  const [pwFor, setPwFor] = React.useState<TacacsMapping | undefined>();
  const confirm = useConfirm<TacacsMapping>();
  const now = useNow();
  const writable = can("tacacs:write");

  const del = useMutation({
    mutationFn: (m: TacacsMapping) => api.delete(`/tacacs/users/${m.id}`),
    onSuccess: () => {
      toast.success("Mapping removed");
      confirm.close();
      void qc.invalidateQueries({ queryKey: ["tacacs", "users"] });
    },
  });

  const uName = new Map((users.data ?? []).map((u) => [u.id, u.username]));
  const list = q.data ?? [];
  return (
    <Card>
      <CardHeader className="flex-row items-center justify-between">
        <div>
          <CardTitle>TACACS+ users</CardTitle>
          <CardDescription>Platform users mapped to device login identities</CardDescription>
        </div>
        {writable ? (
          <Button size="sm" onClick={() => setCreateOpen(true)}>
            <Plus /> Map user
          </Button>
        ) : null}
      </CardHeader>
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>TACACS+ username</TableHead>
            <TableHead>Platform user</TableHead>
            <TableHead>Auth</TableHead>
            <TableHead>Password</TableHead>
            <TableHead>Valid until</TableHead>
            <TableHead>State</TableHead>
            <TableHead />
          </TableRow>
        </TableHeader>
        <TableBody>
          <TableState cols={7} isLoading={q.isLoading} error={q.error} onRetry={() => void q.refetch()} isEmpty={list.length === 0} empty={<EmptyState icon={UserCog} title="No TACACS+ users" />} />
          {list.map((m) => {
            const expired = m.valid_until ? new Date(m.valid_until).getTime() < now : false;
            return (
              <TableRow key={m.id}>
                <TableCell className="font-mono text-xs font-medium">{m.tacacs_username}</TableCell>
                <TableCell>{uName.get(m.user_id) ?? m.user_id.slice(0, 8)}</TableCell>
                <TableCell>
                  <Badge variant="outline">{m.auth_method}</Badge>
                </TableCell>
                <TableCell>
                  {m.auth_method === "ldap" ? <span className="text-xs text-muted-foreground">directory</span> : m.has_password ? <Badge variant="success">Set</Badge> : <Badge variant="warning">Not set</Badge>}
                </TableCell>
                <TableCell className="text-xs">{m.valid_until ? <span className={expired ? "text-destructive" : undefined}>{formatDateTime(m.valid_until)}</span> : "—"}</TableCell>
                <TableCell>{m.enabled && !expired ? <Badge variant="success">Active</Badge> : <Badge variant="muted">{expired ? "Expired" : "Disabled"}</Badge>}</TableCell>
                <TableCell className="whitespace-nowrap">
                  {writable ? (
                    <div className="flex justify-end gap-1">
                      {m.auth_method === "crypt" ? (
                        <Button variant="outline" size="xs" onClick={() => setPwFor(m)}>
                          <KeyRound /> Set password
                        </Button>
                      ) : null}
                      <Button variant="ghost" size="icon-sm" aria-label={`Remove ${m.tacacs_username}`} onClick={() => confirm.ask(m)}>
                        <Trash2 />
                      </Button>
                    </div>
                  ) : null}
                </TableCell>
              </TableRow>
            );
          })}
        </TableBody>
      </Table>
      <MappingDialog open={createOpen} onOpenChange={setCreateOpen} />
      <MappingDialog open={!!pwFor} onOpenChange={(o) => !o && setPwFor(undefined)} replace={pwFor} />
      <ConfirmDialog
        open={confirm.open}
        onOpenChange={confirm.onOpenChange}
        title={`Remove ${confirm.target?.tacacs_username ?? ""}?`}
        description="The user can no longer log in to devices after the next deploy."
        destructive
        confirmLabel="Remove"
        loading={del.isPending}
        onConfirm={() => confirm.target && del.mutate(confirm.target)}
      />
    </Card>
  );
}
