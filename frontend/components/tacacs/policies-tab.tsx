"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Pencil, Plus, ShieldCheck, Trash2 } from "lucide-react";
import * as React from "react";

import { ConfirmDialog, useConfirm } from "@/components/common/confirm-dialog";
import { EmptyState } from "@/components/common/empty-state";
import { ErrorState } from "@/components/common/error-state";
import { RelativeTime } from "@/components/common/relative-time";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { useAuth } from "@/hooks/use-auth";
import { useDeviceGroups, useGroups } from "@/hooks/use-lookups";
import { toast } from "@/hooks/use-toast";
import { api } from "@/lib/api";
import type { Policy } from "@/lib/types";

import { PolicyEditor } from "./policy-editor";

export function PoliciesTab() {
  const { can } = useAuth();
  const qc = useQueryClient();
  const groups = useGroups();
  const deviceGroups = useDeviceGroups();
  const q = useQuery({ queryKey: ["tacacs", "policies"], queryFn: () => api.get<Policy[]>("/tacacs/policies") });
  const [editing, setEditing] = React.useState<Policy | undefined>();
  const [open, setOpen] = React.useState(false);
  const confirm = useConfirm<Policy>();
  const writable = can("tacacs:write");

  const del = useMutation({
    mutationFn: (p: Policy) => api.delete(`/tacacs/policies/${p.id}`),
    onSuccess: () => {
      toast.success("Policy deleted");
      confirm.close();
      void qc.invalidateQueries({ queryKey: ["tacacs"] });
    },
  });

  const gName = new Map((groups.data ?? []).map((g) => [g.id, g.name]));
  const dgName = new Map((deviceGroups.data ?? []).map((g) => [g.id, g.name]));
  const list = [...(q.data ?? [])].sort((a, b) => a.priority - b.priority);

  return (
    <div className="grid gap-3">
      <div className="flex items-center justify-between">
        <p className="text-sm text-muted-foreground">{list.length} policies, evaluated in priority order.</p>
        {writable ? (
          <Button size="sm" onClick={() => { setEditing(undefined); setOpen(true); }}>
            <Plus /> New policy
          </Button>
        ) : null}
      </div>
      {q.isLoading ? (
        <div className="grid gap-3 md:grid-cols-2">{Array.from({ length: 4 }).map((_, i) => <Skeleton key={i} className="h-40" />)}</div>
      ) : q.error ? (
        <ErrorState error={q.error} onRetry={() => void q.refetch()} />
      ) : list.length === 0 ? (
        <Card>
          <EmptyState icon={ShieldCheck} title="No policies" description="Create a policy to grant a user group access to devices." />
        </Card>
      ) : (
        <div className="grid gap-3 md:grid-cols-2">
          {list.map((p) => (
            <Card key={p.id} className={p.enabled ? undefined : "opacity-60"}>
              <CardHeader className="flex-row items-start justify-between gap-2">
                <div className="min-w-0">
                  <CardTitle className="flex items-center gap-2">
                    {p.name}
                    {p.enabled ? null : <Badge variant="muted">Disabled</Badge>}
                  </CardTitle>
                  <CardDescription>
                    {p.description || "No description"} · updated <RelativeTime value={p.updated_at} />
                  </CardDescription>
                </div>
                {writable ? (
                  <div className="flex shrink-0 gap-1">
                    <Button variant="ghost" size="icon-sm" aria-label={`Edit ${p.name}`} onClick={() => { setEditing(p); setOpen(true); }}>
                      <Pencil />
                    </Button>
                    <Button variant="ghost" size="icon-sm" aria-label={`Delete ${p.name}`} onClick={() => confirm.ask(p)}>
                      <Trash2 />
                    </Button>
                  </div>
                ) : null}
              </CardHeader>
              <CardContent className="grid gap-3">
                <div className="flex flex-wrap gap-1.5 text-xs">
                  <Badge variant="secondary">prio {p.priority}</Badge>
                  <Badge variant="info">group: {gName.get(p.group_id) ?? p.group_id.slice(0, 8)}</Badge>
                  <Badge variant="outline">{p.device_group_id ? `devices: ${dgName.get(p.device_group_id) ?? "…"}` : "all devices"}</Badge>
                  <Badge variant="default">priv-lvl {p.privilege_level}</Badge>
                  <Badge variant={p.default_action === "permit" ? "success" : "danger"}>default {p.default_action}</Badge>
                  {p.junos_class ? <Badge variant="outline">junos: {p.junos_class}</Badge> : null}
                  {p.fortigate_profile ? <Badge variant="outline">forti: {p.fortigate_profile}</Badge> : null}
                  {p.arista_role ? <Badge variant="outline">arista: {p.arista_role}</Badge> : null}
                  {p.time_window ? <Badge variant="warning">{p.time_window}</Badge> : null}
                </div>
                {p.command_rules.length ? (
                  <ol className="divide-y rounded-md border font-mono text-[11px]">
                    {[...p.command_rules].sort((a, b) => a.sequence - b.sequence).slice(0, 8).map((r) => (
                      <li key={r.id} className="flex items-center gap-2 px-2 py-1">
                        <span className="w-6 text-muted-foreground">{r.sequence}</span>
                        <span className={r.action === "deny" ? "w-12 text-destructive" : "w-12 text-success"}>{r.action}</span>
                        <span className="truncate">{r.pattern}</span>
                      </li>
                    ))}
                    {p.command_rules.length > 8 ? <li className="px-2 py-1 text-muted-foreground">+{p.command_rules.length - 8} more</li> : null}
                  </ol>
                ) : (
                  <p className="text-xs text-muted-foreground">No command rules.</p>
                )}
              </CardContent>
            </Card>
          ))}
        </div>
      )}
      <PolicyEditor open={open} onOpenChange={setOpen} policy={editing} />
      <ConfirmDialog
        open={confirm.open}
        onOpenChange={confirm.onOpenChange}
        title={`Delete policy "${confirm.target?.name ?? ""}"?`}
        description="Users in the group lose this access after the next deploy."
        destructive
        confirmLabel="Delete"
        loading={del.isPending}
        onConfirm={() => confirm.target && del.mutate(confirm.target)}
      />
    </div>
  );
}
