"use client";

import { useQuery } from "@tanstack/react-query";
import { Fingerprint } from "lucide-react";
import * as React from "react";

import { Chart, useChartTheme } from "@/components/charts/chart";
import { ChartBody, ChartCard } from "@/components/common/chart-card";
import { EmptyState } from "@/components/common/empty-state";
import { FilterBar } from "@/components/common/filter-bar";
import { Pagination } from "@/components/common/pagination";
import { RelativeTime } from "@/components/common/relative-time";
import { StatusBadge } from "@/components/common/status-badge";
import { TableState } from "@/components/common/table-skeleton";
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { SimpleSelect } from "@/components/ui/select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Segmented } from "@/components/ui/tabs";
import { KIND_LABEL, useAuthResults } from "@/hooks/use-activity";
import { useDebounce } from "@/hooks/use-debounce";
import { useTimeRange } from "@/hooks/use-time-range";
import { useOnChange } from "@/hooks/use-reset";
import { api } from "@/lib/api";
import { TIME_RANGES, type TimeRange } from "@/lib/aggregate";
import { barOption, donutOption, type ChartTheme } from "@/lib/charts";
import { PAGE_SIZE } from "@/lib/constants";
import type { AuthEvent, Page } from "@/lib/types";
import { formatNumber, humanize } from "@/lib/utils";

function resultColor(result: string, theme: ChartTheme): string {
  const s = theme.status;
  const r = result.toLowerCase();
  if (["pass", "permit", "success"].includes(r)) return s.success;
  if (["fail", "deny", "denied"].includes(r)) return s.danger;
  if (r === "error") return s.warning;
  return s.neutral;
}

export function EventsTab() {
  const [username, setUsername] = React.useState("");
  const [result, setResult] = React.useState("");
  const [offset, setOffset] = React.useState(0);
  const u = useDebounce(username.trim(), 350);
  useOnChange(u, () => setOffset(0));

  const q = useQuery({
    queryKey: ["tacacs", "events", u, result, offset],
    queryFn: () => api.get<Page<AuthEvent>>("/tacacs/events", { username: u, result, limit: PAGE_SIZE, offset }),
    placeholderData: (p) => p,
    refetchInterval: 30_000,
  });
  const items = q.data?.items ?? [];
  const theme = useChartTheme();
  const { range, setRange } = useTimeRange();
  // counted by the server over the whole window
  const recent = useAuthResults(range);
  const charts = React.useMemo(() => {
    const results = Object.entries(recent.totals)
      .map(([name, value]) => ({ name, value }))
      .sort((a, b) => b.value - a.value);
    const n = results.reduce((x, r) => x + r.value, 0);
    const series = recent.series ?? { labels: [], starts: [], series: [], counted: 0 };
    return {
      n,
      pie: donutOption({ items: results.map((r) => ({ name: humanize(r.name), value: r.value, color: resultColor(r.name, theme) })), centerValue: formatNumber(n), centerLabel: "events" }, theme),
      bars: barOption(
        {
          categories: series.labels,
          series: series.series.map((x) => ({ name: humanize(x.name), data: x.data, stack: "r", color: resultColor(x.name, theme) })),
          axisLabelInterval: range === "30d" ? 4 : 3,
          barWidth: 12,
        },
        theme,
      ),
      kinds: Object.entries(recent.kinds).map(([k, value]) => ({ name: KIND_LABEL[k] ?? k, value })),
    };
  }, [recent.series, recent.totals, recent.kinds, range, theme]);
  const rangeLabel = TIME_RANGES.find((r) => r.value === range)?.long.toLowerCase();

  return (
    <div className="grid gap-4">
    <div className="grid gap-4 xl:grid-cols-[1fr_1.8fr]">
      <ChartCard title="Auth results" description={`${formatNumber(charts.n)} events · ${rangeLabel}${charts.kinds.length ? ` · ${charts.kinds.map((k) => `${k.value} ${k.name.toLowerCase()}`).join(", ")}` : ""}`}>
        <ChartBody loading={recent.isLoading} error={recent.error} empty={!charts.n} emptyTitle="No auth events in this window" emptyIcon={Fingerprint} emptyArt="default" height={240}>
          <Chart option={charts.pie} height={240} ariaLabel="Auth results" />
        </ChartBody>
      </ChartCard>
      <ChartCard
        title="Events over time"
        description="Stacked by result"
        delay={1}
        actions={<Segmented<TimeRange> aria-label="Window" value={range} onChange={setRange} options={TIME_RANGES.map((r) => ({ value: r.value, label: r.label }))} />}
      >
        <ChartBody loading={recent.isLoading} error={recent.error} empty={!charts.n} emptyTitle="No auth events in this window" emptyIcon={Fingerprint} height={240}>
          <Chart option={charts.bars} height={240} ariaLabel="Auth events over time" />
        </ChartBody>
      </ChartCard>
    </div>
    <Card>
      <FilterBar>
        <Input value={username} onChange={(e) => setUsername(e.target.value)} placeholder="Username (exact)" className="w-52" aria-label="Username" />
        <SimpleSelect
          aria-label="Result"
          value={result}
          onValueChange={(v) => { setResult(v); setOffset(0); }}
          allowEmpty
          emptyLabel="Any result"
          className="w-40"
          options={["pass", "fail", "permit", "deny", "error"].map((r) => ({ value: r, label: r }))}
        />
      </FilterBar>
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Time</TableHead>
            <TableHead>User</TableHead>
            <TableHead>Kind</TableHead>
            <TableHead>Device</TableHead>
            <TableHead>Source</TableHead>
            <TableHead>Result</TableHead>
            <TableHead className="w-full">Detail</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          <TableState cols={7} isLoading={q.isLoading} error={q.error} onRetry={() => void q.refetch()} isEmpty={items.length === 0} empty={<EmptyState icon={Fingerprint} title="No authentication events" />} />
          {items.map((e) => (
            <TableRow key={e.id}>
              <TableCell className="whitespace-nowrap text-xs">
                <RelativeTime value={e.timestamp} />
              </TableCell>
              <TableCell className="font-medium">{e.username}</TableCell>
              <TableCell>
                <Badge variant="outline">{e.kind}</Badge>
              </TableCell>
              <TableCell className="font-mono text-xs">{e.device_address}</TableCell>
              <TableCell className="font-mono text-xs">{e.source_address ?? "—"}</TableCell>
              <TableCell>
                <StatusBadge status={e.result} dot={false} />
              </TableCell>
              <TableCell className="max-w-0">
                <code className="block truncate font-mono text-xs text-muted-foreground" title={e.detail ?? undefined}>
                  {e.detail ?? ""}
                </code>
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
      {q.data ? <Pagination total={q.data.total} limit={PAGE_SIZE} offset={offset} onChange={setOffset} /> : null}
    </Card>
    </div>
  );
}
