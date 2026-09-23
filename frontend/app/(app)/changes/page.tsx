"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Plus, Workflow } from "lucide-react";
import * as React from "react";

import { ChangeFormDialog } from "@/components/changes/change-form-dialog";
import { Chart, useChartTheme } from "@/components/charts/chart";
import { ChartBody, ChartCard } from "@/components/common/chart-card";
import { EmptyState } from "@/components/common/empty-state";
import { FilterBar } from "@/components/common/filter-bar";
import { PageHeader } from "@/components/common/page-header";
import { Pagination } from "@/components/common/pagination";
import { RelativeTime } from "@/components/common/relative-time";
import { StatusBadge } from "@/components/common/status-badge";
import { TableState } from "@/components/common/table-skeleton";
import { TextFilter } from "@/components/common/text-filter";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { SimpleSelect } from "@/components/ui/select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { useAuth } from "@/hooks/use-auth";
import { useUrlState } from "@/hooks/use-url-state";
import { api } from "@/lib/api";
import { countBy } from "@/lib/aggregate";
import { barOption, donutOption, funnelOption, severityColor, type ChartTheme } from "@/lib/charts";
import { CHANGE_RISKS, CHANGE_STATES, PAGE_SIZE } from "@/lib/constants";
import type { Change, Page } from "@/lib/types";
import { formatDateTime, humanize } from "@/lib/utils";

const STAGES = ["draft", "pending_approval", "approved", "implemented", "closed"];

function riskColor(risk: string, theme: ChartTheme): string {
  return severityColor(risk, theme);
}

export default function ChangesPage() {
  const { can } = useAuth();
  const [f, setF] = useUrlState({ state: "", q: "", offset: "0" });
  const [createOpen, setCreateOpen] = React.useState(false);
  const offset = Number(f.offset) || 0;
  const q = useQuery({
    queryKey: ["changes", "list", f],
    queryFn: () => api.get<Page<Change>>("/changes", { state: f.state, q: f.q, limit: PAGE_SIZE, offset }),
    placeholderData: (p) => p,
  });
  const items = q.data?.items ?? [];
  const theme = useChartTheme();
  const all = useQuery({ queryKey: ["changes", "stats"], queryFn: () => api.get<Page<Change>>("/changes", { limit: 500 }), staleTime: 60_000 });
  const charts = React.useMemo(() => {
    const rows = all.data?.items ?? [];
    const rank = (st: string) => (st === "cancelled" ? 0 : st === "rejected" ? 1 : Math.max(0, STAGES.indexOf(st)));
    const funnel = STAGES.map((st, i) => ({ name: humanize(st), value: rows.filter((c) => rank(c.state) >= i).length }));
    const risks = countBy(rows, (c) => c.risk).sort((a, b) => CHANGE_RISKS.indexOf(a.name as never) - CHANGE_RISKS.indexOf(b.name as never));
    const states = countBy(rows, (c) => c.state);
    return {
      n: rows.length,
      funnel: funnelOption(funnel, theme),
      risk: donutOption({ items: risks.map((r) => ({ name: humanize(r.name), value: r.value, color: riskColor(r.name, theme) })), centerValue: String(rows.length), centerLabel: "changes" }, theme),
      states: barOption({ categories: states.map((x) => humanize(x.name)), series: [{ name: "Changes", data: states.map((x) => x.value) }], horizontal: true, valueLabels: true }, theme),
      statesN: states.length,
    };
  }, [all.data, theme]);
  const params = useSearchParams();
  const router = useRouter();
  // the top-bar "New change" button links to /changes?new=1
  const wantsNew = params.get("new") === "1" && can("changes:write");
  const dialogOpen = createOpen || wantsNew;
  const onDialogOpenChange = (o: boolean) => {
    setCreateOpen(o);
    if (!o && wantsNew) router.replace("/changes");
  };

  return (
    <>
      <PageHeader
        title="Change requests"
        description="Four-eyes change workflow linked to configuration snapshots."
        actions={
          can("changes:write") ? (
            <Button onClick={() => setCreateOpen(true)}>
              <Plus /> New change
            </Button>
          ) : null
        }
      />
      <div className="mb-4 grid gap-4 lg:grid-cols-2 xl:grid-cols-3">
        <ChartCard title="Workflow funnel" description="Change requests that reached each stage">
          <ChartBody loading={all.isLoading} error={all.error} empty={!charts.n} emptyTitle="No change requests yet" emptyIcon={Workflow} emptyArt="default" height={230}>
            <Chart option={charts.funnel} height={230} ariaLabel="Change workflow funnel" />
          </ChartBody>
        </ChartCard>
        <ChartCard title="Current state" description="Where every change is now" delay={1}>
          <ChartBody loading={all.isLoading} error={all.error} empty={!charts.n} emptyTitle="No change requests yet" emptyIcon={Workflow} height={230}>
            <Chart
              option={charts.states}
              height={Math.max(180, charts.statesN * 30 + 20)}
              ariaLabel="Changes by state"
              onEvents={{ click: (p) => setF({ state: String((p as { name: string }).name).toLowerCase().replace(/ /g, "_"), offset: "0" }) }}
            />
          </ChartBody>
        </ChartCard>
        <ChartCard title="Changes by risk" description="Declared risk of each request" delay={2} className="lg:col-span-2 xl:col-span-1">
          <ChartBody loading={all.isLoading} error={all.error} empty={!charts.n} emptyTitle="No change requests yet" emptyIcon={Workflow} emptyArt="default" height={230}>
            <Chart option={charts.risk} height={230} ariaLabel="Changes by risk" />
          </ChartBody>
        </ChartCard>
      </div>
      <Card>
        <FilterBar>
          <TextFilter value={f.q} onCommit={(v) => setF({ q: v, offset: "0" })} placeholder="Search title" className="w-64" aria-label="Search title" />
          <SimpleSelect
            aria-label="State"
            value={f.state}
            onValueChange={(v) => setF({ state: v, offset: "0" })}
            allowEmpty
            emptyLabel="Any state"
            className="w-48"
            options={CHANGE_STATES.map((s) => ({ value: s, label: humanize(s) }))}
          />
        </FilterBar>
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Number</TableHead>
              <TableHead className="w-full">Title</TableHead>
              <TableHead>State</TableHead>
              <TableHead>Risk</TableHead>
              <TableHead>Devices</TableHead>
              <TableHead>Scheduled</TableHead>
              <TableHead>Created</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            <TableState cols={7} isLoading={q.isLoading} error={q.error} onRetry={() => void q.refetch()} isEmpty={items.length === 0} empty={<EmptyState icon={Workflow} title="No change requests" />} />
            {items.map((c) => (
              <TableRow key={c.id}>
                <TableCell className="whitespace-nowrap font-mono text-xs">
                  <Link href={`/changes/${c.id}`} className="font-semibold text-accent-foreground hover:underline">
                    CHG-{c.number}
                  </Link>
                </TableCell>
                <TableCell className="max-w-0">
                  <Link href={`/changes/${c.id}`} className="block truncate font-medium hover:underline">
                    {c.title}
                  </Link>
                  {c.external_ticket ? <span className="text-xs text-muted-foreground">{c.external_ticket}</span> : null}
                </TableCell>
                <TableCell>
                  <StatusBadge status={c.state} />
                </TableCell>
                <TableCell>
                  <StatusBadge status={c.risk} dot={false} />
                </TableCell>
                <TableCell className="tabular">{c.device_ids.length}</TableCell>
                <TableCell className="whitespace-nowrap text-xs">{c.scheduled_start ? formatDateTime(c.scheduled_start) : "—"}</TableCell>
                <TableCell className="whitespace-nowrap text-xs">
                  <RelativeTime value={c.created_at} />
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
        {q.data ? <Pagination total={q.data.total} limit={PAGE_SIZE} offset={offset} onChange={(o) => setF({ offset: String(o) })} /> : null}
      </Card>
      <ChangeFormDialog open={dialogOpen} onOpenChange={onDialogOpenChange} />
    </>
  );
}
