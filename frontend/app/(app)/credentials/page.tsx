"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { KeyRound, Pencil, Plus, Star, Trash2 } from "lucide-react";
import * as React from "react";

import { ConfirmDialog, useConfirm } from "@/components/common/confirm-dialog";
import { EmptyState } from "@/components/common/empty-state";
import { Field } from "@/components/common/field";
import { PageHeader } from "@/components/common/page-header";
import { RelativeTime } from "@/components/common/relative-time";
import { TableState } from "@/components/common/table-skeleton";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
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
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Textarea } from "@/components/ui/textarea";
import { useAuth } from "@/hooks/use-auth";
import { useOnOpen } from "@/hooks/use-reset";
import { toast } from "@/hooks/use-toast";
import { api } from "@/lib/api";
import type { Credential } from "@/lib/types";

interface Form {
  name: string;
  username: string;
  password: string;
  ssh_key: string;
  enable_secret: string;
  make_default: boolean;
}

function CredentialDialog({
  open,
  onOpenChange,
  editing,
  hasDefault,
}: {
  open: boolean;
  onOpenChange: (o: boolean) => void;
  editing: Credential | null;
  hasDefault: boolean;
}) {
  const qc = useQueryClient();
  const empty: Form = {
    name: "",
    username: "",
    password: "",
    ssh_key: "",
    enable_secret: "",
    make_default: false,
  };
  const [f, setF] = React.useState<Form>(empty);
  useOnOpen(open, () =>
    setF(
      editing
        ? {
            ...empty,
            name: editing.name,
            username: editing.username,
            make_default: !!editing.is_default,
          }
        : { ...empty, make_default: !hasDefault },
    ),
  );
  const set =
    (k: keyof Form) =>
    (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) =>
      setF((p) => ({ ...p, [k]: e.target.value }));

  const save = useMutation({
    mutationFn: () => {
      // Secrets left blank on edit keep their stored value.
      const body = {
        name: f.name.trim(),
        username: f.username.trim(),
        password: f.password || null,
        ssh_key: f.ssh_key.trim() || null,
        enable_secret: f.enable_secret || null,
        make_default: f.make_default,
      };
      return editing
        ? api.put<Credential>(`/credentials/${editing.id}`, body)
        : api.post<Credential>("/credentials", body);
    },
    onSuccess: (c) => {
      void qc.invalidateQueries({ queryKey: ["credentials"] });
      toast.success(
        editing
          ? `Credential ${c.name} updated`
          : `Credential ${c.name} created`,
      );
      onOpenChange(false);
    },
    onError: (e) => toast.error("Could not save credential", e),
  });
  const valid =
    f.name.trim() &&
    f.username.trim() &&
    (editing || f.password || f.ssh_key.trim());

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>
            {editing ? `Edit credential ${editing.name}` : "Add credential"}
          </DialogTitle>
          <DialogDescription>
            SSH login used for configuration backups, drift checks and restores.
            Secrets are encrypted at rest and never shown again
            {editing ? "; leave a secret empty to keep the stored one" : ""}.
          </DialogDescription>
        </DialogHeader>
        <form
          className="grid gap-3"
          onSubmit={(e) => {
            e.preventDefault();
            if (valid) save.mutate();
          }}
        >
          <Field
            label="Name"
            htmlFor="cred-name"
            required
            hint="e.g. rancid-backup"
          >
            <Input
              id="cred-name"
              value={f.name}
              onChange={set("name")}
              autoComplete="off"
            />
          </Field>
          <Field label="Username" htmlFor="cred-user" required>
            <Input
              id="cred-user"
              value={f.username}
              onChange={set("username")}
              autoComplete="off"
            />
          </Field>
          <Field
            label="Password"
            htmlFor="cred-pass"
            hint={
              editing?.has_password ? "Stored - leave empty to keep" : undefined
            }
          >
            <Input
              id="cred-pass"
              type="password"
              value={f.password}
              onChange={set("password")}
              autoComplete="new-password"
            />
          </Field>
          <Field
            label="SSH private key (optional)"
            htmlFor="cred-key"
            hint={
              editing?.has_ssh_key ? "Stored - leave empty to keep" : undefined
            }
          >
            <Textarea
              id="cred-key"
              value={f.ssh_key}
              onChange={set("ssh_key")}
              placeholder="-----BEGIN OPENSSH PRIVATE KEY-----"
              className="min-h-[80px] font-mono text-xs"
              spellCheck={false}
            />
          </Field>
          <Field
            label="Enable secret (optional)"
            htmlFor="cred-enable"
            hint="Cisco/Arista privileged mode, if the account needs it"
          >
            <Input
              id="cred-enable"
              type="password"
              value={f.enable_secret}
              onChange={set("enable_secret")}
              autoComplete="new-password"
            />
          </Field>
          <label className="flex items-start gap-2 text-sm">
            <Checkbox
              checked={f.make_default}
              onCheckedChange={(v) =>
                setF((p) => ({ ...p, make_default: v === true }))
              }
            />
            <span>
              <span className="font-medium">Default credential</span>
              <span className="block text-xs text-muted-foreground">
                Used for every device that has no credential of its own (e.g.
                all NetBox-synced devices).
              </span>
            </span>
          </label>
          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              onClick={() => onOpenChange(false)}
            >
              Cancel
            </Button>
            <Button type="submit" disabled={!valid} loading={save.isPending}>
              {editing ? "Save" : "Add credential"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

export default function CredentialsPage() {
  const { can } = useAuth();
  const qc = useQueryClient();
  const writable = can("credentials:write");
  const q = useQuery({
    queryKey: ["credentials"],
    queryFn: () => api.get<Credential[]>("/credentials"),
  });
  const [dialog, setDialog] = React.useState<{
    open: boolean;
    editing: Credential | null;
  }>({ open: false, editing: null });
  const confirmDelete = useConfirm<Credential>();
  const list = q.data ?? [];
  const hasDefault = list.some((c) => c.is_default);

  const makeDefault = useMutation({
    mutationFn: (c: Credential) =>
      api.post<Credential>(`/credentials/${c.id}/default`),
    onSuccess: (c) => {
      void qc.invalidateQueries({ queryKey: ["credentials"] });
      toast.success(`${c.name} is now the default credential`);
    },
    onError: (e) => toast.error("Could not set default", e),
  });
  const remove = useMutation({
    mutationFn: (c: Credential) => api.delete(`/credentials/${c.id}`),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["credentials"] });
      confirmDelete.close();
      toast.success("Credential deleted");
    },
    onError: (e) => toast.error("Could not delete credential", e),
  });

  return (
    <>
      <PageHeader
        title="Credentials"
        description="SSH accounts used to collect configurations. Devices without their own credential use the default."
        actions={
          writable ? (
            <Button onClick={() => setDialog({ open: true, editing: null })}>
              <Plus /> Add credential
            </Button>
          ) : null
        }
      />
      {!q.isLoading && list.length > 0 && !hasDefault ? (
        <div
          className="mb-4 rounded-lg border border-warning/40 bg-warning/10 p-3 text-sm"
          role="status"
        >
          No default credential is set - devices without their own credential
          cannot be backed up. Mark one as default.
        </div>
      ) : null}
      <Card className="overflow-hidden">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Name</TableHead>
              <TableHead>Username</TableHead>
              <TableHead>Authentication</TableHead>
              <TableHead>Assigned devices</TableHead>
              <TableHead>Rotated</TableHead>
              <TableHead className="text-right">Actions</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            <TableState
              isLoading={q.isLoading}
              error={q.error}
              isEmpty={list.length === 0}
              cols={6}
              onRetry={() => void q.refetch()}
              empty={
                <EmptyState
                  icon={KeyRound}
                  title="No credentials yet"
                  description="Add the SSH account your backups use today (for example the RANCID user) and mark it as default."
                />
              }
            />
            {list.map((c) => (
              <TableRow key={c.id}>
                <TableCell>
                  <span className="font-medium">{c.name}</span>{" "}
                  {c.is_default ? (
                    <Badge variant="success" className="ml-1">
                      Default
                    </Badge>
                  ) : null}
                </TableCell>
                <TableCell className="font-mono text-sm">
                  {c.username}
                </TableCell>
                <TableCell>
                  <div className="flex flex-wrap gap-1">
                    {c.has_password ? (
                      <Badge variant="muted">Password</Badge>
                    ) : null}
                    {c.has_ssh_key ? (
                      <Badge variant="muted">SSH key</Badge>
                    ) : null}
                    {c.has_enable_secret ? (
                      <Badge variant="muted">Enable secret</Badge>
                    ) : null}
                  </div>
                </TableCell>
                <TableCell>
                  {c.is_default
                    ? `${c.device_count ?? 0} + all without their own`
                    : (c.device_count ?? 0)}
                </TableCell>
                <TableCell>
                  <RelativeTime value={c.rotated_at} />
                </TableCell>
                <TableCell className="text-right">
                  {writable ? (
                    <div className="flex justify-end gap-1">
                      {!c.is_default ? (
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={() => makeDefault.mutate(c)}
                          loading={
                            makeDefault.isPending &&
                            makeDefault.variables?.id === c.id
                          }
                        >
                          <Star /> Make default
                        </Button>
                      ) : null}
                      <Button
                        variant="ghost"
                        size="sm"
                        aria-label={`Edit ${c.name}`}
                        onClick={() => setDialog({ open: true, editing: c })}
                      >
                        <Pencil />
                      </Button>
                      <Button
                        variant="ghost"
                        size="sm"
                        aria-label={`Delete ${c.name}`}
                        onClick={() => confirmDelete.ask(c)}
                      >
                        <Trash2 />
                      </Button>
                    </div>
                  ) : null}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </Card>
      <CredentialDialog
        open={dialog.open}
        onOpenChange={(o) => setDialog((d) => ({ ...d, open: o }))}
        editing={dialog.editing}
        hasDefault={hasDefault}
      />
      <ConfirmDialog
        open={confirmDelete.open}
        onOpenChange={confirmDelete.onOpenChange}
        title={`Delete credential ${confirmDelete.target?.name ?? ""}?`}
        description="Devices assigned to it fall back to the default credential. This cannot be undone."
        confirmLabel="Delete"
        destructive
        loading={remove.isPending}
        onConfirm={() =>
          confirmDelete.target && remove.mutate(confirmDelete.target)
        }
      />
    </>
  );
}
