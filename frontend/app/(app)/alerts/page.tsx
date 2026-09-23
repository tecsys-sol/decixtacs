"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { Bell, BellRing, Check, Plus, Radio, Send, Trash2, Workflow } from "lucide-react";
import * as React from "react";

import { ConfirmDialog, useConfirm } from "@/components/common/confirm-dialog";
import { EmptyState } from "@/components/common/empty-state";
import { Field } from "@/components/common/field";
import { FilterBar } from "@/components/common/filter-bar";
import { PageHeader } from "@/components/common/page-header";
import { Pagination } from "@/components/common/pagination";
import { RelativeTime } from "@/components/common/relative-time";
import { StatusBadge } from "@/components/common/status-badge";
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
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useAuth } from "@/hooks/use-auth";
import { toast } from "@/hooks/use-toast";
import { useOnOpen } from "@/hooks/use-reset";
import { useUrlState } from "@/hooks/use-url-state";
import { api, errorMessage } from "@/lib/api";
import { PAGE_SIZE, SEVERITIES } from "@/lib/constants";
import { ALERT_EVENT_TYPES, type Alert, type AlertChannel, type AlertRule, type Page } from "@/lib/types";
import { humanize } from "@/lib/utils";

const CHANNEL_KINDS = [
  { value: "email", label: "Email", placeholder: "noc@example.net" },
  { value: "slack", label: "Slack webhook", placeholder: "https://hooks.slack.com/services/…" },
  { value: "teams", label: "Microsoft Teams webhook", placeholder: "https://…webhook.office.com/…" },
  { value: "webhook", label: "Generic webhook", placeholder: "https://alerts.example.net/hook" },
];

function AlertsList() {
  const qc = useQueryClient();
  const [f, setF] = useUrlState({ event_type: "", severity: "", open: "1", offset: "0" });
  const offset = Number(f.offset) || 0;
  const q = useQuery({
    queryKey: ["alerts", "list", f],
    queryFn: () =>
      api.get<Page<Alert>>("/alerts", {
        event_type: f.event_type,
        severity: f.severity,
        unacknowledged: f.open === "1" ? true : undefined,
        limit: PAGE_SIZE,
        offset,
      }),
    placeholderData: (p) => p,
    refetchInterval: 30_000,
  });
  const ack = useMutation({
    mutationFn: (a: Alert) => api.post<Alert>(`/alerts/${a.id}/ack`),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["alerts"] });
      void qc.invalidateQueries({ queryKey: ["dashboard"] });
    },
  });
  const items = q.data?.items ?? [];

  return (
    <Card>
      <FilterBar>
        <SimpleSelect aria-label="Event type" value={f.event_type} onValueChange={(v) => setF({ event_type: v, offset: "0" })} allowEmpty emptyLabel="All events" className="w-56" options={ALERT_EVENT_TYPES.map((e) => ({ value: e, label: humanize(e) }))} />
        <SimpleSelect aria-label="Severity" value={f.severity} onValueChange={(v) => setF({ severity: v, offset: "0" })} allowEmpty emptyLabel="Any severity" className="w-40" options={["info", ...SEVERITIES].map((s) => ({ value: s, label: humanize(s) }))} />
        <div className="flex h-9 items-center">
          <Checkbox label="Unacknowledged only" checked={f.open === "1"} onCheckedChange={(c) => setF({ open: c ? "1" : "0", offset: "0" })} />
        </div>
      </FilterBar>
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Raised</TableHead>
            <TableHead>Severity</TableHead>
            <TableHead>Event</TableHead>
            <TableHead className="w-full">Alert</TableHead>
            <TableHead>Delivered</TableHead>
            <TableHead />
          </TableRow>
        </TableHeader>
        <TableBody>
          <TableState cols={6} isLoading={q.isLoading} error={q.error} onRetry={() => void q.refetch()} isEmpty={items.length === 0} empty={<EmptyState icon={Bell} title={f.open === "1" ? "No open alerts" : "No alerts"} description="All quiet." />} />
          {items.map((a) => (
            <TableRow key={a.id} className={a.acknowledged_at ? "opacity-60" : undefined}>
              <TableCell className="whitespace-nowrap text-xs">
                <RelativeTime value={a.created_at} />
              </TableCell>
              <TableCell>
                <StatusBadge status={a.severity} dot={false} />
              </TableCell>
              <TableCell>
                <Badge variant="outline">{humanize(a.event_type)}</Badge>
              </TableCell>
              <TableCell className="max-w-0">
                <p className="truncate font-medium">{a.title}</p>
                {a.body ? <p className="truncate text-xs text-muted-foreground" title={a.body}>{a.body}</p> : null}
                {a.device_id ? (
                  <Link href={`/devices/${a.device_id}`} className="text-xs text-primary hover:underline">
                    View device
                  </Link>
                ) : null}
              </TableCell>
              <TableCell className="text-xs tabular">{a.delivered.length} channel(s)</TableCell>
              <TableCell className="whitespace-nowrap">
                {a.acknowledged_at ? (
                  <span className="text-xs text-muted-foreground">
                    acked <RelativeTime value={a.acknowledged_at} />
                  </span>
                ) : (
                  <Button size="xs" variant="outline" onClick={() => ack.mutate(a)} loading={ack.isPending && ack.variables?.id === a.id}>
                    <Check /> Acknowledge
                  </Button>
                )}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
      {q.data ? <Pagination total={q.data.total} limit={PAGE_SIZE} offset={offset} onChange={(o) => setF({ offset: String(o) })} /> : null}
    </Card>
  );
}

function ChannelsTab() {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["alerts", "channels"], queryFn: () => api.get<AlertChannel[]>("/alerts/channels") });
  const [open, setOpen] = React.useState(false);
  const [f, setF] = React.useState({ name: "", kind: "email", target: "", enabled: true });
  const confirm = useConfirm<AlertChannel>();
  useOnOpen(open, () => {
    setF({ name: "", kind: "email", target: "", enabled: true });
  });

  const create = useMutation({
    mutationFn: () => api.post<AlertChannel>("/alerts/channels", { ...f, name: f.name.trim(), target: f.target.trim() }),
    onSuccess: () => {
      toast.success("Channel created");
      setOpen(false);
      void qc.invalidateQueries({ queryKey: ["alerts", "channels"] });
    },
    onError: (e) => toast.error("Could not create channel", errorMessage(e)),
  });
  const test = useMutation({
    mutationFn: (c: AlertChannel) => api.post(`/alerts/channels/${c.id}/test`),
    onSuccess: (_r, c) => toast.success(`Test alert sent via ${c.name}`),
    onError: (e) => toast.error("Test delivery failed", errorMessage(e)),
  });
  const del = useMutation({
    mutationFn: (c: AlertChannel) => api.delete(`/alerts/channels/${c.id}`),
    onSuccess: () => {
      toast.success("Channel deleted");
      confirm.close();
      void qc.invalidateQueries({ queryKey: ["alerts", "channels"] });
    },
  });
  const kindMeta = CHANNEL_KINDS.find((k) => k.value === f.kind);
  const list = q.data ?? [];

  return (
    <Card>
      <CardHeader className="flex-row items-center justify-between">
        <div>
          <CardTitle>Notification channels</CardTitle>
          <CardDescription>Targets are stored encrypted.</CardDescription>
        </div>
        <Button size="sm" onClick={() => setOpen(true)}>
          <Plus /> Add channel
        </Button>
      </CardHeader>
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead className="w-full">Name</TableHead>
            <TableHead>Kind</TableHead>
            <TableHead>State</TableHead>
            <TableHead />
          </TableRow>
        </TableHeader>
        <TableBody>
          <TableState cols={4} isLoading={q.isLoading} error={q.error} onRetry={() => void q.refetch()} isEmpty={list.length === 0} empty={<EmptyState icon={Radio} title="No channels" />} />
          {list.map((c) => (
            <TableRow key={c.id}>
              <TableCell className="font-medium">{c.name}</TableCell>
              <TableCell>
                <Badge variant="outline">{c.kind}</Badge>
              </TableCell>
              <TableCell>{c.enabled ? <Badge variant="success">Enabled</Badge> : <Badge variant="muted">Disabled</Badge>}</TableCell>
              <TableCell className="whitespace-nowrap">
                <div className="flex justify-end gap-1">
                  <Button size="xs" variant="outline" onClick={() => test.mutate(c)} loading={test.isPending && test.variables?.id === c.id}>
                    <Send /> Test
                  </Button>
                  <Button size="icon-sm" variant="ghost" aria-label={`Delete ${c.name}`} onClick={() => confirm.ask(c)}>
                    <Trash2 />
                  </Button>
                </div>
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Add notification channel</DialogTitle>
            <DialogDescription>Where alert rules deliver notifications.</DialogDescription>
          </DialogHeader>
          <form
            className="grid gap-3"
            onSubmit={(e) => {
              e.preventDefault();
              create.mutate();
            }}
          >
            <Field label="Name" htmlFor="cname" required>
              <Input id="cname" value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} placeholder="NOC Slack" />
            </Field>
            <Field label="Kind" htmlFor="ckind">
              <SimpleSelect id="ckind" value={f.kind} onValueChange={(v) => setF({ ...f, kind: v })} options={CHANNEL_KINDS} />
            </Field>
            <Field label={f.kind === "email" ? "Recipient" : "Webhook URL"} htmlFor="ctarget" required>
              <Input id="ctarget" value={f.target} onChange={(e) => setF({ ...f, target: e.target.value })} placeholder={kindMeta?.placeholder} className="font-mono text-xs" />
            </Field>
            <Checkbox label="Enabled" checked={f.enabled} onCheckedChange={(c) => setF({ ...f, enabled: c })} />
            <DialogFooter>
              <Button type="button" variant="outline" onClick={() => setOpen(false)}>
                Cancel
              </Button>
              <Button type="submit" loading={create.isPending} disabled={!f.name.trim() || !f.target.trim()}>
                Create channel
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
      <ConfirmDialog open={confirm.open} onOpenChange={confirm.onOpenChange} title={`Delete ${confirm.target?.name ?? ""}?`} destructive confirmLabel="Delete" loading={del.isPending} onConfirm={() => confirm.target && del.mutate(confirm.target)} />
    </Card>
  );
}

function RulesTab() {
  const qc = useQueryClient();
  const rules = useQuery({ queryKey: ["alerts", "rules"], queryFn: () => api.get<AlertRule[]>("/alerts/rules") });
  const channels = useQuery({ queryKey: ["alerts", "channels"], queryFn: () => api.get<AlertChannel[]>("/alerts/channels") });
  const [open, setOpen] = React.useState(false);
  const [f, setF] = React.useState({ name: "", event_type: "backup_failed", min_severity: "low", channel_ids: [] as string[], throttle_minutes: 15, enabled: true });
  const confirm = useConfirm<AlertRule>();
  useOnOpen(open, () => {
    setF({ name: "", event_type: "backup_failed", min_severity: "low", channel_ids: [], throttle_minutes: 15, enabled: true });
  });

  const create = useMutation({
    mutationFn: () => api.post<AlertRule>("/alerts/rules", { ...f, name: f.name.trim(), filters: {} }),
    onSuccess: () => {
      toast.success("Rule created");
      setOpen(false);
      void qc.invalidateQueries({ queryKey: ["alerts", "rules"] });
    },
    onError: (e) => toast.error("Could not create rule", errorMessage(e)),
  });
  const del = useMutation({
    mutationFn: (r: AlertRule) => api.delete(`/alerts/rules/${r.id}`),
    onSuccess: () => {
      toast.success("Rule deleted");
      confirm.close();
      void qc.invalidateQueries({ queryKey: ["alerts", "rules"] });
    },
  });
  const chName = new Map((channels.data ?? []).map((c) => [c.id, c.name]));
  const list = rules.data ?? [];

  return (
    <Card>
      <CardHeader className="flex-row items-center justify-between">
        <div>
          <CardTitle>Alert rules</CardTitle>
          <CardDescription>Route platform events to channels with throttling.</CardDescription>
        </div>
        <Button size="sm" onClick={() => setOpen(true)} disabled={!channels.data?.length} title={channels.data?.length ? undefined : "Create a channel first"}>
          <Plus /> Add rule
        </Button>
      </CardHeader>
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Name</TableHead>
            <TableHead>Event</TableHead>
            <TableHead>Min severity</TableHead>
            <TableHead className="w-full">Channels</TableHead>
            <TableHead>Throttle</TableHead>
            <TableHead>State</TableHead>
            <TableHead />
          </TableRow>
        </TableHeader>
        <TableBody>
          <TableState cols={7} isLoading={rules.isLoading} error={rules.error} onRetry={() => void rules.refetch()} isEmpty={list.length === 0} empty={<EmptyState icon={Workflow} title="No alert rules" />} />
          {list.map((r) => (
            <TableRow key={r.id}>
              <TableCell className="font-medium">{r.name}</TableCell>
              <TableCell>
                <Badge variant="outline">{humanize(r.event_type)}</Badge>
              </TableCell>
              <TableCell>
                <StatusBadge status={r.min_severity} dot={false} />
              </TableCell>
              <TableCell className="text-xs">{r.channel_ids.map((c) => chName.get(String(c)) ?? "?").join(", ")}</TableCell>
              <TableCell className="whitespace-nowrap text-xs">{r.throttle_minutes} min</TableCell>
              <TableCell>{r.enabled ? <Badge variant="success">Enabled</Badge> : <Badge variant="muted">Disabled</Badge>}</TableCell>
              <TableCell>
                <Button size="icon-sm" variant="ghost" aria-label={`Delete ${r.name}`} onClick={() => confirm.ask(r)}>
                  <Trash2 />
                </Button>
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Add alert rule</DialogTitle>
            <DialogDescription>Notify channels when an event of at least the given severity occurs.</DialogDescription>
          </DialogHeader>
          <form
            className="grid gap-3"
            onSubmit={(e) => {
              e.preventDefault();
              create.mutate();
            }}
          >
            <Field label="Name" htmlFor="rname" required>
              <Input id="rname" value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} placeholder="Backup failures to NOC" />
            </Field>
            <div className="grid gap-3 sm:grid-cols-3">
              <Field label="Event" htmlFor="revent" className="sm:col-span-2">
                <SimpleSelect id="revent" value={f.event_type} onValueChange={(v) => setF({ ...f, event_type: v })} options={ALERT_EVENT_TYPES.map((e) => ({ value: e, label: humanize(e) }))} />
              </Field>
              <Field label="Min severity" htmlFor="rsev">
                <SimpleSelect id="rsev" value={f.min_severity} onValueChange={(v) => setF({ ...f, min_severity: v })} options={["info", ...SEVERITIES].map((s) => ({ value: s, label: humanize(s) }))} />
              </Field>
            </div>
            <Field label="Channels" required>
              <div className="flex flex-wrap gap-x-4 gap-y-2 rounded-md border p-2">
                {(channels.data ?? []).map((c) => (
                  <Checkbox
                    key={c.id}
                    label={c.name}
                    checked={f.channel_ids.includes(c.id)}
                    onCheckedChange={(on) => setF({ ...f, channel_ids: on ? [...f.channel_ids, c.id] : f.channel_ids.filter((x) => x !== c.id) })}
                  />
                ))}
              </div>
            </Field>
            <Field label="Throttle (minutes)" htmlFor="rthr" hint="Suppress repeats of the same alert within this window">
              <Input id="rthr" type="number" min={0} value={f.throttle_minutes} onChange={(e) => setF({ ...f, throttle_minutes: Number(e.target.value) })} className="w-32" />
            </Field>
            <Checkbox label="Enabled" checked={f.enabled} onCheckedChange={(c) => setF({ ...f, enabled: c })} />
            <DialogFooter>
              <Button type="button" variant="outline" onClick={() => setOpen(false)}>
                Cancel
              </Button>
              <Button type="submit" loading={create.isPending} disabled={!f.name.trim() || f.channel_ids.length === 0}>
                Create rule
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
      <ConfirmDialog open={confirm.open} onOpenChange={confirm.onOpenChange} title={`Delete ${confirm.target?.name ?? ""}?`} destructive confirmLabel="Delete" loading={del.isPending} onConfirm={() => confirm.target && del.mutate(confirm.target)} />
    </Card>
  );
}

export default function AlertsPage() {
  const { can } = useAuth();
  const [f, setF] = useUrlState({ tab: "alerts" });
  const manage = can("alerts:write");
  return (
    <>
      <PageHeader title="Alerts" description="Operational alerts and how they are delivered." />
      <Tabs value={manage ? f.tab : "alerts"} onValueChange={(v) => setF({ tab: v })}>
        <TabsList>
          <TabsTrigger value="alerts"><BellRing /> Alerts</TabsTrigger>
          {manage ? <TabsTrigger value="channels"><Radio /> Channels</TabsTrigger> : null}
          {manage ? <TabsTrigger value="rules"><Workflow /> Rules</TabsTrigger> : null}
        </TabsList>
        <TabsContent value="alerts"><AlertsList /></TabsContent>
        {manage ? <TabsContent value="channels"><ChannelsTab /></TabsContent> : null}
        {manage ? <TabsContent value="rules"><RulesTab /></TabsContent> : null}
      </Tabs>
    </>
  );
}
