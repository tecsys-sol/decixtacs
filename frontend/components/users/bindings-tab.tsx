"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link2, Plus, Trash2 } from "lucide-react";
import * as React from "react";

import { ConfirmDialog, useConfirm } from "@/components/common/confirm-dialog";
import { EmptyState } from "@/components/common/empty-state";
import { Field } from "@/components/common/field";
import { TableState } from "@/components/common/table-skeleton";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Segmented } from "@/components/ui/tabs";
import { SimpleSelect } from "@/components/ui/select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { useAuth } from "@/hooks/use-auth";
import { useAllUsers, useDeviceGroups, useGroups, useRoles, useSites } from "@/hooks/use-lookups";
import { toast } from "@/hooks/use-toast";
import { useOnOpen } from "@/hooks/use-reset";
import { api, errorMessage } from "@/lib/api";
import type { RoleBinding } from "@/lib/types";

function BindingDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (o: boolean) => void }) {
  const qc = useQueryClient();
  const roles = useRoles();
  const users = useAllUsers();
  const groups = useGroups();
  const sites = useSites();
  const deviceGroups = useDeviceGroups();
  const [principal, setPrincipal] = React.useState<"group" | "user">("group");
  const [roleId, setRoleId] = React.useState("");
  const [subject, setSubject] = React.useState("");
  const [scopeType, setScopeType] = React.useState("");
  const [scopeId, setScopeId] = React.useState("");
  useOnOpen(open, () => {
    setPrincipal("group");
    setRoleId("");
    setSubject("");
    setScopeType("");
    setScopeId("");
  });
  const create = useMutation({
    mutationFn: () =>
      api.post<RoleBinding>("/role-bindings", {
        role_id: roleId,
        user_id: principal === "user" ? subject : null,
        group_id: principal === "group" ? subject : null,
        scope_type: scopeType || null,
        scope_id: scopeType ? scopeId : null,
      }),
    onSuccess: () => {
      toast.success("Role binding created");
      void qc.invalidateQueries({ queryKey: ["role-bindings"] });
      onOpenChange(false);
    },
    onError: (e) => toast.error("Could not create binding", errorMessage(e)),
  });
  const scopeOptions =
    scopeType === "site"
      ? (sites.data ?? []).map((s) => ({ value: s.id, label: s.name }))
      : (deviceGroups.data ?? []).map((g) => ({ value: g.id, label: g.name }));
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Bind role</DialogTitle>
          <DialogDescription>Scoped bindings grant device permissions only within a site or device group.</DialogDescription>
        </DialogHeader>
        <div className="grid gap-3">
          <Field label="Role" htmlFor="brole" required>
            <SimpleSelect id="brole" value={roleId} onValueChange={setRoleId} placeholder="Select role" options={(roles.data ?? []).map((r) => ({ value: r.id, label: r.name }))} />
          </Field>
          <Field label="Grant to">
            <Segmented<"group" | "user">
              value={principal}
              onChange={(v) => {
                setPrincipal(v);
                setSubject("");
              }}
              options={[{ value: "group", label: "Group" }, { value: "user", label: "User" }]}
            />
          </Field>
          <Field label={principal === "group" ? "Group" : "User"} htmlFor="bsubj" required>
            <SimpleSelect
              id="bsubj"
              value={subject}
              onValueChange={setSubject}
              placeholder={`Select ${principal}`}
              options={
                principal === "group"
                  ? (groups.data ?? []).map((g) => ({ value: g.id, label: g.name }))
                  : (users.data ?? []).map((u) => ({ value: u.id, label: u.username }))
              }
            />
          </Field>
          <div className="grid gap-3 sm:grid-cols-2">
            <Field label="Scope" htmlFor="bscope">
              <SimpleSelect
                id="bscope"
                value={scopeType}
                onValueChange={(v) => {
                  setScopeType(v);
                  setScopeId("");
                }}
                allowEmpty
                emptyLabel="Global (whole tenant)"
                options={[{ value: "site", label: "Site" }, { value: "device_group", label: "Device group" }]}
              />
            </Field>
            {scopeType ? (
              <Field label={scopeType === "site" ? "Site" : "Device group"} htmlFor="bscopeid" required>
                <SimpleSelect id="bscopeid" value={scopeId} onValueChange={setScopeId} placeholder="Select…" options={scopeOptions} />
              </Field>
            ) : null}
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button onClick={() => create.mutate()} loading={create.isPending} disabled={!roleId || !subject || (!!scopeType && !scopeId)}>
            Create binding
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

export function BindingsTab() {
  const { can } = useAuth();
  const qc = useQueryClient();
  const users = useAllUsers();
  const groups = useGroups();
  const sites = useSites();
  const deviceGroups = useDeviceGroups();
  const q = useQuery({ queryKey: ["role-bindings"], queryFn: () => api.get<RoleBinding[]>("/role-bindings") });
  const [open, setOpen] = React.useState(false);
  const confirm = useConfirm<RoleBinding>();
  const del = useMutation({
    mutationFn: (b: RoleBinding) => api.delete(`/role-bindings/${b.id}`),
    onSuccess: () => {
      toast.success("Binding removed");
      confirm.close();
      void qc.invalidateQueries({ queryKey: ["role-bindings"] });
    },
  });
  const uName = new Map((users.data ?? []).map((u) => [u.id, u.username]));
  const gName = new Map((groups.data ?? []).map((g) => [g.id, g.name]));
  const sName = new Map((sites.data ?? []).map((s) => [s.id, s.name]));
  const dgName = new Map((deviceGroups.data ?? []).map((g) => [g.id, g.name]));
  const list = q.data ?? [];
  const writable = can("users:write");

  return (
    <Card>
      <CardHeader className="flex-row items-center justify-between">
        <div>
          <CardTitle>Role bindings</CardTitle>
          <CardDescription>Who holds which role, and where.</CardDescription>
        </div>
        {writable ? (
          <Button size="sm" onClick={() => setOpen(true)}>
            <Plus /> Bind role
          </Button>
        ) : null}
      </CardHeader>
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Role</TableHead>
            <TableHead>Granted to</TableHead>
            <TableHead className="w-full">Scope</TableHead>
            <TableHead />
          </TableRow>
        </TableHeader>
        <TableBody>
          <TableState cols={4} isLoading={q.isLoading} error={q.error} onRetry={() => void q.refetch()} isEmpty={list.length === 0} empty={<EmptyState icon={Link2} title="No role bindings" />} />
          {list.map((b) => (
            <TableRow key={b.id}>
              <TableCell className="whitespace-nowrap font-medium">{b.role.name}</TableCell>
              <TableCell className="whitespace-nowrap">
                {b.group_id ? (
                  <>
                    <Badge variant="info">group</Badge> {gName.get(b.group_id) ?? b.group_id.slice(0, 8)}
                  </>
                ) : (
                  <>
                    <Badge variant="default">user</Badge> {b.user_id ? uName.get(b.user_id) ?? b.user_id.slice(0, 8) : "—"}
                  </>
                )}
              </TableCell>
              <TableCell>
                {b.scope_type && b.scope_id ? (
                  <Badge variant="outline">
                    {b.scope_type === "site" ? "site" : "device group"}: {(b.scope_type === "site" ? sName : dgName).get(b.scope_id) ?? b.scope_id.slice(0, 8)}
                  </Badge>
                ) : (
                  <span className="text-xs text-muted-foreground">global</span>
                )}
              </TableCell>
              <TableCell>
                {writable ? (
                  <Button variant="ghost" size="icon-sm" aria-label="Remove binding" onClick={() => confirm.ask(b)}>
                    <Trash2 />
                  </Button>
                ) : null}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
      <BindingDialog open={open} onOpenChange={setOpen} />
      <ConfirmDialog open={confirm.open} onOpenChange={confirm.onOpenChange} title={`Remove ${confirm.target?.role.name ?? ""} binding?`} destructive confirmLabel="Remove" loading={del.isPending} onConfirm={() => confirm.target && del.mutate(confirm.target)} />
    </Card>
  );
}
