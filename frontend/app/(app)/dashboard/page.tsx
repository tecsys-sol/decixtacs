"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import {
  AlertTriangle,
  Bell,
  ClipboardCheck,
  DatabaseBackup,
  GitCompare,
  Server,
  ShieldCheck,
  Workflow,
} from "lucide-react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { CHART, ChartTooltip, RankedBars } from "@/components/charts/chart-kit";
import { EmptyState } from "@/components/common/empty-state";
import { ErrorState } from "@/components/common/error-state";
import { KpiTile } from "@/components/common/kpi-tile";
import { PageHeader } from "@/components/common/page-header";
import { RelativeTime } from "@/components/common/relative-time";
import { RiskBadge } from "@/components/diff/risk-panel";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { api } from "@/lib/api";
import { scoreColor } from "@/lib/status";
import type { Dashboard } from "@/lib/types";
import { cn, formatDate, formatDateTime, formatNumber, humanize, shortSha } from "@/lib/utils";

function ChartSkeleton() {
  return <Skeleton className="h-[220px] w-full" />;
}

export default function DashboardPage() {
  const q = useQuery({
    queryKey: ["dashboard"],
    queryFn: () => api.get<Dashboard>("/dashboard"),
    refetchInterval: 60_000,
  });
  const d = q.data;
  const loading = q.isLoading;

  if (q.error && !d) {
    return (
      <>
        <PageHeader title="Dashboard" />
        <Card>
          <ErrorState error={q.error} onRetry={() => void q.refetch()} />
        </Card>
      </>
    );
  }

  const authOk = d ? (d.tacacs.auth_24h.pass ?? 0) + (d.tacacs.auth_24h.success ?? 0) + (d.tacacs.auth_24h.permit ?? 0) : 0;
  const authTotal = d ? Object.values(d.tacacs.auth_24h).reduce((a, b) => a + b, 0) : 0;
  const unreachable = d ? (d.devices.by_reachability.unreachable ?? 0) + (d.devices.by_reachability.down ?? 0) : 0;
  const vendors = [...(d?.devices.by_vendor ?? [])].sort((a, b) => b.count - a.count);
  const trend = (d?.compliance.trend ?? []).map((p) => ({ t: p.t, score: Math.round(p.score * 10) / 10 }));

  return (
    <>
      <PageHeader title="Dashboard" description="Fleet health, configuration activity and access at a glance." />

      <div className="grid grid-cols-2 gap-3 md:grid-cols-4 xl:grid-cols-7">
        <KpiTile
          label="Devices"
          icon={Server}
          loading={loading}
          value={formatNumber(d?.devices.total)}
          sub={unreachable ? <span className="text-destructive">{unreachable} unreachable</span> : "all reachable"}
          href="/devices"
        />
        <KpiTile
          label="Last backup"
          icon={DatabaseBackup}
          loading={loading}
          value={<RelativeTime value={d?.backups.last} className="text-lg" />}
          sub={`${formatNumber(d?.backups.last_24h)} runs in 24h`}
          href="/backups"
        />
        <KpiTile
          label="Backup failures (24h)"
          icon={AlertTriangle}
          tone={d && d.backups.failures_24h > 0 ? "danger" : "success"}
          loading={loading}
          value={formatNumber(d?.backups.failures_24h)}
          sub={`${formatNumber(d?.backups.devices_failing)} devices failing`}
          href="/backups?status=failed"
        />
        <KpiTile
          label="Compliance score"
          icon={ClipboardCheck}
          tone={d?.compliance.score == null ? "default" : d.compliance.score >= 90 ? "success" : d.compliance.score >= 70 ? "warning" : "danger"}
          loading={loading}
          value={
            <span className={scoreColor(d?.compliance.score)}>
              {d?.compliance.score == null ? "—" : `${d.compliance.score.toFixed(1)}%`}
            </span>
          }
          sub="latest run"
          href="/compliance"
        />
        <KpiTile
          label="TACACS requests (24h)"
          icon={ShieldCheck}
          loading={loading}
          value={formatNumber(authTotal)}
          sub={`${formatNumber(d?.tacacs.accounting_24h)} commands${authTotal ? ` · ${Math.round((authOk / authTotal) * 100)}% auth ok` : ""}`}
          href="/tacacs?tab=events"
        />
        <KpiTile
          label="Open changes"
          icon={Workflow}
          loading={loading}
          value={formatNumber(d?.open_changes)}
          sub="pending or approved"
          href="/changes"
        />
        <KpiTile
          label="Open alerts (7d)"
          icon={Bell}
          tone={d && d.open_alerts > 0 ? "warning" : "success"}
          loading={loading}
          value={formatNumber(d?.open_alerts)}
          sub="unacknowledged"
          href="/alerts"
        />
      </div>

      <div className="mt-4 grid gap-4 lg:grid-cols-3">
        <Card>
          <CardHeader>
            <CardTitle>Devices by vendor</CardTitle>
            <CardDescription>Inventory composition</CardDescription>
          </CardHeader>
          <CardContent>
            {loading ? (
              <ChartSkeleton />
            ) : vendors.length ? (
              <ResponsiveContainer width="100%" height={Math.max(160, vendors.length * 30 + 20)}>
                <BarChart data={vendors} layout="vertical" margin={{ left: 0, right: 16, top: 4, bottom: 4 }} barCategoryGap={6}>
                  <CartesianGrid horizontal={false} stroke={CHART.grid} />
                  <XAxis type="number" allowDecimals={false} tick={CHART.tick} axisLine={false} tickLine={false} />
                  <YAxis type="category" dataKey="name" width={96} tick={CHART.tick} axisLine={false} tickLine={false} />
                  <Tooltip cursor={{ fill: "hsl(var(--muted))" }} content={<ChartTooltip />} />
                  <Bar dataKey="count" name="Devices" fill={CHART.series1} radius={[0, 4, 4, 0]} maxBarSize={18} />
                </BarChart>
              </ResponsiveContainer>
            ) : (
              <EmptyState title="No devices yet" icon={Server} />
            )}
          </CardContent>
        </Card>

        <Card className="lg:col-span-2">
          <CardHeader>
            <CardTitle>Compliance trend</CardTitle>
            <CardDescription>Fleet score over the last {trend.length || 30} runs</CardDescription>
          </CardHeader>
          <CardContent>
            {loading ? (
              <ChartSkeleton />
            ) : trend.length ? (
              <ResponsiveContainer width="100%" height={220}>
                <LineChart data={trend} margin={{ left: -12, right: 8, top: 8, bottom: 0 }}>
                  <CartesianGrid vertical={false} stroke={CHART.grid} />
                  <XAxis dataKey="t" tickFormatter={(v: string) => formatDate(v)} tick={CHART.tick} axisLine={false} tickLine={false} minTickGap={24} />
                  <YAxis domain={[0, 100]} tick={CHART.tick} axisLine={false} tickLine={false} unit="%" />
                  <Tooltip
                    content={<ChartTooltip labelFormatter={(l) => formatDateTime(String(l))} valueFormatter={(v) => `${v}%`} />}
                  />
                  <Line
                    type="monotone"
                    dataKey="score"
                    name="Score"
                    stroke={CHART.series1}
                    strokeWidth={2}
                    dot={trend.length < 20 ? { r: 3, strokeWidth: 0, fill: CHART.series1 } : false}
                    activeDot={{ r: 4, strokeWidth: 2, stroke: "hsl(var(--card))" }}
                  />
                </LineChart>
              </ResponsiveContainer>
            ) : (
              <EmptyState title="No compliance runs yet" icon={ClipboardCheck} />
            )}
          </CardContent>
        </Card>
      </div>

      <div className="mt-4 grid gap-4 lg:grid-cols-2 xl:grid-cols-4">
        <Card>
          <CardHeader>
            <CardTitle>Top users</CardTitle>
            <CardDescription>Device commands, last 7 days</CardDescription>
          </CardHeader>
          <CardContent>
            {loading ? (
              <ChartSkeleton />
            ) : (
              <RankedBars
                items={(d?.top_users ?? []).map((u) => ({ label: u.user, value: u.commands }))}
                hrefFor={(u) => `/accounting?user=${encodeURIComponent(u)}`}
                empty="No accounting records"
              />
            )}
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>Most active devices</CardTitle>
            <CardDescription>Device commands, last 7 days</CardDescription>
          </CardHeader>
          <CardContent>
            {loading ? (
              <ChartSkeleton />
            ) : (
              <RankedBars
                items={(d?.top_devices ?? []).map((u) => ({ label: u.device, value: u.commands }))}
                hrefFor={(dev) => `/accounting?device=${encodeURIComponent(dev)}`}
                empty="No accounting records"
              />
            )}
          </CardContent>
        </Card>

        <Card className="lg:col-span-2">
          <CardHeader className="flex-row items-center justify-between">
            <div>
              <CardTitle>Recent configuration changes</CardTitle>
              <CardDescription>Backups that changed the stored config</CardDescription>
            </div>
            <Link href="/backups?changed_only=1" className="text-xs text-primary hover:underline">
              View all
            </Link>
          </CardHeader>
          <CardContent className="px-0 pb-2">
            {loading ? (
              <div className="grid gap-2 px-4">
                {Array.from({ length: 5 }).map((_, i) => (
                  <Skeleton key={i} className="h-8" />
                ))}
              </div>
            ) : d?.recent_changes.length ? (
              <ul className="divide-y">
                {d.recent_changes.map((c) => (
                  <li key={c.id}>
                    <Link
                      href={c.commit ? `/devices/${c.device_id}?tab=diff&new=${c.commit}` : `/devices/${c.device_id}`}
                      className="flex items-center gap-3 px-4 py-2 text-sm hover:bg-muted/40"
                    >
                      <GitCompare className="h-4 w-4 shrink-0 text-muted-foreground" />
                      <div className="min-w-0 flex-1">
                        <p className="truncate font-medium">{c.device}</p>
                        <p className="truncate text-xs text-muted-foreground">
                          {c.author ?? "unknown"} · {c.reason ?? "scheduled"} · <span className="font-mono">{shortSha(c.commit)}</span>
                        </p>
                      </div>
                      <span className="text-xs tabular">
                        <span className="text-diff-add-fg">+{c.added}</span> <span className="text-diff-del-fg">−{c.removed}</span>
                      </span>
                      {c.risk !== null ? <RiskBadge score={c.risk} className="hidden sm:inline-flex" /> : null}
                      <RelativeTime value={c.at} className="hidden w-24 text-right text-xs text-muted-foreground md:inline" />
                    </Link>
                  </li>
                ))}
              </ul>
            ) : (
              <EmptyState title="No configuration changes recorded" icon={GitCompare} />
            )}
          </CardContent>
        </Card>
      </div>

      <div className="mt-4 grid gap-4 lg:grid-cols-3">
        <Card className="lg:col-span-2">
          <CardHeader className="flex-row items-center justify-between">
            <div>
              <CardTitle>Recent audit events</CardTitle>
              <CardDescription>Tamper-evident trail of portal actions</CardDescription>
            </div>
            <Link href="/audit" className="text-xs text-primary hover:underline">
              Open audit log
            </Link>
          </CardHeader>
          <CardContent className="px-0 pb-2">
            {loading ? (
              <div className="grid gap-2 px-4">
                {Array.from({ length: 5 }).map((_, i) => (
                  <Skeleton key={i} className="h-6" />
                ))}
              </div>
            ) : d?.recent_audit.length ? (
              <ul className="divide-y text-sm">
                {d.recent_audit.map((a, i) => (
                  <li key={i} className="flex items-center gap-3 px-4 py-1.5">
                    <span className="w-28 shrink-0 truncate font-medium">{a.actor}</span>
                    <code className="truncate rounded bg-muted px-1.5 py-0.5 font-mono text-[11px]">{a.action}</code>
                    <span className="truncate text-muted-foreground">{a.target ?? ""}</span>
                    <RelativeTime value={a.at} className="ml-auto shrink-0 text-xs text-muted-foreground" />
                  </li>
                ))}
              </ul>
            ) : (
              <EmptyState title="No audit events" />
            )}
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>Reachability & sites</CardTitle>
            <CardDescription>Device status and largest sites</CardDescription>
          </CardHeader>
          <CardContent className="grid gap-4">
            {loading ? (
              <ChartSkeleton />
            ) : (
              <>
                <div className="flex flex-wrap gap-2">
                  {Object.entries(d?.devices.by_reachability ?? {}).map(([k, v]) => (
                    <div key={k} className={cn("rounded-md border px-2.5 py-1.5")}>
                      <p className="text-[11px] text-muted-foreground">{humanize(k)}</p>
                      <p className="text-base font-semibold tabular">{formatNumber(v)}</p>
                    </div>
                  ))}
                </div>
                <RankedBars
                  items={(d?.devices.by_site ?? []).map((s) => ({ label: s.name, value: s.count }))}
                  valueLabel="devices"
                  empty="No sites"
                />
              </>
            )}
          </CardContent>
        </Card>
      </div>
    </>
  );
}
