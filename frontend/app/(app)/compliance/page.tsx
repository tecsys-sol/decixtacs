"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { ClipboardCheck, ListChecks, Pencil, Play, Plus, Trash2 } from "lucide-react";
import * as React from "react";
import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import { CHART, ChartTooltip } from "@/components/charts/chart-kit";
import { RuleDialog } from "@/components/compliance/rule-dialog";
import { ConfirmDialog, useConfirm } from "@/components/common/confirm-dialog";
import { EmptyState } from "@/components/common/empty-state";
import { PageHeader } from "@/components/common/page-header";
import { RelativeTime } from "@/components/common/relative-time";
import { StatusBadge } from "@/components/common/status-badge";
import { TableState } from "@/components/common/table-skeleton";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useAuth } from "@/hooks/use-auth";
import { toast } from "@/hooks/use-toast";
import { useUrlState } from "@/hooks/use-url-state";
import { api } from "@/lib/api";
import { scoreColor } from "@/lib/status";
import type { ComplianceRule, ComplianceRun } from "@/lib/types";
import { cn, formatDate, formatDateTime, formatDuration, humanize, parseDate } from "@/lib/utils";

function RunsPanel() {
  const router = useRouter();
  const runs = useQuery({ queryKey: ["compliance", "runs", 90], queryFn: () => api.get<ComplianceRun[]>("/compliance/runs", { limit: 90 }) });
  const list = runs.data ?? [];
  const latest = list.find((r) => r.score !== null);
  const chart = [...list].reverse().filter((r) => r.score !== null).map((r) => ({ t: r.started_at, score: Math.round((r.score ?? 0) * 10) / 10 }));

  return (
    <div className="grid gap-4">
      <div className="grid gap-4 lg:grid-cols-4">
        <Card>
          <CardHeader>
            <CardTitle>Latest score</CardTitle>
            <CardDescription>{latest ? <RelativeTime value={latest.started_at} /> : "No completed runs"}</CardDescription>
          </CardHeader>
          <CardContent>
            {runs.isLoading ? (
              <Skeleton className="h-12 w-28" />
            ) : (
              <>
                <p className={cn("text-5xl font-semibold tracking-tight tabular", scoreColor(latest?.score))}>
                  {latest?.score == null ? "—" : `${latest.score.toFixed(1)}%`}
                </p>
                <p className="mt-2 text-xs text-muted-foreground">{latest ? `${latest.devices_checked} devices checked` : ""}</p>
              </>
            )}
          </CardContent>
        </Card>
        <Card className="lg:col-span-3">
          <CardHeader>
            <CardTitle>Score history</CardTitle>
            <CardDescription>Fleet compliance per run</CardDescription>
          </CardHeader>
          <CardContent>
            {runs.isLoading ? (
              <Skeleton className="h-[200px]" />
            ) : chart.length ? (
              <ResponsiveContainer width="100%" height={200}>
                <LineChart data={chart} margin={{ left: -12, right: 8, top: 8 }}>
                  <CartesianGrid vertical={false} stroke={CHART.grid} />
                  <XAxis dataKey="t" tickFormatter={(v: string) => formatDate(v)} tick={CHART.tick} axisLine={false} tickLine={false} minTickGap={24} />
                  <YAxis domain={[0, 100]} unit="%" tick={CHART.tick} axisLine={false} tickLine={false} />
                  <Tooltip content={<ChartTooltip labelFormatter={(l) => formatDateTime(String(l))} valueFormatter={(v) => `${v}%`} />} />
                  <Line type="monotone" dataKey="score" name="Score" stroke={CHART.series1} strokeWidth={2} dot={chart.length < 20 ? { r: 3 } : false} activeDot={{ r: 4 }} />
                </LineChart>
              </ResponsiveContainer>
            ) : (
              <EmptyState title="No runs yet" icon={ClipboardCheck} />
            )}
          </CardContent>
        </Card>
      </div>
      <Card>
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Started</TableHead>
              <TableHead>Duration</TableHead>
              <TableHead>Devices</TableHead>
              <TableHead className="w-full">Score</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            <TableState cols={4} isLoading={runs.isLoading} error={runs.error} onRetry={() => void runs.refetch()} isEmpty={list.length === 0} empty={<EmptyState title="No compliance runs" icon={ClipboardCheck} />} />
            {list.map((r) => {
              const start = parseDate(r.started_at);
              const end = parseDate(r.finished_at);
              return (
                <TableRow key={r.id} className="cursor-pointer" onClick={() => router.push(`/compliance/runs/${r.id}`)}>
                  <TableCell className="whitespace-nowrap">
                    <Link href={`/compliance/runs/${r.id}`} className="text-primary hover:underline" onClick={(e) => e.stopPropagation()}>
                      {formatDateTime(r.started_at)}
                    </Link>
                  </TableCell>
                  <TableCell className="whitespace-nowrap text-xs">
                    {end && start ? formatDuration((end.getTime() - start.getTime()) / 1000) : <StatusBadge status="running" />}
                  </TableCell>
                  <TableCell className="tabular">{r.devices_checked}</TableCell>
                  <TableCell>
                    {r.score === null ? (
                      "—"
                    ) : (
                      <div className="flex items-center gap-2">
                        <div className="h-1.5 w-40 rounded-full bg-muted">
                          <div className="h-full rounded-full" style={{ width: `${r.score}%`, background: CHART.series1 }} />
                        </div>
                        <span className={cn("text-sm font-medium tabular", scoreColor(r.score))}>{r.score.toFixed(1)}%</span>
                      </div>
                    )}
                  </TableCell>
                </TableRow>
              );
            })}
          </TableBody>
        </Table>
      </Card>
    </div>
  );
}

function RulesPanel() {
  const { can } = useAuth();
  const qc = useQueryClient();
  const rules = useQuery({ queryKey: ["compliance", "rules"], queryFn: () => api.get<ComplianceRule[]>("/compliance/rules") });
  const [editing, setEditing] = React.useState<ComplianceRule | undefined>();
  const [open, setOpen] = React.useState(false);
  const confirm = useConfirm<ComplianceRule>();
  const writable = can("compliance:write");

  const del = useMutation({
    mutationFn: (r: ComplianceRule) => api.delete(`/compliance/rules/${r.id}`),
    onSuccess: () => {
      toast.success("Rule deleted");
      confirm.close();
      void qc.invalidateQueries({ queryKey: ["compliance", "rules"] });
    },
  });

  const list = rules.data ?? [];
  return (
    <Card>
      <CardHeader className="flex-row items-center justify-between">
        <div>
          <CardTitle>Rules</CardTitle>
          <CardDescription>{list.length} rule(s)</CardDescription>
        </div>
        {writable ? (
          <Button size="sm" onClick={() => { setEditing(undefined); setOpen(true); }}>
            <Plus /> New rule
          </Button>
        ) : null}
      </CardHeader>
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Name</TableHead>
            <TableHead>Type</TableHead>
            <TableHead className="w-full">Pattern</TableHead>
            <TableHead>Severity</TableHead>
            <TableHead>Scope</TableHead>
            <TableHead>State</TableHead>
            <TableHead />
          </TableRow>
        </TableHeader>
        <TableBody>
          <TableState cols={7} isLoading={rules.isLoading} error={rules.error} onRetry={() => void rules.refetch()} isEmpty={list.length === 0} empty={<EmptyState title="No rules defined" icon={ListChecks} description="Create rules such as 'NTP configured' or 'no telnet'." />} />
          {list.map((r) => (
            <TableRow key={r.id}>
              <TableCell>
                <p className="font-medium">{r.name}</p>
                {r.description ? <p className="text-xs text-muted-foreground">{r.description}</p> : null}
              </TableCell>
              <TableCell className="whitespace-nowrap text-xs">{humanize(r.rule_type)}</TableCell>
              <TableCell className="max-w-0">
                <code className="block truncate font-mono text-xs" title={r.pattern}>
                  {r.block_start ? <span className="text-muted-foreground">{r.block_start} ⟶ </span> : null}
                  {r.pattern}
                  {r.rule_type === "count_at_least" ? <span className="text-muted-foreground"> ×{r.min_count}</span> : null}
                </code>
              </TableCell>
              <TableCell>
                <StatusBadge status={r.severity} dot={false} />
              </TableCell>
              <TableCell>
                <div className="flex flex-wrap gap-1">
                  {r.platforms?.length ? r.platforms.map((p) => <Badge key={p} variant="outline">{p}</Badge>) : <span className="text-xs text-muted-foreground">all</span>}
                </div>
              </TableCell>
              <TableCell>{r.enabled ? <Badge variant="success">Enabled</Badge> : <Badge variant="muted">Disabled</Badge>}</TableCell>
              <TableCell className="whitespace-nowrap">
                {writable ? (
                  <div className="flex gap-1">
                    <Button variant="ghost" size="icon-sm" aria-label={`Edit ${r.name}`} onClick={() => { setEditing(r); setOpen(true); }}>
                      <Pencil />
                    </Button>
                    <Button variant="ghost" size="icon-sm" aria-label={`Delete ${r.name}`} onClick={() => confirm.ask(r)}>
                      <Trash2 />
                    </Button>
                  </div>
                ) : null}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
      <RuleDialog open={open} onOpenChange={setOpen} rule={editing} />
      <ConfirmDialog
        open={confirm.open}
        onOpenChange={confirm.onOpenChange}
        title={`Delete rule "${confirm.target?.name ?? ""}"?`}
        destructive
        confirmLabel="Delete"
        loading={del.isPending}
        onConfirm={() => confirm.target && del.mutate(confirm.target)}
      />
    </Card>
  );
}

export default function CompliancePage() {
  const { can } = useAuth();
  const qc = useQueryClient();
  const router = useRouter();
  const [state, setState] = useUrlState({ tab: "runs" });

  const run = useMutation({
    mutationFn: () => api.post<ComplianceRun>("/compliance/run"),
    onSuccess: (r) => {
      toast.success("Compliance run finished", r.score != null ? `Score ${r.score.toFixed(1)}% across ${r.devices_checked} devices` : undefined);
      void qc.invalidateQueries({ queryKey: ["compliance"] });
      router.push(`/compliance/runs/${r.id}`);
    },
  });

  return (
    <>
      <PageHeader
        title="Compliance"
        description="Policy-as-regex checks over stored configurations."
        actions={
          can("compliance:write") ? (
            <Button onClick={() => run.mutate()} loading={run.isPending}>
              <Play /> Run now
            </Button>
          ) : null
        }
      />
      <Tabs value={state.tab} onValueChange={(v) => setState({ tab: v })}>
        <TabsList>
          <TabsTrigger value="runs"><ClipboardCheck /> Runs</TabsTrigger>
          <TabsTrigger value="rules"><ListChecks /> Rules</TabsTrigger>
        </TabsList>
        <TabsContent value="runs"><RunsPanel /></TabsContent>
        <TabsContent value="rules"><RulesPanel /></TabsContent>
      </Tabs>
    </>
  );
}
