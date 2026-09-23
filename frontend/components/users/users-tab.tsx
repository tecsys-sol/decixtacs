"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { Plus, Users } from "lucide-react";
import * as React from "react";

import { EmptyState } from "@/components/common/empty-state";
import { Field } from "@/components/common/field";
import { FilterBar } from "@/components/common/filter-bar";
import { Pagination } from "@/components/common/pagination";
import { RelativeTime } from "@/components/common/relative-time";
import { TableState } from "@/components/common/table-skeleton";
import { TextFilter } from "@/components/common/text-filter";
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
import { SimpleSelect } from "@/components/ui/select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { useAuth } from "@/hooks/use-auth";
import { useGroups } from "@/hooks/use-lookups";
import { toast } from "@/hooks/use-toast";
import { useNow } from "@/hooks/use-now";
import { useOnOpen } from "@/hooks/use-reset";
import { api, errorMessage } from "@/lib/api";
import { PAGE_SIZE } from "@/lib/constants";
import type { Page, User, UserIn } from "@/lib/types";

export const AUTH_SOURCES = [
  { value: "local", label: "Local" },
  { value: "ldap", label: "LDAP / AD" },
  { value: "oidc", label: "OIDC / SSO" },
];

function CreateUserDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (o: boolean) => void }) {
  const qc = useQueryClient();
  const groups = useGroups();
  const blank: Required<Omit<UserIn, "password">> & { password: string } = {
    username: "",
    email: "",
    full_name: "",
    password: "",
    auth_source: "local",
    is_active: true,
    group_ids: [],
  };
  const [f, setF] = React.useState(blank);
  useOnOpen(open, () => {
    setF(blank);
  });
  const create = useMutation({
    mutationFn: () =>
      api.post<User>("/users", {
        ...f,
        username: f.username.trim(),
        email: f.email?.trim() || null,
        full_name: f.full_name?.trim() || null,
        password: f.auth_source === "local" ? f.password : null,
      }),
    onSuccess: (u) => {
      toast.success(`User ${u.username} created`);
      void qc.invalidateQueries({ queryKey: ["users"] });
      onOpenChange(false);
    },
    onError: (e) => toast.error("Could not create user", errorMessage(e)),
  });
  const valid = f.username.trim() && (f.auth_source !== "local" || f.password.length > 0);
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-xl">
        <DialogHeader>
          <DialogTitle>Create user</DialogTitle>
          <DialogDescription>Permissions come from roles bound to the user or their groups.</DialogDescription>
        </DialogHeader>
        <form
          className="grid gap-3"
          onSubmit={(e) => {
            e.preventDefault();
            if (valid) create.mutate();
          }}
        >
          <div className="grid gap-3 sm:grid-cols-2">
            <Field label="Username" htmlFor="uname" required>
              <Input id="uname" value={f.username} onChange={(e) => setF({ ...f, username: e.target.value })} autoComplete="off" />
            </Field>
            <Field label="Full name" htmlFor="ufull">
              <Input id="ufull" value={f.full_name ?? ""} onChange={(e) => setF({ ...f, full_name: e.target.value })} />
            </Field>
            <Field label="Email" htmlFor="uemail">
              <Input id="uemail" type="email" value={f.email ?? ""} onChange={(e) => setF({ ...f, email: e.target.value })} />
            </Field>
            <Field label="Authentication" htmlFor="usrc">
              <SimpleSelect id="usrc" value={f.auth_source} onValueChange={(v) => setF({ ...f, auth_source: v })} options={AUTH_SOURCES} />
            </Field>
            {f.auth_source === "local" ? (
              <Field label="Initial password" htmlFor="upw" required hint="Must satisfy the tenant password policy" className="sm:col-span-2">
                <Input id="upw" type="password" autoComplete="new-password" value={f.password} onChange={(e) => setF({ ...f, password: e.target.value })} />
              </Field>
            ) : null}
          </div>
          {groups.data?.length ? (
            <Field label="Groups">
              <div className="flex max-h-32 flex-wrap gap-x-4 gap-y-2 overflow-y-auto rounded-md border p-2">
                {groups.data.map((g) => (
                  <Checkbox
                    key={g.id}
                    label={g.name}
                    checked={f.group_ids.includes(g.id)}
                    onCheckedChange={(c) => setF({ ...f, group_ids: c ? [...f.group_ids, g.id] : f.group_ids.filter((x) => x !== g.id) })}
                  />
                ))}
              </div>
            </Field>
          ) : null}
          <Checkbox label="Active" checked={f.is_active} onCheckedChange={(c) => setF({ ...f, is_active: c })} />
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
              Cancel
            </Button>
            <Button type="submit" loading={create.isPending} disabled={!valid}>
              Create user
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

export function UsersTab() {
  const { can } = useAuth();
  const [q, setQ] = React.useState("");
  const [offset, setOffset] = React.useState(0);
  const [open, setOpen] = React.useState(false);
  const now = useNow();
  const users = useQuery({
    queryKey: ["users", "list", q, offset],
    queryFn: () => api.get<Page<User>>("/users", { q, limit: PAGE_SIZE, offset }),
    placeholderData: (p) => p,
  });
  const items = users.data?.items ?? [];
  return (
    <Card>
      <FilterBar>
        <TextFilter value={q} onCommit={(v) => { setQ(v); setOffset(0); }} placeholder="Search username, name or email" className="w-72" aria-label="Search users" />
        {can("users:write") ? (
          <Button size="sm" className="ml-auto self-center" onClick={() => setOpen(true)}>
            <Plus /> Create user
          </Button>
        ) : null}
      </FilterBar>
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Username</TableHead>
            <TableHead>Name</TableHead>
            <TableHead>Source</TableHead>
            <TableHead className="w-full">Groups</TableHead>
            <TableHead>MFA</TableHead>
            <TableHead>Status</TableHead>
            <TableHead>Last login</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          <TableState cols={7} isLoading={users.isLoading} error={users.error} onRetry={() => void users.refetch()} isEmpty={items.length === 0} empty={<EmptyState icon={Users} title="No users found" />} />
          {items.map((u) => {
            const locked = u.locked_until ? new Date(u.locked_until).getTime() > now : false;
            return (
              <TableRow key={u.id}>
                <TableCell className="whitespace-nowrap">
                  <Link href={`/users/${u.id}`} className="font-medium text-primary hover:underline">
                    {u.username}
                  </Link>
                  {u.is_superuser ? <Badge variant="warning" className="ml-2">superuser</Badge> : null}
                </TableCell>
                <TableCell className="whitespace-nowrap">
                  {u.full_name ?? "—"}
                  {u.email ? <p className="text-xs text-muted-foreground">{u.email}</p> : null}
                </TableCell>
                <TableCell>
                  <Badge variant="outline">{u.auth_source}</Badge>
                </TableCell>
                <TableCell>
                  <div className="flex flex-wrap gap-1">
                    {u.groups.map((g) => (
                      <Badge key={g.id} variant="secondary">
                        {g.name}
                      </Badge>
                    ))}
                  </div>
                </TableCell>
                <TableCell>{u.mfa_enabled ? <Badge variant="success">On</Badge> : <Badge variant="muted">Off</Badge>}</TableCell>
                <TableCell>
                  {locked ? <Badge variant="danger">Locked</Badge> : u.is_active ? <Badge variant="success" dot>Active</Badge> : <Badge variant="muted" dot>Disabled</Badge>}
                </TableCell>
                <TableCell className="whitespace-nowrap text-xs">
                  <RelativeTime value={u.last_login_at} />
                </TableCell>
              </TableRow>
            );
          })}
        </TableBody>
      </Table>
      {users.data ? <Pagination total={users.data.total} limit={PAGE_SIZE} offset={offset} onChange={setOffset} /> : null}
      <CreateUserDialog open={open} onOpenChange={setOpen} />
    </Card>
  );
}
