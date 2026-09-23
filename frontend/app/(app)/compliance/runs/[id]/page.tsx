"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useParams } from "next/navigation";
import { CheckCircle2, ChevronDown, ChevronRight, Search } from "lucide-react";
import * as React from "react";

import { EmptyState } from "@/components/common/empty-state";
import { ErrorState } from "@/components/common/error-state";
import { KeyValue } from "@/components/common/field";
import { PageHeader } from "@/components/common/page-header";
import { StatusBadge } from "@/components/common/status-badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { api } from "@/lib/api";
import { scoreColor } from "@/lib/status";
import type { ComplianceRunDetail } from "@/lib/types";
import { cn, formatDateTime } from "@/lib/utils";

const SEV_ORDER: Record<string, number> = { critical: 0, high: 1, medium: 2, low: 3 };

export default function ComplianceRunPage() {
  const { id } = useParams<{ id: string }>();
  const [filter, setFilter] = React.useState("");
  const [expanded, setExpanded] = React.useState<Set<string>>(new Set());
  const q = useQuery({ queryKey: ["compliance", "run", id], queryFn: () => api.get<ComplianceRunDetail>(`/compliance/runs/${id}`) });

  const byRule = React.useMemo(() => {
    const m = new Map<string, { rule: string; severity: string; items: ComplianceRunDetail["failures"] }>();
    for (const f of q.data?.failures ?? []) {
      const g = m.get(f.rule) ?? { rule: f.rule, severity: f.severity, items: [] };
      g.items.push(f);
      m.set(f.rule, g);
    }
    return [...m.values()].sort((a, b) => (SEV_ORDER[a.severity] ?? 9) - (SEV_ORDER[b.severity] ?? 9) || b.items.length - a.items.length);
  }, [q.data]);

  if (q.isLoading) return <Skeleton className="h-96" />;
  if (q.error || !q.data) return <ErrorState error={q.error} onRetry={() => void q.refetch()} />;
  const { run, devices } = q.data;
  const shown = devices.filter((d) => !filter || d.hostname.toLowerCase().includes(filter.toLowerCase()));

  const toggle = (rule: string) =>
    setExpanded((s) => {
      const n = new Set(s);
      if (n.has(rule)) n.delete(rule);
      else n.add(rule);
      return n;
    });

  return (
    <>
      <PageHeader
        breadcrumbs={[{ label: "Compliance", href: "/compliance" }, { label: "Run" }]}
        title={`Compliance run · ${formatDateTime(run.started_at)}`}
        description={`${run.devices_checked} devices checked · ${q.data.failures.length} failed checks`}
      />
      <div className="grid gap-4 lg:grid-cols-3">
        <Card>
          <CardHeader>
            <CardTitle>Summary</CardTitle>
          </CardHeader>
          <CardContent className="grid gap-4">
            <p className={cn("text-5xl font-semibold tabular", scoreColor(run.score))}>{run.score == null ? "—" : `${run.score.toFixed(1)}%`}</p>
            <KeyValue
              items={[
                ["Started", formatDateTime(run.started_at)],
                ["Finished", run.finished_at ? formatDateTime(run.finished_at) : <StatusBadge key="r" status="running" />],
                ["Devices", run.devices_checked],
                ["Failing rules", byRule.length],
              ]}
            />
          </CardContent>
        </Card>

        <Card className="lg:col-span-2">
          <CardHeader>
            <CardTitle>Failures by rule</CardTitle>
            <CardDescription>Click a rule to see affected devices</CardDescription>
          </CardHeader>
          <CardContent className="px-0">
            {byRule.length ? (
              <ul className="divide-y">
                {byRule.map((g) => {
                  const open = expanded.has(g.rule);
                  return (
                    <li key={g.rule}>
                      <button type="button" className="flex w-full items-center gap-2 px-4 py-2 text-left text-sm hover:bg-muted/40" onClick={() => toggle(g.rule)} aria-expanded={open}>
                        {open ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
                        <span className="flex-1 font-medium">{g.rule}</span>
                        <StatusBadge status={g.severity} dot={false} />
                        <span className="w-20 text-right text-xs text-muted-foreground tabular">{g.items.length} device(s)</span>
                      </button>
                      {open ? (
                        <ul className="border-t bg-muted/20 px-10 py-2 text-xs">
                          {g.items.map((f, i) => (
                            <li key={i} className="flex gap-3 py-0.5">
                              <span className="w-44 shrink-0 truncate font-mono">{f.device}</span>
                              <span className="text-muted-foreground">{f.detail}</span>
                            </li>
                          ))}
                        </ul>
                      ) : null}
                    </li>
                  );
                })}
              </ul>
            ) : (
              <EmptyState icon={CheckCircle2} title="No failures" description="Every device passed every rule." />
            )}
          </CardContent>
        </Card>

        <Card className="lg:col-span-3">
          <CardHeader className="flex-row items-center justify-between gap-2">
            <CardTitle>Devices</CardTitle>
            <div className="relative w-64">
              <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
              <Input value={filter} onChange={(e) => setFilter(e.target.value)} placeholder="Filter devices" className="h-8 pl-8" aria-label="Filter devices" />
            </div>
          </CardHeader>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Device</TableHead>
                <TableHead className="w-full">Score</TableHead>
                <TableHead>Passed</TableHead>
                <TableHead>Failed</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {shown.map((d) => (
                <TableRow key={d.device_id}>
                  <TableCell className="whitespace-nowrap">
                    <Link href={`/devices/${d.device_id}?tab=compliance`} className="font-medium hover:underline">
                      {d.hostname}
                    </Link>
                  </TableCell>
                  <TableCell>
                    <div className="flex items-center gap-2">
                      <div className="h-1.5 w-40 rounded-full bg-muted">
                        <div className="h-full rounded-full" style={{ width: `${d.score}%`, background: "var(--series-1)" }} />
                      </div>
                      <span className={cn("text-sm font-medium tabular", scoreColor(d.score))}>{d.score.toFixed(1)}%</span>
                    </div>
                  </TableCell>
                  <TableCell className="tabular text-success">{d.passed}</TableCell>
                  <TableCell className={cn("tabular", d.failed ? "text-destructive" : "text-muted-foreground")}>{d.failed}</TableCell>
                </TableRow>
              ))}
              {shown.length === 0 ? (
                <TableRow>
                  <TableCell colSpan={4} className="py-8 text-center text-sm text-muted-foreground">
                    No devices
                  </TableCell>
                </TableRow>
              ) : null}
            </TableBody>
          </Table>
        </Card>
      </div>
    </>
  );
}
