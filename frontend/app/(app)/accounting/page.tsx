"use client";

import { useQuery } from "@tanstack/react-query";
import { Info, Server, Terminal, Users } from "lucide-react";
import * as React from "react";

import { CommandsTable } from "@/components/accounting/commands-table";
import { Chart, useChartTheme } from "@/components/charts/chart";
import { ChartBody, ChartCard } from "@/components/common/chart-card";
import { FilterBar } from "@/components/common/filter-bar";
import { PageHeader } from "@/components/common/page-header";
import { Pagination } from "@/components/common/pagination";
import { TextFilter } from "@/components/common/text-filter";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { SimpleSelect } from "@/components/ui/select";
import { Segmented } from "@/components/ui/tabs";
import { ACTIVITY_LIMIT } from "@/hooks/use-activity";
import { useNow } from "@/hooks/use-now";
import { useTimeRange } from "@/hooks/use-time-range";
import { useUrlState } from "@/hooks/use-url-state";
import { api } from "@/lib/api";
import { bucketSeries, dailySeries, DAY_LABELS, dayHourMatrix, TIME_RANGES, type TimeRange } from "@/lib/aggregate";
import { barOption, heatmapOption, palette } from "@/lib/charts";
import { PAGE_SIZE } from "@/lib/constants";
import type { CommandLog, Page } from "@/lib/types";
import { formatNumber, localInputToIso, parseDate } from "@/lib/utils";

const DEFAULTS = { user: "", device: "", command: "", result: "", start: "", end: "", offset: "0" };

export default function AccountingPage() {
  const [f, setF] = useUrlState(DEFAULTS);
  const theme = useChartTheme();
  const now = useNow();
  const { range, setRange } = useTimeRange();
  const offset = Number(f.offset) || 0;
  const set = (k: keyof typeof DEFAULTS) => (v: string) => setF({ [k]: v, offset: "0" });

  const q = useQuery({
    queryKey: ["accounting", "commands", f],
    queryFn: () =>
      api.get<Page<CommandLog>>("/accounting/commands", {
        user: f.user,
        device: f.device,
        command: f.command,
        result: f.result,
        start: localInputToIso(f.start),
        end: localInputToIso(f.end),
        limit: PAGE_SIZE,
        offset,
      }),
    placeholderData: (p) => p,
  });

  const stats = useQuery({
    queryKey: ["accounting", "stats", { ...f, offset: undefined }],
    queryFn: () =>
      api.get<Page<CommandLog>>("/accounting/commands", {
        user: f.user,
        device: f.device,
        command: f.command,
        result: f.result,
        start: localInputToIso(f.start),
        end: localInputToIso(f.end),
        limit: ACTIVITY_LIMIT,
      }),
    placeholderData: (p) => p,
    staleTime: 60_000,
  });
  const days = range === "24h" ? 1 : range === "7d" ? 7 : 30;
  const top = useQuery({
    queryKey: ["accounting", "top", days],
    queryFn: () => api.get<{ users: { user: string; commands: number }[]; devices: { device: string; commands: number }[] }>("/accounting/top", { days }),
  });

  const charts = React.useMemo(() => {
    const rows = stats.data?.items ?? [];
    const t = now;
    // span of the loaded rows decides the grain: hours for <= 2 days, else days (max 60)
    const times = rows.map((r) => parseDate(r.timestamp)?.getTime() ?? 0).filter(Boolean);
    const oldest = times.length ? Math.min(...times) : t;
    const spanDays = Math.min(60, Math.max(1, Math.ceil((t - oldest) / 86_400_000)));
    let timeline;
    if (spanDays <= 2) {
      const s = bucketSeries(rows, (r) => r.timestamp, "24h", t, { group: (r) => (r.dangerous ? "Dangerous" : "Commands"), groupOrder: ["Commands", "Dangerous"] });
      timeline = { labels: s.labels, series: s.series };
    } else {
      const all = dailySeries(rows.filter((r) => !r.dangerous), (r) => r.timestamp, spanDays, t);
      const bad = dailySeries(rows.filter((r) => r.dangerous), (r) => r.timestamp, spanDays, t);
      timeline = { labels: all.labels, series: [{ name: "Commands", data: all.data }, { name: "Dangerous", data: bad.data }] };
    }
    const colors: Record<string, string> = { Commands: palette(theme)[0], Dangerous: theme.status.danger };
    const heat = dayHourMatrix(rows.map((r) => r.timestamp), t, 3650);
    return {
      n: rows.length,
      timeline: barOption(
        { categories: timeline.labels, series: timeline.series.map((x) => ({ ...x, stack: "c", color: colors[x.name] })), barWidth: 14 },
        theme,
      ),
      heat: heatmapOption(
        {
          xLabels: Array.from({ length: 24 }, (_, h) => String(h).padStart(2, "0")),
          yLabels: DAY_LABELS,
          cells: heat.cells,
          max: heat.max,
          tooltip: (x, y, v) => `<b>${y} ${x}:00</b> — ${v.toLocaleString("en")} command${v === 1 ? "" : "s"}`,
        },
        theme,
      ),
    };
  }, [stats.data, now, theme]);
  const topUsers = React.useMemo(
    () => barOption({ categories: (top.data?.users ?? []).map((u) => u.user), series: [{ name: "Commands", data: (top.data?.users ?? []).map((u) => u.commands) }], horizontal: true, valueLabels: true }, theme),
    [top.data, theme],
  );
  const topDevices = React.useMemo(
    () =>
      barOption(
        { categories: (top.data?.devices ?? []).map((u) => u.device), series: [{ name: "Commands", data: (top.data?.devices ?? []).map((u) => u.commands), color: palette(theme)[2] }], horizontal: true, valueLabels: true, labelWidth: 140 },
        theme,
      ),
    [top.data, theme],
  );
  const statsNote = stats.data && stats.data.total > stats.data.items.length ? ` · latest ${formatNumber(stats.data.items.length)} of ${formatNumber(stats.data.total)}` : "";
  const rangeLabel = TIME_RANGES.find((r) => r.value === range)?.long.toLowerCase();

  const dirty = Object.entries(f).some(([k, v]) => k !== "offset" && v);
  const dangerousOnPage = (q.data?.items ?? []).filter((c) => c.dangerous).length;

  return (
    <>
      <PageHeader
        title="Command accounting"
        description="Every command executed on network devices, as reported by TACACS+ accounting."
      />
      <div className="mb-4 grid gap-4 xl:grid-cols-[1.6fr_1fr]">
        <ChartCard title="Commands over time" description={`Matching the filters below, dangerous commands highlighted${statsNote}`}>
          <ChartBody loading={stats.isLoading} error={stats.error} empty={!charts.n} emptyTitle="No commands match" emptyIcon={Terminal} height={240}>
            <Chart option={charts.timeline} height={240} ariaLabel="Commands over time" />
          </ChartBody>
        </ChartCard>
        <ChartCard title="When commands run" description={`Weekday × hour of the matching commands${statsNote}`} delay={1}>
          <ChartBody loading={stats.isLoading} error={stats.error} empty={!charts.n} emptyTitle="No commands match" emptyIcon={Terminal} height={240}>
            <Chart option={charts.heat} height={240} ariaLabel="Commands by weekday and hour" />
          </ChartBody>
        </ChartCard>
        <ChartCard
          title="Top users"
          description={`Commands, ${rangeLabel}`}
          delay={2}
          actions={<Segmented<TimeRange> aria-label="Window" value={range} onChange={setRange} options={TIME_RANGES.map((r) => ({ value: r.value, label: r.label }))} />}
        >
          <ChartBody loading={top.isLoading} error={top.error} empty={!top.data?.users.length} emptyTitle="No commands in this window" emptyIcon={Users} emptyArt="default" height={200}>
            <Chart
              option={topUsers}
              height={Math.max(160, (top.data?.users.length ?? 0) * 30 + 20)}
              ariaLabel="Top users"
              onEvents={{ click: (p) => set("user")((p as { name: string }).name) }}
            />
          </ChartBody>
        </ChartCard>
        <ChartCard title="Most active devices" description={`Commands, ${rangeLabel}`} delay={3}>
          <ChartBody loading={top.isLoading} error={top.error} empty={!top.data?.devices.length} emptyTitle="No commands in this window" emptyIcon={Server} emptyArt="default" height={200}>
            <Chart
              option={topDevices}
              height={Math.max(160, (top.data?.devices.length ?? 0) * 30 + 20)}
              ariaLabel="Most active devices"
              onEvents={{ click: (p) => set("device")((p as { name: string }).name) }}
            />
          </ChartBody>
        </ChartCard>
      </div>
      <Card>
        <FilterBar>
          <TextFilter value={f.user} onCommit={set("user")} placeholder="User (exact)" className="w-40" aria-label="User" />
          <TextFilter value={f.device} onCommit={set("device")} placeholder="Device hostname or IP" className="w-52" aria-label="Device" />
          <TextFilter
            value={f.command}
            onCommit={set("command")}
            placeholder="Command substring, or ~regex"
            className="w-72 flex-1 font-mono text-xs"
            aria-label="Command"
          />
          <SimpleSelect
            aria-label="Result"
            value={f.result}
            onValueChange={set("result")}
            allowEmpty
            emptyLabel="Any result"
            className="w-36"
            options={["accounted", "denied", "permit", "deny"].map((r) => ({ value: r, label: r }))}
          />
          <Input type="datetime-local" value={f.start} onChange={(e) => set("start")(e.target.value)} className="w-52" aria-label="From" title="From" />
          <Input type="datetime-local" value={f.end} onChange={(e) => set("end")(e.target.value)} className="w-52" aria-label="To" title="To" />
          {dirty ? (
            <Button variant="ghost" size="sm" onClick={() => setF(DEFAULTS)}>
              Clear
            </Button>
          ) : null}
        </FilterBar>
        <div className="flex flex-wrap items-center gap-2 border-b px-4 py-2 text-xs text-ink-3">
          <Info className="h-3.5 w-3.5" />
          Prefix the command filter with <code className="rounded-sm bg-secondary px-1 font-mono">~</code> for a regular expression, e.g.{" "}
          <code className="rounded-sm bg-secondary px-1 font-mono">~^delete protocols bgp</code>.
          {dangerousOnPage ? <span className="ml-auto font-bold text-danger">{dangerousOnPage} dangerous on this page</span> : null}
        </div>
        <CommandsTable items={q.data?.items ?? []} isLoading={q.isLoading} error={q.error} onRetry={() => void q.refetch()} />
        {q.data ? <Pagination total={q.data.total} limit={PAGE_SIZE} offset={offset} onChange={(o) => setF({ offset: String(o) })} /> : null}
      </Card>
    </>
  );
}
