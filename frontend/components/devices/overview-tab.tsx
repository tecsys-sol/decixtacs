"use client";

import { useMutation, useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { Radar } from "lucide-react";
import * as React from "react";

import { KeyValue } from "@/components/common/field";
import { RelativeTime } from "@/components/common/relative-time";
import { StatusBadge } from "@/components/common/status-badge";
import { UnifiedDiffBlock } from "@/components/diff/diff-viewer";
import { RiskBadge } from "@/components/diff/risk-panel";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { useAuth } from "@/hooks/use-auth";
import { toast } from "@/hooks/use-toast";
import { api, errorMessage } from "@/lib/api";
import type { Backup, Device, Page } from "@/lib/types";
import { formatBytes, formatDateTime, humanize, shortSha } from "@/lib/utils";

export function OverviewTab({ device }: { device: Device }) {
  const { can } = useAuth();
  const [drift, setDrift] = React.useState<{ drifted: boolean; diff: string } | null>(null);
  const backups = useQuery({
    queryKey: ["backups", "device", device.id, "recent"],
    queryFn: () => api.get<Page<Backup>>("/backups", { device_id: device.id, limit: 8 }),
  });

  const driftCheck = useMutation({
    mutationFn: () => api.post<{ drifted: boolean; diff: string }>(`/devices/${device.id}/drift-check`),
    onSuccess: (r) => {
      setDrift(r);
      if (r.drifted) toast.warning("Drift detected", "The running config differs from the last backup.");
      else toast.success("No drift", "Running config matches the last backup.");
    },
    onError: (e) => toast.error("Drift check failed", errorMessage(e)),
  });

  return (
    <div className="grid gap-4 lg:grid-cols-3">
      <Card>
        <CardHeader>
          <CardTitle>Device</CardTitle>
        </CardHeader>
        <CardContent>
          <KeyValue
            items={[
              ["Hostname", device.hostname],
              ["Management IP", <span key="ip" className="font-mono">{device.management_ip}:{device.ssh_port}</span>],
              ["Site", device.site?.name],
              ["Vendor", device.vendor?.name],
              ["Platform", device.platform?.name],
              ["OS version", device.os_version],
              ["Serial", device.serial ? <span key="s" className="font-mono">{device.serial}</span> : null],
              ["Role", device.role ? humanize(device.role) : null],
              ["Status", <StatusBadge key="st" status={device.status} dot={false} />],
              ["Reachability", <StatusBadge key="r" status={device.reachability} />],
              ["NetBox ID", device.netbox_id],
              ["Created", formatDateTime(device.created_at)],
            ]}
          />
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Backup</CardTitle>
          <CardDescription>{device.backup_enabled ? "Included in scheduled backups" : "Scheduled backups disabled"}</CardDescription>
        </CardHeader>
        <CardContent className="grid gap-4">
          <KeyValue
            items={[
              ["Last backup", <RelativeTime key="lb" value={device.last_backup_at} />],
              ["Last status", device.last_backup_status ? <StatusBadge key="ls" status={device.last_backup_status} /> : null],
              ["Groups", device.groups?.length ? (
                <div key="g" className="flex flex-wrap gap-1">
                  {device.groups.map((g) => <Badge key={g.id} variant="secondary">{g.name}</Badge>)}
                </div>
              ) : null],
              ["Tags", device.tags.length ? (
                <div key="t" className="flex flex-wrap gap-1">
                  {device.tags.map((t) => <Badge key={t} variant="outline">{t}</Badge>)}
                </div>
              ) : null],
            ]}
          />
          {can("configs:backup") ? (
            <div>
              <Button variant="outline" size="sm" onClick={() => driftCheck.mutate()} loading={driftCheck.isPending}>
                <Radar /> Check drift now
              </Button>
              <p className="mt-1 text-xs text-muted-foreground">Collects the running config and compares it with the last backup without committing.</p>
            </div>
          ) : null}
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="flex-row items-center justify-between">
          <CardTitle>Recent backups</CardTitle>
          <Link href={`/devices/${device.id}?tab=history`} className="text-xs text-primary hover:underline">
            History
          </Link>
        </CardHeader>
        <CardContent className="px-0">
          {backups.isLoading ? (
            <div className="grid gap-2 px-4">{Array.from({ length: 4 }).map((_, i) => <Skeleton key={i} className="h-8" />)}</div>
          ) : backups.data?.items.length ? (
            <ul className="divide-y text-sm">
              {backups.data.items.map((b) => (
                <li key={b.id} className="flex items-center gap-2 px-4 py-2">
                  <StatusBadge status={b.status} dot={false} />
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-xs">
                      <span className="font-mono">{shortSha(b.commit_sha)}</span> · {b.reason ?? b.trigger} · {formatBytes(b.size_bytes)}
                    </p>
                    {b.error ? <p className="truncate text-xs text-destructive" title={b.error}>{b.error}</p> : null}
                  </div>
                  {b.changed ? (
                    <span className="text-xs tabular">
                      <span className="text-diff-add-fg">+{b.lines_added}</span> <span className="text-diff-del-fg">−{b.lines_removed}</span>
                    </span>
                  ) : null}
                  {b.risk_score !== null && b.changed ? <RiskBadge score={b.risk_score} /> : null}
                  <RelativeTime value={b.collected_at} className="w-20 text-right text-xs text-muted-foreground" />
                </li>
              ))}
            </ul>
          ) : (
            <p className="px-4 py-6 text-center text-xs text-muted-foreground">No backups yet.</p>
          )}
        </CardContent>
      </Card>

      {drift ? (
        <Card className="lg:col-span-3">
          <CardHeader>
            <CardTitle>Drift check result</CardTitle>
            <CardDescription>{drift.drifted ? "Running configuration differs from the last backup." : "No differences."}</CardDescription>
          </CardHeader>
          <CardContent>{drift.drifted ? <UnifiedDiffBlock text={drift.diff} /> : null}</CardContent>
        </Card>
      ) : null}
    </div>
  );
}
