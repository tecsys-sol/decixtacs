"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { ClipboardCheck, ListChecks, Pencil, Play, Plus, Trash2 } from "lucide-react";
import * as React from "react";

import { Chart, useChartMode } from "@/components/charts/chart";
import { ChartBody, ChartCard } from "@/components/common/chart-card";
import { RunCharts } from "@/components/compliance/run-charts";
import { RuleDialog } from "@/components/compliance/rule-dialog";
import { ConfirmDialog, useConfirm } from "@/components/common/confirm-dialog";
import { EmptyState } from "@/components/common/empty-state";
import { PageHeader } from "@/components/common/page-header";
import { RelativeTime } from "@/components/common/relative-time";
import { StatusBadge } from "@/components/common/status-badge";
import { TableState } from "@/components/common/table-skeleton";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useAuth } from "@/hooks/use-auth";
import { toast } from "@/hooks/use-toast";
import { useUrlState } from "@/hooks/use-url-state";
import { api } from "@/lib/api";
import { scoreColor } from "@/lib/status";
import { barOption, gaugeOption, lineOption, palette } from "@/lib/charts";
import type { ComplianceRule, ComplianceRun, ComplianceRunDetail } from "@/lib/types";
import { cn, formatDate, formatDateTime, formatDuration, humanize, parseDate } from "@/lib/utils";

function RunsPanel() {
  const router = useRouter();
  const mode = useChartMode();
  const runs = useQuery({ queryKey: ["compliance", "runs", 90], queryFn: () => api.get<ComplianceRun[]>("/compliance/runs", { limit: 90 }) });
  const list = React.useMemo(() => runs.data ?? [], [runs.data]);
  const completed = React.useMemo(() => list.filter((r) => r.score !== null), [list]);
  const latest = completed[0];
  const previous = completed[1];
  const detail = useQuery({
    queryKey: ["compliance", "run", latest?.id],
    queryFn: () => api.get<ComplianceRunDetail>(`/compliance/runs/${latest?.id}`),
    enabled: !!latest,
  });
  const chart = React.useMemo(() => [...completed].reverse(), [completed]);
  const delta = latest?.score != null && previous?.score != null ? latest.score - previous.score : null;

  const gauge = React.useMemo(
    () =>
      gaugeOption(
        {
          value: latest?.score == null ? null : Math.round(latest.score * 10) / 10,
          label: delta == null ? `${latest?.devices_checked ?? 0} devices checked` : `${delta >= 0 ? "+" : "−"}${Math.abs(delta).toFixed(1)} vs previous run`,
          gradient: true,
        },
        mode,
      ),
    [latest, delta, mode],
  );
  const trend = React.useMemo(
    () =>
      lineOption(
        {
          categories: chart.map((r) => formatDate(r.started_at)),
          series: [
            { name: "Score", data: chart.map((r) => Math.round((r.score ?? 0) * 10) / 10) },
          ],
          area: true,
          min: 0,
          max: 100,
          format: (v) => `${v}%`,
          axisFormat: (v) => `${v}%`,
        },
        mode,
      ),
    [chart, mode],
  );
  const checked = React.useMemo(
    () =>
      barOption(
        {
          categories: chart.map((r) => formatDate(r.started_at)),
          series: [{ name: "Devices checked", data: chart.map((r) => r.devices_checked), color: palette(mode)[2] }],
          barWidth: 14,
        },
        mode,
      ),
    [chart, mode],
  );

  return (
    <div className="grid gap-4">
      <div className="grid gap-4 xl:grid-cols-[1fr_2fr]">
        <ChartCard title="Compliance score" description={latest ? <>Latest run · <RelativeTime value={latest.started_at} /></> : "No completed runs"}>
          <ChartBody loading={runs.isLoading} error={runs.error} empty={!latest} emptyTitle="No runs yet" emptyDescription="Run the checks to get a fleet score." emptyIcon={ClipboardCheck} emptyArt="default" height={220}>
            <Chart option={gauge} height={220} ariaLabel={`Latest compliance score ${latest?.score?.toFixed(1) ?? ""}`} />
          </ChartBody>
        </ChartCard>
        <ChartCard title="Score history" description={`Fleet compliance per run · ${completed.length} run${completed.length === 1 ? "" : "s"}`} delay={1}>
          <ChartBody loading={runs.isLoading} error={runs.error} empty={!chart.length} emptyTitle="No runs yet" emptyIcon={ClipboardCheck} height={220}>
            <Chart
              option={trend}
              height={220}
              ariaLabel="Compliance score per run"
              onEvents={{ click: (p) => { const r = chart[(p as { dataIndex: number }).dataIndex]; if (r) router.push(`/compliance/runs/${r.id}`); } }}
            />
          </ChartBody>
        </ChartCard>
      </div>
      <RunCharts detail={latest ? detail.data : undefined} mode={mode} delay={2} />
      {chart.length > 1 ? (
        <ChartCard title="Coverage per run" description="Devices evaluated in each run" delay={5}>
          <Chart option={checked} height={180} ariaLabel="Devices checked per run" />
        </ChartCard>
      ) : null}
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
                        <div className="h-1.5 w-40 rounded-full bg-secondary">
                          <div className="h-full rounded-full bg-primary" style={{ width: `${r.score}%` }} />
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
