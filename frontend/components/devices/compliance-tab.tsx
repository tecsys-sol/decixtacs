"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { CheckCircle2, ClipboardCheck } from "lucide-react";

import { EmptyState } from "@/components/common/empty-state";
import { ErrorState } from "@/components/common/error-state";
import { RelativeTime } from "@/components/common/relative-time";
import { StatusBadge } from "@/components/common/status-badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { api } from "@/lib/api";
import { scoreColor } from "@/lib/status";
import type { ComplianceRun, ComplianceRunDetail, Device } from "@/lib/types";
import { cn } from "@/lib/utils";

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
              <p className={cn("text-4xl font-semibold tabular", scoreColor(score.score))}>{score.score.toFixed(1)}%</p>
              <p className="mt-1 text-xs text-muted-foreground">
                {score.passed} passed · {score.failed} failed
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
            <EmptyState icon={CheckCircle2} title="All rules passed" />
          )}
        </CardContent>
      </Card>
    </div>
  );
}
