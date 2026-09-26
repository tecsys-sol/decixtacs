"use client";

import { useQuery } from "@tanstack/react-query";
import { DatabaseBackup, GitCompare, LogIn, ShieldAlert, SquareTerminal, Users } from "lucide-react";
import Link from "next/link";
import * as React from "react";

import { Chart, useChartTheme } from "@/components/charts/chart";
import { ChartBody, ChartCard } from "@/components/common/chart-card";
import { EmptyState } from "@/components/common/empty-state";
import { ErrorState } from "@/components/common/error-state";
import { KpiTile } from "@/components/common/kpi-tile";
import { RelativeTime } from "@/components/common/relative-time";
import { RiskBadge } from "@/components/diff/risk-panel";
import { SessionsTable, type SessionSummary, type UserSession } from "@/components/sessions/user-sessions";
import { Badge } from "@/components/ui/badge";
import { Card, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Segmented } from "@/components/ui/tabs";
import { api } from "@/lib/api";
import { barOption, palette } from "@/lib/charts";
import type { Device } from "@/lib/types";
import { formatDateTime, formatNumber, humanize, shortSha } from "@/lib/utils";

interface Activity {
  days: number;
  accounting: boolean;
  summary: {
    changes: number;
    lines_added: number;
    lines_removed: number;
    backups: number;
    failed_backups: number;
    authors: number;
  } & Partial<SessionSummary>;
  per_day: { day: string; changes: number; sessions: number; commands: number; backups: number; failed: number }[];
  changes: { id: string; at: string; commit: string | null; author: string | null; reason: string | null; added: number; removed: number; risk: number | null; trigger: string; change_request_id: string | null; source?: "nom" | "rancid" }[];
  sessions: UserSession[];
  logins: { at: string; user: string; source: string | null; result: string; detail: string | null }[];
}

const PERIODS = ["7", "30", "90", "365"] as const;

/** Change-history dashboard for one device. */
export function ActivityTab({ device }: { device: Device }) {
  const theme = useChartTheme();
  const [days, setDays] = React.useState<(typeof PERIODS)[number]>("30");
  const [loginFilter, setLoginFilter] = React.useState<"all" | "fail">("all");
  const q = useQuery({
    queryKey: ["device", device.id, "activity", days],
    queryFn: () => api.get<Activity>(`/devices/${device.id}/activity`, { days }),
  });
  const a = q.data;
  const chart = React.useMemo(() => {
    if (!a) return null;
    const pal = palette(theme);
    return barOption(
      {
        categories: a.per_day.map((d) => d.day.slice(5)),
        series: [
          { name: "Config changes", data: a.per_day.map((d) => d.changes), color: pal[0] },
          ...(a.accounting ? [{ name: "Sessions", data: a.per_day.map((d) => d.sessions), color: pal[1] }] : []),
          { name: "Failed backups", data: a.per_day.map((d) => d.failed), color: theme.status.danger },
        ],
        barWidth: 10,
      },
      theme,
    );
  }, [a, theme]);

  if (q.isLoading) return <Skeleton className="h-[70vh]" />;
  if (q.error || !a) return <ErrorState error={q.error} onRetry={() => void q.refetch()} />;
  const s = a.summary;
  const logins = a.logins.filter((l) => loginFilter === "all" || l.result === "fail");

  return (
    <div className="grid gap-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-sm text-muted-foreground">Configuration changes, backups, engineer sessions and logins on {device.hostname}.</p>
        <Segmented
          aria-label="Period"
          value={days}
          onChange={(v) => setDays(v)}
          options={PERIODS.map((p) => ({ value: p, label: p === "365" ? "1 year" : `${p} days` }))}
        />
      </div>
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-3 xl:grid-cols-6">
        <KpiTile label="Config changes" value={formatNumber(s.changes)} icon={GitCompare} sub={`+${formatNumber(s.lines_added)} −${formatNumber(s.lines_removed)} lines`} />
        <KpiTile label="Backups" value={formatNumber(s.backups)} icon={DatabaseBackup} delay={1} sub={s.failed_backups ? `${s.failed_backups} failed` : "all succeeded"} tone={s.failed_backups ? "warning" : "success"} />
        {a.accounting ? (
          <>
            <KpiTile label="User sessions" value={formatNumber(s.sessions ?? 0)} icon={SquareTerminal} delay={2} sub={`${formatNumber(s.config_sessions ?? 0)} configured`} />
            <KpiTile label="Engineers" value={formatNumber(s.users ?? 0)} icon={Users} delay={3} />
            <KpiTile label="Commands" value={formatNumber(s.commands ?? 0)} icon={SquareTerminal} delay={4} sub={s.denied ? `${s.denied} denied` : undefined} tone={s.denied ? "warning" : "default"} />
            <KpiTile label="Logins" value={formatNumber(s.logins ?? 0)} icon={LogIn} delay={5} sub={s.failed_logins ? `${s.failed_logins} failed` : "no failures"} tone={s.failed_logins ? "danger" : "default"} />
          </>
        ) : null}
      </div>

      <ChartCard title="Activity per day" description={`Last ${a.days} days`}>
        <ChartBody empty={!a.per_day.length} emptyTitle="No activity in this period" height={220}>
          {chart ? <Chart option={chart} height={220} ariaLabel="Changes, sessions and failed backups per day" /> : null}
        </ChartBody>
      </ChartCard>

      <Card className="overflow-hidden">
        <CardHeader>
          <CardTitle>Configuration changes</CardTitle>
          <CardDescription>Every stored change, newest first, including revisions imported from RANCID. Unchanged scheduled backups are not listed.</CardDescription>
        </CardHeader>
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>When</TableHead>
              <TableHead>By</TableHead>
              <TableHead>Reason</TableHead>
              <TableHead>Lines</TableHead>
              <TableHead>Risk</TableHead>
              <TableHead>Version</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {a.changes.length === 0 ? (
              <TableRow>
                <TableCell colSpan={6}>
                  <EmptyState icon={GitCompare} title="No configuration changes in this period" compact />
                </TableCell>
              </TableRow>
            ) : null}
            {a.changes.map((c) => (
              <TableRow key={c.id}>
                <TableCell className="whitespace-nowrap text-xs" title={formatDateTime(c.at)}>
                  <RelativeTime value={c.at} />
                </TableCell>
                <TableCell className="font-medium">{c.author ?? "—"}</TableCell>
                <TableCell className="max-w-[360px] truncate text-sm" title={c.reason ?? undefined}>
                  {c.reason ?? humanize(c.trigger)}
                  {c.source === "rancid" ? (
                    <Badge variant="muted" className="ml-2" title="Imported from RANCID's CVS history">
                      RANCID
                    </Badge>
                  ) : null}
                  {c.change_request_id ? (
                    <Link href={`/changes/${c.change_request_id}`} className="ml-2">
                      <Badge variant="info">change request</Badge>
                    </Link>
                  ) : null}
                </TableCell>
                <TableCell className="font-mono text-xs">
                  <span className="text-success">+{c.added}</span> <span className="text-danger">−{c.removed}</span>
                </TableCell>
                <TableCell>{c.risk !== null ? <RiskBadge score={c.risk} /> : "—"}</TableCell>
                <TableCell>
                  {c.commit ? (
                    <Link href={`/devices/${device.id}?tab=diff&new=${c.commit}`} className="inline-flex items-center gap-1 font-mono text-xs text-primary hover:underline">
                      <GitCompare className="h-3.5 w-3.5" /> {shortSha(c.commit, 8)}
                    </Link>
                  ) : (
                    "—"
                  )}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </Card>

      {a.accounting ? (
        <>
          <Card className="overflow-hidden">
            <CardHeader>
              <CardTitle>User sessions</CardTitle>
              <CardDescription>Click a session for its command log; configuration commands are highlighted, denied ones struck through.</CardDescription>
            </CardHeader>
            <SessionsTable items={a.sessions} showDevice={false} />
            {a.sessions.length >= 200 ? (
              <p className="border-t px-4 py-2 text-xs text-muted-foreground">
                Latest 200 shown - see <Link href={`/sessions?device_id=${device.id}&days=${Math.min(Number(days), 90)}`} className="text-primary hover:underline">Sessions</Link> for all.
              </p>
            ) : null}
          </Card>

          <Card className="overflow-hidden">
            <CardHeader className="flex-row items-center justify-between">
              <div>
                <CardTitle>Login history</CardTitle>
                <CardDescription>TACACS+ authentications on this device.</CardDescription>
              </div>
              <Segmented
                aria-label="Logins"
                value={loginFilter}
                onChange={setLoginFilter}
                options={[
                  { value: "all", label: "All" },
                  { value: "fail", label: <><ShieldAlert /> Failed</> },
                ]}
              />
            </CardHeader>
            <div className="max-h-[420px] overflow-y-auto scrollbar-thin">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>When</TableHead>
                    <TableHead>User</TableHead>
                    <TableHead>From</TableHead>
                    <TableHead>Result</TableHead>
                    <TableHead>Detail</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {logins.length === 0 ? (
                    <TableRow>
                      <TableCell colSpan={5}>
                        <EmptyState icon={LogIn} title={loginFilter === "fail" ? "No failed logins" : "No logins in this period"} compact />
                      </TableCell>
                    </TableRow>
                  ) : null}
                  {logins.map((l, i) => (
                    <TableRow key={i}>
                      <TableCell className="whitespace-nowrap text-xs">{formatDateTime(l.at)}</TableCell>
                      <TableCell className="font-medium">{l.user}</TableCell>
                      <TableCell className="font-mono text-xs">{l.source ?? "—"}</TableCell>
                      <TableCell>{l.result === "pass" ? <Badge variant="success">success</Badge> : l.result === "fail" ? <Badge variant="danger">failed</Badge> : <Badge variant="muted">{l.result}</Badge>}</TableCell>
                      <TableCell className="max-w-[320px] truncate text-xs text-muted-foreground">{l.detail ?? "—"}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          </Card>
        </>
      ) : (
        <Card>
          <EmptyState icon={SquareTerminal} title="Sessions and logins need the accounting permission" compact />
        </Card>
      )}
    </div>
  );
}
