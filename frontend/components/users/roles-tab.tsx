"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { KeySquare, Plus } from "lucide-react";
import * as React from "react";

import { EmptyState } from "@/components/common/empty-state";
import { ErrorState } from "@/components/common/error-state";
import { Field } from "@/components/common/field";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
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
import { Skeleton } from "@/components/ui/skeleton";
import { useAuth } from "@/hooks/use-auth";
import { useRoles } from "@/hooks/use-lookups";
import { toast } from "@/hooks/use-toast";
import { useOnOpen } from "@/hooks/use-reset";
import { api, errorMessage } from "@/lib/api";
import type { Permission, Role } from "@/lib/types";

function CreateRoleDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (o: boolean) => void }) {
  const qc = useQueryClient();
  const { can } = useAuth();
  const perms = useQuery({ queryKey: ["permissions"], queryFn: () => api.get<Permission[]>("/permissions"), enabled: open });
  const [name, setName] = React.useState("");
  const [description, setDescription] = React.useState("");
  const [selected, setSelected] = React.useState<string[]>([]);
  useOnOpen(open, () => {
    setName("");
    setDescription("");
    setSelected([]);
  });
  const create = useMutation({
    mutationFn: () => api.post<Role>("/roles", { name: name.trim(), description: description.trim() || null, permissions: selected }),
    onSuccess: () => {
      toast.success("Role created");
      void qc.invalidateQueries({ queryKey: ["roles"] });
      onOpenChange(false);
    },
    onError: (e) => toast.error("Could not create role", errorMessage(e)),
  });
  const grouped = React.useMemo(() => {
    const m = new Map<string, Permission[]>();
    for (const p of perms.data ?? []) {
      const area = p.code.split(":")[0];
      m.set(area, [...(m.get(area) ?? []), p]);
    }
    return [...m.entries()];
  }, [perms.data]);
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle>Create role</DialogTitle>
          <DialogDescription>You can only grant permissions you hold yourself.</DialogDescription>
        </DialogHeader>
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label="Name" htmlFor="rname" required>
            <Input id="rname" value={name} onChange={(e) => setName(e.target.value)} />
          </Field>
          <Field label="Description" htmlFor="rdesc">
            <Input id="rdesc" value={description} onChange={(e) => setDescription(e.target.value)} />
          </Field>
        </div>
        {perms.isLoading ? (
          <Skeleton className="h-60" />
        ) : (
          <div className="grid max-h-[45vh] gap-3 overflow-y-auto rounded-md border p-3 sm:grid-cols-2">
            {grouped.map(([area, ps]) => (
              <fieldset key={area} className="grid gap-1.5">
                <legend className="mb-1 text-xs font-semibold uppercase tracking-wide text-muted-foreground">{area}</legend>
                {ps.map((p) => (
                  <Checkbox
                    key={p.code}
                    disabled={!can(p.code)}
                    checked={selected.includes(p.code)}
                    onCheckedChange={(c) => setSelected((s) => (c ? [...s, p.code] : s.filter((x) => x !== p.code)))}
                    label={
                      <span className="text-xs">
                        <code className="font-mono">{p.code}</code>
                        {p.description ? <span className="block text-muted-foreground">{p.description}</span> : null}
                      </span>
                    }
                  />
                ))}
              </fieldset>
            ))}
          </div>
        )}
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button onClick={() => create.mutate()} loading={create.isPending} disabled={!name.trim() || !selected.length}>
            Create role
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

export function RolesTab() {
  const { can } = useAuth();
  const roles = useRoles();
  const [open, setOpen] = React.useState(false);
  return (
    <div className="grid gap-3">
      <div className="flex items-center justify-between">
        <p className="text-sm text-muted-foreground">Roles are sets of permissions; bind them to users or groups under Role bindings.</p>
        {can("users:write") ? (
          <Button size="sm" onClick={() => setOpen(true)}>
            <Plus /> Create role
          </Button>
        ) : null}
      </div>
      {roles.isLoading ? (
        <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">{Array.from({ length: 6 }).map((_, i) => <Skeleton key={i} className="h-40" />)}</div>
      ) : roles.error ? (
        <ErrorState error={roles.error} onRetry={() => void roles.refetch()} />
      ) : roles.data?.length ? (
        <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
          {roles.data.map((r) => (
            <Card key={r.id}>
              <CardHeader>
                <CardTitle className="flex items-center gap-2">
                  {r.name} {r.builtin ? <Badge variant="muted">built-in</Badge> : null}
                </CardTitle>
                <CardDescription>{r.description ?? `${r.permissions.length} permissions`}</CardDescription>
              </CardHeader>
              <CardContent>
                <div className="flex flex-wrap gap-1">
                  {r.permissions.map((p) => (
                    <Badge key={p.code} variant="secondary" className="font-mono" title={p.description ?? undefined}>
                      {p.code}
                    </Badge>
                  ))}
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
      ) : (
        <Card>
          <EmptyState icon={KeySquare} title="No roles" />
        </Card>
      )}
      <CreateRoleDialog open={open} onOpenChange={setOpen} />
    </div>
  );
}
