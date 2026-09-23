"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Pencil, Plus, Trash2, UsersRound } from "lucide-react";
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
import { Input } from "@/components/ui/input";
import { SimpleSelect } from "@/components/ui/select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { useAuth } from "@/hooks/use-auth";
import { useGroups } from "@/hooks/use-lookups";
import { toast } from "@/hooks/use-toast";
import { useOnOpen } from "@/hooks/use-reset";
import { api, errorMessage } from "@/lib/api";
import type { Group } from "@/lib/types";

function GroupDialog({ open, onOpenChange, group }: { open: boolean; onOpenChange: (o: boolean) => void; group?: Group }) {
  const qc = useQueryClient();
  const [f, setF] = React.useState({ name: "", description: "", source: "local", external_dn: "" });
  useOnOpen(open, () => {
    setF({ name: group?.name ?? "", description: group?.description ?? "", source: group?.source ?? "local", external_dn: group?.external_dn ?? "" });
  });
  const save = useMutation({
    mutationFn: () => {
      const body = { name: f.name.trim(), description: f.description.trim() || null, source: f.source, external_dn: f.external_dn.trim() || null };
      return group ? api.patch<Group>(`/groups/${group.id}`, body) : api.post<Group>("/groups", body);
    },
    onSuccess: () => {
      toast.success(group ? "Group updated" : "Group created");
      void qc.invalidateQueries({ queryKey: ["groups"] });
      onOpenChange(false);
    },
    onError: (e) => toast.error("Could not save group", errorMessage(e)),
  });
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{group ? `Edit ${group.name}` : "Create group"}</DialogTitle>
          <DialogDescription>Directory groups are synchronised from LDAP/AD by their DN.</DialogDescription>
        </DialogHeader>
        <form
          className="grid gap-3"
          onSubmit={(e) => {
            e.preventDefault();
            save.mutate();
          }}
        >
          <Field label="Name" htmlFor="gname" required>
            <Input id="gname" value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} />
          </Field>
          <Field label="Description" htmlFor="gdesc">
            <Input id="gdesc" value={f.description} onChange={(e) => setF({ ...f, description: e.target.value })} />
          </Field>
          <div className="grid gap-3 sm:grid-cols-[160px_1fr]">
            <Field label="Source" htmlFor="gsrc">
              <SimpleSelect id="gsrc" value={f.source} onValueChange={(v) => setF({ ...f, source: v })} options={[{ value: "local", label: "Local" }, { value: "ldap", label: "LDAP / AD" }, { value: "oidc", label: "OIDC" }]} />
            </Field>
            <Field label="External DN / claim" htmlFor="gdn">
              <Input id="gdn" value={f.external_dn} onChange={(e) => setF({ ...f, external_dn: e.target.value })} className="font-mono text-xs" placeholder="CN=NOC,OU=Groups,DC=example,DC=net" />
            </Field>
          </div>
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
              Cancel
            </Button>
            <Button type="submit" loading={save.isPending} disabled={!f.name.trim()}>
              {group ? "Save" : "Create group"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

export function GroupsTab() {
  const { can } = useAuth();
  const qc = useQueryClient();
  const groups = useGroups();
  const [editing, setEditing] = React.useState<Group | undefined>();
  const [open, setOpen] = React.useState(false);
  const confirm = useConfirm<Group>();
  const writable = can("users:write");
  const del = useMutation({
    mutationFn: (g: Group) => api.delete(`/groups/${g.id}`),
    onSuccess: () => {
      toast.success("Group deleted");
      confirm.close();
      void qc.invalidateQueries({ queryKey: ["groups"] });
    },
  });
  const list = groups.data ?? [];
  return (
    <Card>
      <CardHeader className="flex-row items-center justify-between">
        <div>
          <CardTitle>Groups</CardTitle>
          <CardDescription>Group membership drives role bindings and TACACS+ policies.</CardDescription>
        </div>
        {writable ? (
          <Button size="sm" onClick={() => { setEditing(undefined); setOpen(true); }}>
            <Plus /> Create group
          </Button>
        ) : null}
      </CardHeader>
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Name</TableHead>
            <TableHead className="w-full">Description</TableHead>
            <TableHead>Source</TableHead>
            <TableHead>External DN</TableHead>
            <TableHead />
          </TableRow>
        </TableHeader>
        <TableBody>
          <TableState cols={5} isLoading={groups.isLoading} error={groups.error} onRetry={() => void groups.refetch()} isEmpty={list.length === 0} empty={<EmptyState icon={UsersRound} title="No groups" />} />
          {list.map((g) => (
            <TableRow key={g.id}>
              <TableCell className="whitespace-nowrap font-medium">{g.name}</TableCell>
              <TableCell className="text-muted-foreground">{g.description ?? "—"}</TableCell>
              <TableCell>
                <Badge variant="outline">{g.source}</Badge>
              </TableCell>
              <TableCell className="max-w-[260px] truncate font-mono text-xs" title={g.external_dn ?? undefined}>
                {g.external_dn ?? "—"}
              </TableCell>
              <TableCell className="whitespace-nowrap">
                {writable ? (
                  <div className="flex justify-end gap-1">
                    <Button variant="ghost" size="icon-sm" aria-label={`Edit ${g.name}`} onClick={() => { setEditing(g); setOpen(true); }}>
                      <Pencil />
                    </Button>
                    <Button variant="ghost" size="icon-sm" aria-label={`Delete ${g.name}`} onClick={() => confirm.ask(g)}>
                      <Trash2 />
                    </Button>
                  </div>
                ) : null}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
      <GroupDialog open={open} onOpenChange={setOpen} group={editing} />
      <ConfirmDialog open={confirm.open} onOpenChange={confirm.onOpenChange} title={`Delete group ${confirm.target?.name ?? ""}?`} description="Role bindings and TACACS+ policies referencing this group stop applying." destructive confirmLabel="Delete" loading={del.isPending} onConfirm={() => confirm.target && del.mutate(confirm.target)} />
    </Card>
  );
}
