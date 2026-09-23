"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { CheckCircle2, ClipboardCheck } from "lucide-react";

import * as React from "react";

import { Chart, useChartMode } from "@/components/charts/chart";
import { EmptyState } from "@/components/common/empty-state";
import { ErrorState } from "@/components/common/error-state";
import { RelativeTime } from "@/components/common/relative-time";
import { StatusBadge } from "@/components/common/status-badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { api } from "@/lib/api";
import { donutOption, gaugeOption, STATUS } from "@/lib/charts";
import { scoreColor } from "@/lib/status";
import type { ComplianceRun, ComplianceRunDetail, Device } from "@/lib/types";
import { cn } from "@/lib/utils";

function DeviceGauges({ score, fleet }: { score: { score: number; passed: number; failed: number }; fleet: number | null }) {
  const mode = useChartMode();
  const gauge = React.useMemo(
    () => gaugeOption({ value: Math.round(score.score * 10) / 10, label: fleet == null ? "device score" : `${score.score >= fleet ? "+" : "−"}${Math.abs(score.score - fleet).toFixed(1)} vs fleet`, gradient: true }, mode),
    [score, fleet, mode],
  );
  const checks = React.useMemo(
    () =>
      donutOption(
        {
          items: [
            { name: "Passed", value: score.passed, color: STATUS[mode].success },
            { name: "Failed", value: score.failed, color: STATUS[mode].danger },
          ],
          centerValue: String(score.passed + score.failed),
          centerLabel: "checks",
        },
        mode,
      ),
    [score, mode],
  );
  return (
    <div className="grid grid-cols-1 gap-2 sm:grid-cols-2 md:grid-cols-1 xl:grid-cols-2">
      <Chart option={gauge} height={180} ariaLabel={`Device compliance score ${score.score.toFixed(1)}`} />
      <Chart option={checks} height={180} ariaLabel="Passed and failed checks" />
    </div>
  );
}

export function ComplianceTab({ device }: { device: Device }) {
  const latest = useQuery({
    queryKey: ["compliance", "runs", 1],
    queryFn: () => api.get<ComplianceRun[]>("/compliance/runs", { limit: 1 }),
  });
  const runId = latest.data?.[0]?.id;
  const detail = useQuery({
    queryKey: ["compliance", "run", runId],
    queryFn: () => api.get<ComplianceRunDetail>(`/compliance/runs/${runId}`),
    enabled: !!runId,
  });

  if (latest.isLoading || (runId && detail.isLoading)) return <Skeleton className="h-64" />;
  if (latest.error || detail.error) return <ErrorState error={latest.error ?? detail.error} onRetry={() => void latest.refetch()} />;
  if (!runId || !detail.data) {
    return <EmptyState icon={ClipboardCheck} title="No compliance runs yet" description="Run compliance checks from the Compliance page." />;
  }
  const score = detail.data.devices.find((d) => d.device_id === device.id);
  const failures = detail.data.failures.filter((f) => f.device === device.hostname);
  const fleet = detail.data.devices.length ? detail.data.devices.reduce((a, d) => a + d.score, 0) / detail.data.devices.length : null;

  return (
    <div className="grid gap-4 md:grid-cols-3">
      <Card>
        <CardHeader>
          <CardTitle>Compliance score</CardTitle>
          <CardDescription>
            Run <Link className="text-primary hover:underline" href={`/compliance/runs/${runId}`}>{runId.slice(0, 8)}</Link> ·{" "}
            <RelativeTime value={detail.data.run.started_at} />
          </CardDescription>
        </CardHeader>
        <CardContent>
          {score ? (
            <>
              <DeviceGauges score={score} fleet={fleet} />
              <p className={cn("mt-1 text-center text-xs font-semibold", scoreColor(score.score))}>
                {score.passed} passed · {score.failed} failed
                {fleet != null ? <span className="font-normal text-ink-3"> · fleet average {fleet.toFixed(1)}%</span> : null}
              </p>
            </>
          ) : (
            <p className="text-sm text-muted-foreground">This device was not evaluated in the latest run.</p>
          )}
        </CardContent>
      </Card>
      <Card className="md:col-span-2">
        <CardHeader>
          <CardTitle>Failed rules</CardTitle>
        </CardHeader>
        <CardContent className="px-0">
          {failures.length ? (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Rule</TableHead>
                  <TableHead>Severity</TableHead>
                  <TableHead className="w-full">Detail</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {failures.map((f, i) => (
                  <TableRow key={i}>
                    <TableCell className="whitespace-nowrap font-medium">{f.rule}</TableCell>
                    <TableCell>
                      <StatusBadge status={f.severity} dot={false} />
                    </TableCell>
                    <TableCell className="text-xs text-muted-foreground">{f.detail}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          ) : (
            <EmptyState icon={CheckCircle2} art="success" title="All rules passed" />
          )}
        </CardContent>
      </Card>
    </div>
  );
}
