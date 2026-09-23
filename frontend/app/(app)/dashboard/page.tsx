"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { Activity, ClipboardCheck, DatabaseBackup, GitCompare, History, Server, ShieldCheck, Terminal, Users } from "lucide-react";
import * as React from "react";

import { Chart, useChartMode } from "@/components/charts/chart";
import { ChartBody, ChartCard } from "@/components/common/chart-card";
import { EmptyState } from "@/components/common/empty-state";
import { ErrorState } from "@/components/common/error-state";
import { KpiTile } from "@/components/common/kpi-tile";
import { RelativeTime } from "@/components/common/relative-time";
import { HeroNetwork } from "@/components/illustrations";
import { Skeleton } from "@/components/ui/skeleton";
import { Segmented } from "@/components/ui/tabs";
import { useAuth } from "@/hooks/use-auth";
import { useCommandsSince, useTacacsActivity } from "@/hooks/use-activity";
import { useRecentBackups } from "@/hooks/use-backup-stats";
import { useDashboard } from "@/hooks/use-dashboard";
import { useNow } from "@/hooks/use-now";
import { useTimeRange } from "@/hooks/use-time-range";
import {
  bucketSeries,
  compactNumber,
  dailySeries,
  DAY_LABELS,
  dayHourMatrix,
  foldTop,
  peak,
  TIME_RANGES,
  type TimeRange,
} from "@/lib/aggregate";
import { api } from "@/lib/api";
import { barOption, donutOption, gaugeOption, heatmapOption, lineOption, palette, STATUS, type ChartMode } from "@/lib/charts";
import type { ComplianceRun, ComplianceRunDetail, Device, Page } from "@/lib/types";
import { formatDate, formatNumber, humanize, parseDate } from "@/lib/utils";

const DAY = 86_400_000;
const HOURS = Array.from({ length: 24 }, (_, h) => String(h).padStart(2, "0"));

function greeting(now: number): string {
  const h = new Date(now).getHours();
  return h < 5 ? "Good evening" : h < 12 ? "Good morning" : h < 18 ? "Good afternoon" : "Good evening";
}

function firstName(me: { full_name: string | null; username: string } | null): string {
  if (!me) return "";
  return (me.full_name?.split(/\s+/)[0] || me.username).replace(/^./, (c) => c.toUpperCase());
}

function reachColor(key: string, mode: ChartMode): string {
  const s = STATUS[mode];
  const k = key.toLowerCase();
  if (["reachable", "up", "ok"].includes(k)) return s.success;
  if (["unreachable", "down", "failed"].includes(k)) return s.danger;
  if (["degraded", "partial"].includes(k)) return s.warning;
  return s.neutral;
}

function authColor(key: string, mode: ChartMode): string {
  const s = STATUS[mode];
  const k = key.toLowerCase();
  if (["pass", "permit", "success", "accepted"].includes(k)) return s.success;
  if (["fail", "deny", "denied", "reject"].includes(k)) return s.danger;
  if (k === "error") return s.warning;
  return s.neutral;
}

const TINTS = [
  "bg-accent text-accent-foreground",
  "bg-success-soft text-success",
  "bg-warning-soft text-warning",
  "bg-[#fbe3ec] text-[#8c1f4b] dark:bg-[#3a1a2a] dark:text-[#f3a6c4]",
];

function initials(name: string | null): string {
  if (!name) return "?";
  const parts = name.split(/[\s._-]+/).filter(Boolean);
  return (parts.length > 1 ? parts[0][0] + parts[1][0] : name.slice(0, 2)).toUpperCase();
}

export default function DashboardPage() {
  const router = useRouter();
  const { me, can } = useAuth();
  const mode = useChartMode();
  const now = useNow();
  const { range, setRange } = useTimeRange();
  const q = useDashboard();
  const d = q.data;
  const loading = q.isLoading;

  const devices = useQuery({
    queryKey: ["devices", "created"],
    queryFn: () => api.get<Page<Device>>("/devices", { limit: 1000 }),
    enabled: can("devices:read"),
    staleTime: 5 * 60_000,
  });
  const backups = useRecentBackups(30);
  const activity = useTacacsActivity(range);
  const week = useCommandsSince("7d-fixed");
  const latestRun = useQuery({
    queryKey: ["compliance", "runs", 1],
    queryFn: () => api.get<ComplianceRun[]>("/compliance/runs", { limit: 1 }),
    enabled: can("compliance:read"),
  });
  const runId = latestRun.data?.[0]?.id;
  const runDetail = useQuery({
    queryKey: ["compliance", "run", runId],
    queryFn: () => api.get<ComplianceRunDetail>(`/compliance/runs/${runId}`),
    enabled: !!runId,
  });

  const t = now;
  React.useEffect(() => {
    document.title = "Dashboard · NetworkOps Manager";
  }, []);

  // --- derived numbers (all from API data) ----------------------------------------------------
  const deviceStats = React.useMemo(() => {
    const items = devices.data?.items ?? [];
    const created = items.map((x) => parseDate(x.created_at)?.getTime() ?? 0);
    const newThisWeek = created.filter((c) => c >= t - 7 * DAY).length;
    const days = dailySeries(items, (x) => x.created_at, 30, t);
    const before = created.filter((c) => c < days.starts[0]).length;
    const cumulative = days.data.reduce<number[]>((acc, n) => [...acc, (acc[acc.length - 1] ?? before) + n], []);
    return { newThisWeek, labels: days.labels, cumulative, complete: (devices.data?.total ?? 0) <= items.length };
  }, [devices.data, t]);

  const backupStats = React.useMemo(() => {
    const items = backups.data?.items ?? [];
    const last24 = items.filter((b) => (parseDate(b.collected_at)?.getTime() ?? 0) >= t - DAY);
    const changed24 = last24.filter((b) => b.changed);
    const unplanned24 = changed24.filter((b) => !b.change_request_id).length;
    const total = dailySeries(items, (b) => b.collected_at, 30, t);
    const ok = dailySeries(items.filter((b) => b.status !== "failed"), (b) => b.collected_at, 30, t);
    const changes = dailySeries(items.filter((b) => b.changed), (b) => b.collected_at, 30, t);
    const rate = total.data.map((n, i) => (n ? Math.round((ok.data[i] / n) * 1000) / 10 : null));
    return { changed24: changed24.length, unplanned24, labels: total.labels, rate, changes: changes.data };
  }, [backups.data, t]);

  const successPct = d && d.backups.last_24h ? ((d.backups.last_24h - d.backups.failures_24h) / d.backups.last_24h) * 100 : null;
  const tacacs24 = d ? Object.values(d.tacacs.auth_24h).reduce((a, b) => a + b, 0) + d.tacacs.accounting_24h : 0;
  const activityPeak = activity.series ? peak(activity.series.series) : 0;
  const activityTotals = activity.series ? activity.series.series.map((s) => s.data).reduce<number[]>((acc, arr) => arr.map((v, i) => v + (acc[i] ?? 0)), []) : [];
  const trend = React.useMemo(() => d?.compliance.trend ?? [], [d]);
  const scoreDelta = trend.length >= 2 ? trend[trend.length - 1].score - trend[trend.length - 2].score : null;
  const rangeLong = TIME_RANGES.find((r) => r.value === range)?.long.toLowerCase() ?? "";
  const perUnit = range === "24h" ? "h" : range === "7d" ? "6h" : "day";

  // --- chart options --------------------------------------------------------------------------
  const activityOption = React.useMemo(
    () =>
      activity.series
        ? lineOption(
            {
              categories: activity.series.labels,
              series: activity.series.series,
              area: true,
              stacked: true,
              labelInterval: range === "24h" ? 3 : range === "7d" ? 3 : 4,
            },
            mode,
          )
        : null,
    [activity.series, range, mode],
  );

  const gauge = React.useMemo(
    () =>
      gaugeOption(
        {
          value: d?.compliance.score == null ? null : Math.round(d.compliance.score * 10) / 10,
          label: scoreDelta == null ? "latest run" : `${scoreDelta >= 0 ? "+" : "−"}${Math.abs(scoreDelta).toFixed(1)} vs previous run`,
          gradient: true,
        },
        mode,
      ),
    [d, scoreDelta, mode],
  );

  const vendors = React.useMemo(() => {
    const items = foldTop((d?.devices.by_vendor ?? []).map((v) => ({ name: v.name, value: v.count })), 5);
    return donutOption({ items, centerValue: formatNumber(d?.devices.total ?? 0), centerLabel: "devices" }, mode);
  }, [d?.devices.by_vendor, d?.devices.total, mode]);

  const heat = React.useMemo(() => {
    const m = dayHourMatrix((week.data?.items ?? []).map((c) => c.timestamp), t, 7);
    return {
      counted: m.counted,
      option: heatmapOption(
        {
          xLabels: HOURS,
          yLabels: DAY_LABELS,
          cells: m.cells,
          max: m.max,
          tooltip: (x, y, v) => `<b>${y} ${x}:00</b> — ${v.toLocaleString("en")} command${v === 1 ? "" : "s"}`,
        },
        mode,
      ),
    };
  }, [week.data, t, mode]);

  const backupBars = React.useMemo(() => {
    const s = bucketSeries(backups.data?.items ?? [], (b) => b.collected_at, range, t, {
      group: (b) => (b.status === "failed" ? "Failed" : b.changed ? "Changed" : "Unchanged"),
      groupOrder: ["Changed", "Unchanged", "Failed"],
    });
    const colors: Record<string, string> = { Changed: palette(mode)[0], Unchanged: STATUS[mode].neutral, Failed: STATUS[mode].danger };
    return {
      counted: s.counted,
      option: barOption(
        {
          categories: s.labels,
          series: s.series.map((x) => ({ ...x, stack: "b", color: colors[x.name] })),
          axisLabelInterval: range === "30d" ? 4 : 3,
          barWidth: 12,
        },
        mode,
      ),
    };
  }, [backups.data, range, t, mode]);

  const authPie = React.useMemo(() => {
    const items = Object.entries(d?.tacacs.auth_24h ?? {})
      .map(([k, v]) => ({ name: humanize(k), value: v, color: authColor(k, mode) }))
      .sort((a, b) => b.value - a.value);
    const total = items.reduce((a, b) => a + b.value, 0);
    return { total, option: donutOption({ items, centerValue: compactNumber(total), centerLabel: "auth events" }, mode) };
  }, [d?.tacacs.auth_24h, mode]);

  const reach = React.useMemo(() => {
    const items = Object.entries(d?.devices.by_reachability ?? {})
      .map(([k, v]) => ({ name: humanize(k), value: v, color: reachColor(k, mode) }))
      .sort((a, b) => b.value - a.value);
    const ok = items.filter((i) => i.color === STATUS[mode].success).reduce((a, b) => a + b.value, 0);
    const total = items.reduce((a, b) => a + b.value, 0);
    return donutOption({ items, centerValue: total ? `${Math.round((ok / total) * 100)}%` : "—", centerLabel: "reachable" }, mode);
  }, [d?.devices.by_reachability, mode]);

  const trendOption = React.useMemo(
    () =>
      lineOption(
        {
          categories: trend.map((p) => formatDate(p.t)),
          series: [{ name: "Score", data: trend.map((p) => Math.round(p.score * 10) / 10) }],
          area: true,
          min: 0,
          max: 100,
          format: (v) => `${v}%`,
          axisFormat: (v) => `${v}%`,
        },
        mode,
      ),
    [trend, mode],
  );

  const sites = React.useMemo(
    () =>
      barOption(
        {
          categories: (d?.devices.by_site ?? []).map((s) => s.name),
          series: [{ name: "Devices", data: (d?.devices.by_site ?? []).map((s) => s.count) }],
          horizontal: true,
          valueLabels: true,
        },
        mode,
      ),
    [d?.devices.by_site, mode],
  );

  const topUsers = React.useMemo(
    () =>
      barOption(
        {
          categories: (d?.top_users ?? []).map((u) => u.user),
          series: [{ name: "Commands", data: (d?.top_users ?? []).map((u) => u.commands), color: palette(mode)[0] }],
          horizontal: true,
          valueLabels: true,
        },
        mode,
      ),
    [d?.top_users, mode],
  );
  const topDevices = React.useMemo(
    () =>
      barOption(
        {
          categories: (d?.top_devices ?? []).map((u) => u.device),
          series: [{ name: "Commands", data: (d?.top_devices ?? []).map((u) => u.commands), color: palette(mode)[2] }],
          horizontal: true,
          valueLabels: true,
          labelWidth: 130,
        },
        mode,
      ),
    [d?.top_devices, mode],
  );

  if (q.error && !d) {
    return (
      <section className="rounded-2xl border bg-card">
        <ErrorState error={q.error} onRetry={() => void q.refetch()} />
      </section>
    );
  }

  const failing = d?.backups.devices_failing ?? 0;
  const healthy = d ? Math.max(0, d.devices.total - failing) : 0;
  const run = runDetail.data;
  const compliant = run ? run.devices.filter((x) => x.failed === 0).length : null;
  const failingDevices = run ? run.devices.filter((x) => x.failed > 0).length : null;
  const critical = run ? run.failures.filter((f) => f.severity === "critical").length : null;

  return (
    <div className="flex flex-col gap-5">
      {/* hero ------------------------------------------------------------------------------- */}
      <section className="rise relative flex items-center gap-6 overflow-hidden rounded-2xl border bg-card px-5 py-6 sm:px-[30px] sm:py-[26px]">
        <div className="z-[1] flex min-w-0 flex-1 flex-col gap-2">
          <span className="inline-flex items-center gap-2 text-[12.5px] font-bold text-success">
            <span className="live h-2 w-2 rounded-full bg-[var(--ill-green)]" aria-hidden />
            Live · updated {q.dataUpdatedAt ? new Date(q.dataUpdatedAt).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }) : "—"}
          </span>
          <h1 className="font-display text-2xl font-bold tracking-[-0.02em] sm:text-[28px]">
            {greeting(now)}
            {me ? `, ${firstName(me)}` : ""}
          </h1>
          {loading ? (
            <Skeleton className="h-10 w-full max-w-[560px]" />
          ) : d ? (
            <p className="max-w-[580px] text-[14.5px] leading-relaxed text-ink-3">
              {formatNumber(healthy)} of {formatNumber(d.devices.total)} devices have a healthy last backup
              {failing ? `, ${formatNumber(failing)} are failing` : ""}.{" "}
              {can("configs:read")
                ? backupStats.unplanned24
                  ? `${backupStats.unplanned24} unplanned config change${backupStats.unplanned24 === 1 ? "" : "s"} in the last 24 hours need${backupStats.unplanned24 === 1 ? "s" : ""} a look`
                  : "No unplanned config changes in the last 24 hours"
                : null}
              {scoreDelta != null
                ? `${can("configs:read") ? ", and the" : " The"} compliance score ${scoreDelta > 0.05 ? `rose ${scoreDelta.toFixed(1)} points` : scoreDelta < -0.05 ? `fell ${Math.abs(scoreDelta).toFixed(1)} points` : "held steady"} since the previous run.`
                : can("configs:read")
                  ? "."
                  : ""}
            </p>
          ) : null}
          <div className="mt-2 flex flex-wrap gap-2.5">
            {can("changes:read") ? (
              <Link
                href="/changes"
                className="inline-flex h-9 items-center rounded-md bg-accent px-3.5 text-[13px] font-bold text-accent-foreground transition-colors hover:bg-accent/70 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              >
                {d?.open_changes ? `Review ${d.open_changes} open change${d.open_changes === 1 ? "" : "s"}` : "View changes"}
              </Link>
            ) : null}
            {can("configs:read") ? (
              <Link
                href={failing ? "/backups?status=failed" : "/backups"}
                className="inline-flex h-9 items-center rounded-md border border-input px-3.5 text-[13px] font-bold text-ink-2 transition-colors hover:border-primary/40 hover:bg-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              >
                {failing ? "Open failed backups" : "Open backups"}
              </Link>
            ) : null}
          </div>
        </div>
        <HeroNetwork className="hidden h-[170px] w-[420px] shrink-0 xl:block" />
        <HeroNetwork className="hidden h-[120px] w-[300px] shrink-0 md:block xl:hidden" />
      </section>

      {/* KPIs --------------------------------------------------------------------------------- */}
      <section className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <KpiTile
          label="Managed devices"
          icon={Server}
          loading={loading}
          href="/devices"
          value={formatNumber(d?.devices.total)}
          tone={deviceStats.newThisWeek ? "success" : "default"}
          sub={devices.data ? (deviceStats.newThisWeek ? `+${deviceStats.newThisWeek} this week` : "no new this week") : undefined}
          spark={devices.data && deviceStats.complete ? { labels: deviceStats.labels, data: deviceStats.cumulative, name: "Devices", color: palette(mode)[0] } : null}
          delay={0}
        />
        <KpiTile
          label="Backup success · 24h"
          icon={DatabaseBackup}
          loading={loading}
          href="/backups"
          value={successPct == null ? "—" : `${successPct.toFixed(1)}%`}
          tone={d?.backups.failures_24h ? "danger" : "success"}
          sub={d ? (d.backups.failures_24h ? `${formatNumber(d.backups.failures_24h)} failed` : d.backups.last_24h ? "no failures" : "no runs") : undefined}
          spark={
            backups.data
              ? { labels: backupStats.labels, data: backupStats.rate.map((v) => v ?? Number.NaN), name: "Success rate", color: palette(mode)[2], format: (v) => (Number.isFinite(v) ? `${v}%` : "no runs") }
              : null
          }
          delay={1}
        />
        <KpiTile
          label="TACACS+ requests · 24h"
          icon={ShieldCheck}
          loading={loading}
          href="/tacacs?tab=events"
          value={compactNumber(tacacs24)}
          sub={activity.series ? `peak ${compactNumber(activityPeak)}/${perUnit}${range === "24h" ? "" : ` · ${range}`}` : undefined}
          spark={activity.series ? { labels: activity.series.labels, data: activityTotals, name: "Requests", color: palette(mode)[1] } : can("accounting:read") ? null : undefined}
          delay={2}
        />
        <KpiTile
          label="Config changes · 24h"
          icon={GitCompare}
          loading={loading || backups.isLoading}
          href="/backups?changed_only=1"
          value={can("configs:read") ? formatNumber(backupStats.changed24) : "—"}
          tone={backupStats.unplanned24 ? "warning" : "default"}
          sub={backups.data ? `${backupStats.unplanned24} unplanned` : undefined}
          spark={backups.data ? { labels: backupStats.labels, data: backupStats.changes, name: "Changes", color: palette(mode)[3] } : null}
          delay={3}
        />
      </section>

      {/* activity + compliance ------------------------------------------------------------------ */}
      <section className="grid gap-4 xl:grid-cols-[2fr_1fr]">
        {can("accounting:read") ? (
          <ChartCard
            title="TACACS+ activity"
            description={`Requests per ${perUnit === "h" ? "hour" : perUnit === "6h" ? "6 hours" : "day"} by type, stacked · ${rangeLong}${activity.truncated ? " · latest 1,000 records per source" : ""}`}
            delay={5}
            actions={
              <Segmented<TimeRange> aria-label="Activity window" value={range} onChange={setRange} options={TIME_RANGES.map((r) => ({ value: r.value, label: r.label }))} />
            }
          >
            <ChartBody
              loading={activity.isLoading}
              error={activity.error}
              empty={!activity.series?.counted}
              emptyTitle="No TACACS+ activity in this window"
              emptyDescription="Authentication, authorisation and accounting records appear once the log shipper sends them."
              emptyIcon={Activity}
              height={268}
            >
              {activityOption ? <Chart option={activityOption} height={268} ariaLabel="TACACS+ activity chart" /> : null}
            </ChartBody>
          </ChartCard>
        ) : null}
        <ChartCard title="Compliance score" description="Latest run, weighted by rule severity" delay={6} className={can("accounting:read") ? undefined : "xl:col-span-2"}>
          <ChartBody loading={loading} empty={d?.compliance.score == null} emptyTitle="No compliance runs yet" emptyIcon={ClipboardCheck} emptyArt="default" height={210}>
            <Chart option={gauge} height={210} ariaLabel={`Compliance score ${d?.compliance.score?.toFixed(1) ?? ""}`} />
            <div className="grid grid-cols-3 gap-2 text-center">
              {[
                ["compliant", compliant],
                ["failing", failingDevices],
                ["critical checks", critical],
              ].map(([label, v]) => (
                <Link key={label as string} href={runId ? `/compliance/runs/${runId}` : "/compliance"} className="rounded-[10px] bg-secondary p-2 transition-colors hover:bg-accent">
                  <div className="font-display text-base font-bold tabular">{v == null ? "—" : formatNumber(v as number)}</div>
                  <div className="text-[11.5px] text-ink-3">{label}</div>
                </Link>
              ))}
            </div>
          </ChartBody>
        </ChartCard>
      </section>

      {/* vendor / heatmap / recent changes ------------------------------------------------------ */}
      <section className="grid gap-4 lg:grid-cols-2 xl:grid-cols-[1fr_1.25fr_1.25fr]">
        <ChartCard title="Fleet by vendor" description={`${formatNumber(d?.devices.total ?? 0)} devices`} delay={7}>
          <ChartBody loading={loading} empty={!d?.devices.by_vendor.length} emptyTitle="No devices yet" emptyIcon={Server} emptyArt="default" height={250}>
            <Chart option={vendors} height={250} ariaLabel="Devices by vendor" />
          </ChartBody>
        </ChartCard>
        {can("accounting:read") ? (
          <ChartCard title="When engineers work" description={`Commands per hour, last 7 days${(week.data?.total ?? 0) > (week.data?.items.length ?? 0) ? " · latest 1,000" : ""}`} delay={8}>
            <ChartBody loading={week.isLoading} error={week.error} empty={!heat.counted} emptyTitle="No commands in the last 7 days" emptyIcon={Terminal} height={250}>
              <Chart option={heat.option} height={250} ariaLabel="Commands by weekday and hour" />
            </ChartBody>
          </ChartCard>
        ) : null}
        <ChartCard
          title="Recent config changes"
          delay={9}
          className="lg:col-span-2 xl:col-span-1"
          actions={
            <Link href="/backups?changed_only=1" className="text-[13px] font-bold text-accent-foreground hover:text-primary-hover hover:underline">
              View all
            </Link>
          }
        >
          {loading ? (
            <div className="grid gap-2 pt-2">
              {Array.from({ length: 5 }).map((_, i) => (
                <Skeleton key={i} className="h-11" />
              ))}
            </div>
          ) : d?.recent_changes.length ? (
            <ul className="-mx-2 flex flex-col pt-1">
              {d.recent_changes.slice(0, 6).map((c, i) => (
                <li key={c.id}>
                  <Link
                    href={c.commit ? `/devices/${c.device_id}?tab=diff&new=${c.commit}` : `/devices/${c.device_id}`}
                    className="flex items-center gap-3 rounded-[10px] px-2 py-[9px] transition-colors hover:bg-row-hover focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                  >
                    <span
                      className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-[10px] text-xs font-extrabold ${c.author ? TINTS[i % TINTS.length] : "bg-danger-soft text-danger"}`}
                      aria-hidden
                    >
                      {initials(c.author)}
                    </span>
                    <span className="flex min-w-0 flex-1 flex-col gap-0.5">
                      <span className="truncate text-[13.5px] font-bold">{c.device}</span>
                      <span className="truncate text-[12.5px] text-ink-3">{c.reason ?? "Scheduled backup"}</span>
                    </span>
                    <span className="flex shrink-0 flex-col items-end gap-0.5">
                      <span className="font-mono text-xs">
                        <span className="text-success">+{c.added}</span> <span className="text-danger">−{c.removed}</span>
                      </span>
                      <span className="text-[11.5px] text-muted-foreground">
                        <RelativeTime value={c.at} /> · {c.author ?? "unknown"}
                      </span>
                    </span>
                  </Link>
                </li>
              ))}
            </ul>
          ) : (
            <EmptyState title="No configuration changes recorded" icon={GitCompare} compact />
          )}
        </ChartCard>
      </section>

      {/* backups / auth results / reachability ------------------------------------------------- */}
      <section className="grid gap-4 lg:grid-cols-2 xl:grid-cols-3">
        {can("configs:read") ? (
          <ChartCard title="Backup runs" description={`Changed, unchanged and failed collections · ${rangeLong}`} delay={10} className="lg:col-span-2 xl:col-span-1">
            <ChartBody loading={backups.isLoading} error={backups.error} empty={!backupBars.counted} emptyTitle="No backups in this window" emptyIcon={DatabaseBackup} height={240}>
              <Chart option={backupBars.option} height={240} ariaLabel="Backup runs over time" />
            </ChartBody>
          </ChartCard>
        ) : null}
        <ChartCard title="TACACS+ auth results" description="Authentication and authorisation outcomes, last 24 hours" delay={11}>
          <ChartBody loading={loading} empty={!authPie.total} emptyTitle="No auth events in 24 hours" emptyIcon={ShieldCheck} emptyArt="default" height={240}>
            <Chart option={authPie.option} height={240} ariaLabel="TACACS+ auth results" />
          </ChartBody>
        </ChartCard>
        <ChartCard title="Reachability" description="Devices by last reachability probe" delay={12}>
          <ChartBody loading={loading} empty={!d?.devices.total} emptyTitle="No devices yet" emptyIcon={Server} emptyArt="network" height={240}>
            <Chart option={reach} height={240} ariaLabel="Devices by reachability" />
          </ChartBody>
        </ChartCard>
      </section>

      {/* compliance trend / sites ------------------------------------------------------------ */}
      <section className="grid gap-4 xl:grid-cols-[2fr_1fr]">
        <ChartCard title="Compliance trend" description={`Fleet score over the last ${trend.length || 30} runs`} delay={13}>
          <ChartBody loading={loading} empty={!trend.length} emptyTitle="No compliance runs yet" emptyIcon={ClipboardCheck} height={240}>
            <Chart option={trendOption} height={240} ariaLabel="Compliance score trend" />
          </ChartBody>
        </ChartCard>
        <ChartCard title="Devices by site" description="Largest sites" delay={14}>
          <ChartBody loading={loading} empty={!d?.devices.by_site.length} emptyTitle="No sites" emptyIcon={Server} emptyArt="network" height={240}>
            <Chart option={sites} height={Math.max(160, (d?.devices.by_site.length ?? 0) * 30 + 30)} ariaLabel="Devices by site" />
          </ChartBody>
        </ChartCard>
      </section>

      {/* people / devices / audit --------------------------------------------------------------- */}
      <section className="grid gap-4 lg:grid-cols-2 xl:grid-cols-3">
        <ChartCard title="Top users" description="Device commands, last 7 days" delay={15}>
          <ChartBody loading={loading} empty={!d?.top_users.length} emptyTitle="No accounting records" emptyIcon={Users} emptyArt="default" height={200}>
            <Chart
              option={topUsers}
              height={Math.max(150, (d?.top_users.length ?? 0) * 34 + 20)}
              ariaLabel="Top users by commands"
              onEvents={{ click: (p) => router.push(`/accounting?user=${encodeURIComponent((p as { name: string }).name)}`) }}
            />
          </ChartBody>
        </ChartCard>
        <ChartCard title="Most active devices" description="Device commands, last 7 days" delay={16}>
          <ChartBody loading={loading} empty={!d?.top_devices.length} emptyTitle="No accounting records" emptyIcon={Terminal} emptyArt="default" height={200}>
            <Chart
              option={topDevices}
              height={Math.max(150, (d?.top_devices.length ?? 0) * 34 + 20)}
              ariaLabel="Most active devices by commands"
              onEvents={{ click: (p) => router.push(`/accounting?device=${encodeURIComponent((p as { name: string }).name)}`) }}
            />
          </ChartBody>
        </ChartCard>
        <ChartCard
          title="Recent audit events"
          delay={17}
          className="lg:col-span-2 xl:col-span-1"
          actions={
            can("audit:read") ? (
              <Link href="/audit" className="text-[13px] font-bold text-accent-foreground hover:text-primary-hover hover:underline">
                Audit log
              </Link>
            ) : null
          }
        >
          {loading ? (
            <Skeleton className="h-48" />
          ) : d?.recent_audit.length ? (
            <ul className="-mx-2 flex flex-col pt-1 text-sm">
              {d.recent_audit.slice(0, 6).map((a, i) => (
                <li key={i} className="flex items-center gap-3 rounded-[10px] px-2 py-2 hover:bg-row-hover">
                  <History className="h-4 w-4 shrink-0 text-muted-foreground" aria-hidden />
                  <span className="flex min-w-0 flex-1 flex-col">
                    <span className="truncate font-semibold">
                      {a.actor} <code className="ml-1 rounded-sm bg-secondary px-1.5 py-0.5 font-mono text-[11px] text-ink-2">{a.action}</code>
                    </span>
                    <span className="truncate text-xs text-ink-3">{a.target ?? "—"}</span>
                  </span>
                  <RelativeTime value={a.at} className="shrink-0 text-xs text-muted-foreground" />
                </li>
              ))}
            </ul>
          ) : (
            <EmptyState title="No audit events" icon={History} compact />
          )}
        </ChartCard>
      </section>

    </div>
  );
}
