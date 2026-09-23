"use client";

import { useMutation, useQuery } from "@tanstack/react-query";
import { ChevronDown, ChevronRight, History, ShieldAlert, ShieldCheck } from "lucide-react";
import * as React from "react";

import { Chart, useChartTheme } from "@/components/charts/chart";
import { ChartBody, ChartCard } from "@/components/common/chart-card";
import { EmptyState } from "@/components/common/empty-state";
import { FilterBar } from "@/components/common/filter-bar";
import { JsonView } from "@/components/common/json-view";
import { PageHeader } from "@/components/common/page-header";
import { Pagination } from "@/components/common/pagination";
import { RelativeTime } from "@/components/common/relative-time";
import { StatusBadge } from "@/components/common/status-badge";
import { TableState } from "@/components/common/table-skeleton";
import { TextFilter } from "@/components/common/text-filter";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Segmented } from "@/components/ui/tabs";
import { useNow } from "@/hooks/use-now";
import { useTimeRange } from "@/hooks/use-time-range";
import { toast } from "@/hooks/use-toast";
import { useUrlState } from "@/hooks/use-url-state";
import { api, errorMessage } from "@/lib/api";
import { bucketSeries, countBy, TIME_RANGES, type TimeRange } from "@/lib/aggregate";
import { barOption } from "@/lib/charts";
import { PAGE_SIZE } from "@/lib/constants";
import type { AuditEvent, AuditVerify, Page } from "@/lib/types";
import { cn, formatDateTime, formatNumber, localInputToIso } from "@/lib/utils";

const DEFAULTS = { actor: "", action: "", target_type: "", start: "", end: "", offset: "0" };

export default function AuditPage() {
  const [f, setF] = useUrlState(DEFAULTS);
  const theme = useChartTheme();
  const now = useNow();
  const { range, setRange } = useTimeRange();
  const offset = Number(f.offset) || 0;
  const [expanded, setExpanded] = React.useState<string | null>(null);
  const [verify, setVerify] = React.useState<AuditVerify | null>(null);
  const set = (k: keyof typeof DEFAULTS) => (v: string) => setF({ [k]: v, offset: "0" });

  const q = useQuery({
    queryKey: ["audit", f],
    queryFn: () =>
      api.get<Page<AuditEvent>>("/audit", {
        actor: f.actor,
        action: f.action,
        target_type: f.target_type,
        start: localInputToIso(f.start),
        end: localInputToIso(f.end),
        limit: PAGE_SIZE,
        offset,
      }),
    placeholderData: (p) => p,
  });

  const verifyChain = useMutation({
    mutationFn: () => api.get<AuditVerify>("/audit/verify"),
    onSuccess: (r) => {
      setVerify(r);
      if (r.intact) toast.success("Audit chain intact", `${formatNumber(r.events_verified)} events verified`);
      else toast.error("Audit chain broken", "Tampering or data loss detected - investigate immediately.");
    },
    onError: (e) => toast.error("Verification failed", errorMessage(e)),
  });

  const items = q.data?.items ?? [];
  const stats = useQuery({
    queryKey: ["audit", "stats", { ...f, offset: undefined }],
    queryFn: () =>
      api.get<Page<AuditEvent>>("/audit", {
        actor: f.actor,
        action: f.action,
        target_type: f.target_type,
        start: localInputToIso(f.start),
        end: localInputToIso(f.end),
        limit: 1000,
      }),
    placeholderData: (p) => p,
    staleTime: 60_000,
  });
  const charts = React.useMemo(() => {
    const rows = stats.data?.items ?? [];
    const actions = countBy(rows, (e) => e.action, 10);
    const areas = countBy(rows, (e) => e.action.split(".")[0], 5);
    const areaOrder = areas.map((a) => a.name);
    const series = bucketSeries(rows, (e) => e.timestamp, range, now, {
      group: (e) => {
        const a = e.action.split(".")[0];
        return areaOrder.slice(0, 4).includes(a) ? a : "Other";
      },
      groupOrder: [...areaOrder.slice(0, 4), ...(areaOrder.length > 4 ? ["Other"] : [])],
    });
    return {
      n: rows.length,
      inRange: series.counted,
      actions: barOption({ categories: actions.map((a) => a.name), series: [{ name: "Events", data: actions.map((a) => a.value) }], horizontal: true, valueLabels: true, labelWidth: 150 }, theme),
      actionsN: actions.length,
      timeline: barOption(
        { categories: series.labels, series: series.series.map((x) => ({ name: x.name, data: x.data, stack: "a" })), axisLabelInterval: range === "30d" ? 4 : 3, barWidth: 12 },
        theme,
      ),
    };
  }, [stats.data, range, now, theme]);
  const statsNote = stats.data && stats.data.total > stats.data.items.length ? ` · latest ${formatNumber(stats.data.items.length)} of ${formatNumber(stats.data.total)}` : "";

  return (
    <>
      <PageHeader
        title="Audit log"
        description="Hash-chained record of every change made through the portal and API."
        actions={
          <Button variant="outline" onClick={() => verifyChain.mutate()} loading={verifyChain.isPending}>
            <ShieldCheck /> Verify chain
          </Button>
        }
      />
      {verify ? (
        <div
          role="status"
          className={cn(
            "rise mb-4 flex items-center gap-3 rounded-xl border p-4 text-sm",
            verify.intact ? "border-success/30 bg-success-soft" : "border-danger/30 bg-danger-soft",
          )}
        >
          {verify.intact ? <ShieldCheck className="h-5 w-5 text-success" /> : <ShieldAlert className="h-5 w-5 text-danger" />}
          <div>
            <p className="font-medium">{verify.intact ? "Chain intact" : "Chain verification FAILED"}</p>
            <p className="text-xs text-muted-foreground">{formatNumber(verify.events_verified)} events verified</p>
          </div>
        </div>
      ) : null}
      <div className="mb-4 grid gap-4 xl:grid-cols-[1fr_1.6fr]">
        <ChartCard title="Actions by type" description={`Most frequent actions matching the filters${statsNote}`}>
          <ChartBody loading={stats.isLoading} error={stats.error} empty={!charts.n} emptyTitle="No audit events match" emptyIcon={History} emptyArt="default" height={240}>
            <Chart
              option={charts.actions}
              height={Math.max(200, charts.actionsN * 28 + 20)}
              ariaLabel="Audit actions by type"
              onEvents={{ click: (p) => set("action")((p as { name: string }).name) }}
            />
          </ChartBody>
        </ChartCard>
        <ChartCard
          title="Activity over time"
          description="Portal and API actions, stacked by area"
          delay={1}
          actions={<Segmented<TimeRange> aria-label="Window" value={range} onChange={setRange} options={TIME_RANGES.map((r) => ({ value: r.value, label: r.label }))} />}
        >
          <ChartBody loading={stats.isLoading} error={stats.error} empty={!charts.inRange} emptyTitle="No activity in this window" emptyIcon={History} height={240}>
            <Chart option={charts.timeline} height={240} ariaLabel="Audit activity over time" />
          </ChartBody>
        </ChartCard>
      </div>
      <Card>
        <FilterBar>
          <TextFilter value={f.actor} onCommit={set("actor")} placeholder="Actor (exact)" className="w-40" aria-label="Actor" />
          <TextFilter value={f.action} onCommit={set("action")} placeholder="Action, e.g. config.* " className="w-52 font-mono text-xs" aria-label="Action" />
          <TextFilter value={f.target_type} onCommit={set("target_type")} placeholder="Target type" className="w-40" aria-label="Target type" />
          <Input type="datetime-local" value={f.start} onChange={(e) => set("start")(e.target.value)} className="w-52" aria-label="From" />
          <Input type="datetime-local" value={f.end} onChange={(e) => set("end")(e.target.value)} className="w-52" aria-label="To" />
        </FilterBar>
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead className="w-6" />
              <TableHead>Time</TableHead>
              <TableHead>Actor</TableHead>
              <TableHead>Action</TableHead>
              <TableHead className="w-full">Target</TableHead>
              <TableHead>Source IP</TableHead>
              <TableHead>Outcome</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            <TableState cols={7} isLoading={q.isLoading} error={q.error} onRetry={() => void q.refetch()} isEmpty={items.length === 0} empty={<EmptyState icon={History} title="No audit events match" />} />
            {items.map((e) => {
              const open = expanded === e.id;
              const hasDetail = !!(e.before || e.after);
              return (
                <React.Fragment key={e.id}>
                  <TableRow className={cn(hasDetail && "cursor-pointer")} onClick={() => hasDetail && setExpanded(open ? null : e.id)} aria-expanded={hasDetail ? open : undefined}>
                    <TableCell className="pr-0">
                      {hasDetail ? open ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" /> : null}
                    </TableCell>
                    <TableCell className="whitespace-nowrap text-xs" title={formatDateTime(e.timestamp)}>
                      <RelativeTime value={e.timestamp} />
                    </TableCell>
                    <TableCell className="whitespace-nowrap font-medium">{e.actor_name}</TableCell>
                    <TableCell>
                      <code className="whitespace-nowrap rounded-sm bg-secondary px-1.5 py-0.5 font-mono text-[11px] text-ink-2">{e.action}</code>
                    </TableCell>
                    <TableCell className="max-w-0">
                      <p className="truncate">
                        {e.target_type ? <span className="text-muted-foreground">{e.target_type}: </span> : null}
                        {e.target_name ?? e.target_id ?? "—"}
                      </p>
                    </TableCell>
                    <TableCell className="font-mono text-xs">{e.source_ip ?? "—"}</TableCell>
                    <TableCell>
                      <StatusBadge status={e.outcome} dot={false} />
                    </TableCell>
                  </TableRow>
                  {open ? (
                    <TableRow className="hover:bg-transparent">
                      <TableCell colSpan={7} className="bg-secondary/60">
                        <div className="grid gap-3 md:grid-cols-2">
                          <div>
                            <p className="mb-1 text-xs font-medium text-muted-foreground">Before</p>
                            <JsonView value={e.before} />
                          </div>
                          <div>
                            <p className="mb-1 text-xs font-medium text-muted-foreground">After</p>
                            <JsonView value={e.after} />
                          </div>
                        </div>
                      </TableCell>
                    </TableRow>
                  ) : null}
                </React.Fragment>
              );
            })}
          </TableBody>
        </Table>
        {q.data ? <Pagination total={q.data.total} limit={PAGE_SIZE} offset={offset} onChange={(o) => setF({ offset: String(o) })} /> : null}
      </Card>
    </>
  );
}
