"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus, PlugZap, RefreshCw, Trash2 } from "lucide-react";
import * as React from "react";

import { ConfirmDialog, useConfirm } from "@/components/common/confirm-dialog";
import { EmptyState } from "@/components/common/empty-state";
import { ErrorState } from "@/components/common/error-state";
import { Field, KeyValue } from "@/components/common/field";
import { JsonView } from "@/components/common/json-view";
import { PageHeader } from "@/components/common/page-header";
import { RelativeTime } from "@/components/common/relative-time";
import { StatusBadge } from "@/components/common/status-badge";
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
import { SimpleSelect } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { Textarea } from "@/components/ui/textarea";
import { useAuth } from "@/hooks/use-auth";
import { toast } from "@/hooks/use-toast";
import { useOnOpen } from "@/hooks/use-reset";
import { api, errorMessage } from "@/lib/api";
import type { Integration, IntegrationIn, IntegrationKind } from "@/lib/types";

const KINDS: { value: IntegrationKind; label: string; description: string; placeholder: string; options: string }[] = [
  {
    value: "netbox",
    label: "NetBox",
    description: "Source of truth for sites, racks, devices, cables, IPAM and contacts.",
    placeholder: "https://netbox.example.net",
    options: '{\n  "site_filter": null,\n  "tag": "managed"\n}',
  },
  {
    value: "ixpmanager",
    label: "IXP Manager",
    description: "Members, connections, VLAN interfaces and route-server settings.",
    placeholder: "https://ixpmanager.example.net",
    options: "{}",
  },
  {
    value: "birdseye",
    label: "Birdseye",
    description: "Route-server session state, accepted/filtered prefixes, IRR and RPKI.",
    placeholder: "https://rs1.example.net/api",
    options: '{\n  "route_servers": []\n}',
  },
];

function CreateIntegrationDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (o: boolean) => void }) {
  const qc = useQueryClient();
  const [kind, setKind] = React.useState<IntegrationKind>("netbox");
  const [name, setName] = React.useState("");
  const [baseUrl, setBaseUrl] = React.useState("");
  const [token, setToken] = React.useState("");
  const [options, setOptions] = React.useState("{}");
  const [enabled, setEnabled] = React.useState(true);
  const [errors, setErrors] = React.useState<Record<string, string>>({});
  const meta = KINDS.find((k) => k.value === kind)!;

  useOnOpen(open, () => {
    setKind("netbox");
    setName("");
    setBaseUrl("");
    setToken("");
    setOptions(KINDS[0].options);
    setEnabled(true);
    setErrors({});
  });

  const create = useMutation({
    mutationFn: (body: IntegrationIn) => api.post<Integration>("/integrations", body),
    onSuccess: (i) => {
      toast.success(`${i.name} added`, "Run a sync to import data.");
      void qc.invalidateQueries({ queryKey: ["integrations"] });
      onOpenChange(false);
    },
    onError: (e) => toast.error("Could not add integration", errorMessage(e)),
  });

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    const errs: Record<string, string> = {};
    if (!name.trim()) errs.name = "Name is required";
    try {
      const u = new URL(baseUrl.trim());
      if (!/^https?:$/.test(u.protocol)) errs.base_url = "Must be an http(s) URL";
    } catch {
      errs.base_url = "Enter a valid URL";
    }
    let opts: Record<string, unknown> = {};
    try {
      const parsed: unknown = JSON.parse(options || "{}");
      if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) throw new Error("must be an object");
      opts = parsed as Record<string, unknown>;
    } catch (err) {
      errs.options = `Invalid JSON: ${err instanceof Error ? err.message : ""}`;
    }
    setErrors(errs);
    if (Object.keys(errs).length) return;
    create.mutate({ kind, name: name.trim(), base_url: baseUrl.trim(), token: token || null, options: opts, enabled });
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-xl">
        <DialogHeader>
          <DialogTitle>Add integration</DialogTitle>
          <DialogDescription>{meta.description}</DialogDescription>
        </DialogHeader>
        <form onSubmit={submit} className="grid gap-3" noValidate>
          <div className="grid gap-3 sm:grid-cols-2">
            <Field label="Type" htmlFor="ikind">
              <SimpleSelect
                id="ikind"
                value={kind}
                onValueChange={(v) => {
                  setKind(v as IntegrationKind);
                  setOptions(KINDS.find((k) => k.value === v)?.options ?? "{}");
                }}
                options={KINDS.map((k) => ({ value: k.value, label: k.label }))}
              />
            </Field>
            <Field label="Name" htmlFor="iname" required error={errors.name}>
              <Input id="iname" value={name} onChange={(e) => setName(e.target.value)} placeholder={`${meta.label} production`} />
            </Field>
          </div>
          <Field label="Base URL" htmlFor="iurl" required error={errors.base_url}>
            <Input id="iurl" value={baseUrl} onChange={(e) => setBaseUrl(e.target.value)} placeholder={meta.placeholder} className="font-mono" />
          </Field>
          <Field label="API token" htmlFor="itoken" hint="Stored encrypted; never shown again">
            <Input id="itoken" type="password" autoComplete="off" value={token} onChange={(e) => setToken(e.target.value)} />
          </Field>
          <Field label="Options (JSON)" htmlFor="iopts" error={errors.options}>
            <Textarea id="iopts" rows={4} value={options} onChange={(e) => setOptions(e.target.value)} className="font-mono text-xs" spellCheck={false} />
          </Field>
          <Checkbox label="Enabled (included in scheduled syncs)" checked={enabled} onCheckedChange={setEnabled} />
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
              Cancel
            </Button>
            <Button type="submit" loading={create.isPending}>
              Add integration
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

export default function IntegrationsPage() {
  const { can } = useAuth();
  const qc = useQueryClient();
  const [open, setOpen] = React.useState(false);
  const confirm = useConfirm<Integration>();
  const writable = can("integrations:write");
  const q = useQuery({ queryKey: ["integrations"], queryFn: () => api.get<Integration[]>("/integrations"), refetchInterval: 30_000 });

  const sync = useMutation({
    mutationFn: (i: Integration) => api.post<Record<string, unknown>>(`/integrations/${i.id}/sync?run_async=true`),
    onSuccess: (r, i) => {
      toast.success(`Sync started for ${i.name}`, typeof r.task_id === "string" ? `Task ${r.task_id.slice(0, 8)}` : undefined);
      setTimeout(() => void qc.invalidateQueries({ queryKey: ["integrations"] }), 5000);
    },
    onError: (e) => toast.error("Sync failed", errorMessage(e)),
  });
  const del = useMutation({
    mutationFn: (i: Integration) => api.delete(`/integrations/${i.id}`),
    onSuccess: () => {
      toast.success("Integration removed");
      confirm.close();
      void qc.invalidateQueries({ queryKey: ["integrations"] });
    },
  });

  const list = q.data ?? [];
  return (
    <>
      <PageHeader
        title="Integrations"
        description="Synchronise inventory and peering data from NetBox, IXP Manager and birdseye."
        actions={
          writable ? (
            <Button onClick={() => setOpen(true)}>
              <Plus /> Add integration
            </Button>
          ) : null
        }
      />
      {q.isLoading ? (
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">{Array.from({ length: 3 }).map((_, i) => <Skeleton key={i} className="h-56" />)}</div>
      ) : q.error ? (
        <Card><ErrorState error={q.error} onRetry={() => void q.refetch()} /></Card>
      ) : list.length === 0 ? (
        <Card>
          <EmptyState icon={PlugZap} title="No integrations configured" description="Connect NetBox to import your inventory, IXP Manager for members and birdseye for route-server state." />
        </Card>
      ) : (
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {list.map((i) => (
            <Card key={i.id} className="flex flex-col">
              <CardHeader className="flex-row items-start justify-between gap-2">
                <div className="min-w-0">
                  <CardTitle className="flex items-center gap-2">
                    {i.name}
                    <Badge variant="outline">{KINDS.find((k) => k.value === i.kind)?.label ?? i.kind}</Badge>
                  </CardTitle>
                  <CardDescription className="truncate font-mono">{i.base_url}</CardDescription>
                </div>
                {i.enabled ? <Badge variant="success">Enabled</Badge> : <Badge variant="muted">Disabled</Badge>}
              </CardHeader>
              <CardContent className="grid flex-1 gap-3">
                <KeyValue
                  items={[
                    ["Last sync", <RelativeTime key="l" value={i.last_sync_at} />],
                    ["Status", i.last_sync_status ? <StatusBadge key="s" status={i.last_sync_status} /> : "never synced"],
                  ]}
                />
                {i.last_sync_detail ? <JsonView value={i.last_sync_detail} className="max-h-32" /> : null}
              </CardContent>
              {writable ? (
                <div className="flex gap-2 border-t p-3">
                  <Button size="sm" variant="outline" onClick={() => sync.mutate(i)} loading={sync.isPending && sync.variables?.id === i.id}>
                    <RefreshCw /> Sync now
                  </Button>
                  <Button size="sm" variant="ghost" className="ml-auto" onClick={() => confirm.ask(i)} aria-label={`Delete ${i.name}`}>
                    <Trash2 />
                  </Button>
                </div>
              ) : null}
            </Card>
          ))}
        </div>
      )}
      <CreateIntegrationDialog open={open} onOpenChange={setOpen} />
      <ConfirmDialog
        open={confirm.open}
        onOpenChange={confirm.onOpenChange}
        title={`Delete ${confirm.target?.name ?? ""}?`}
        description="Imported objects stay in place; future syncs stop."
        destructive
        confirmLabel="Delete"
        loading={del.isPending}
        onConfirm={() => confirm.target && del.mutate(confirm.target)}
      />
    </>
  );
}
