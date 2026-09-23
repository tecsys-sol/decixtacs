"use client";

import { useQuery } from "@tanstack/react-query";
import { ArrowLeftRight, GitCompare } from "lucide-react";
import * as React from "react";

import { EmptyState } from "@/components/common/empty-state";
import { ErrorState } from "@/components/common/error-state";
import { DiffViewer } from "@/components/diff/diff-viewer";
import { Button } from "@/components/ui/button";
import { SimpleSelect } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { api } from "@/lib/api";
import type { Device, DiffOut } from "@/lib/types";
import { formatDateTime, shortSha } from "@/lib/utils";

import { useDeviceHistory } from "./use-device-history";

export function DiffTab({
  device,
  oldRev,
  newRev,
  onChange,
}: {
  device: Device;
  oldRev: string;
  newRev: string;
  onChange: (oldRev: string, newRev: string) => void;
}) {
  const history = useDeviceHistory(device.id);
  const commits = React.useMemo(() => history.data ?? [], [history.data]);

  // Defaults: newest commit vs. the one before it; if only `new` is given, compare with its parent.
  const effectiveNew = newRev || commits[0]?.sha || "";
  const effectiveOld = React.useMemo(() => {
    if (oldRev) return oldRev;
    const idx = commits.findIndex((c) => c.sha === effectiveNew || c.sha.startsWith(effectiveNew));
    return idx >= 0 ? commits[idx + 1]?.sha ?? "" : commits[1]?.sha ?? "";
  }, [oldRev, commits, effectiveNew]);

  const diff = useQuery({
    queryKey: ["device", device.id, "diff", effectiveOld, effectiveNew],
    queryFn: () => api.get<DiffOut>(`/devices/${device.id}/diff`, { old: effectiveOld, new: effectiveNew, context: 3 }),
    enabled: !!effectiveOld && !!effectiveNew,
  });

  const options = commits.map((c) => ({ value: c.sha, label: `${shortSha(c.sha)} · ${formatDateTime(c.timestamp)} · ${c.author}` }));
  // keep a revision passed via URL selectable even if it is outside the loaded history window
  for (const rev of [effectiveOld, effectiveNew]) {
    if (rev && !options.some((o) => o.value === rev)) options.push({ value: rev, label: rev });
  }

  if (history.isLoading) return <Skeleton className="h-[60vh]" />;
  if (history.error) return <ErrorState error={history.error} onRetry={() => void history.refetch()} />;
  if (commits.length < 2 && !oldRev) {
    return <EmptyState icon={GitCompare} title="Nothing to compare yet" description="At least two stored revisions are needed for a diff." />;
  }

  return (
    <div className="grid gap-3">
      <div className="flex flex-wrap items-center gap-2">
        <SimpleSelect aria-label="Old revision" value={effectiveOld} onValueChange={(v) => onChange(v, effectiveNew)} options={options} className="w-full sm:w-80" />
        <Button variant="ghost" size="icon-sm" aria-label="Swap revisions" onClick={() => onChange(effectiveNew, effectiveOld)}>
          <ArrowLeftRight />
        </Button>
        <SimpleSelect aria-label="New revision" value={effectiveNew} onValueChange={(v) => onChange(effectiveOld, v)} options={options} className="w-full sm:w-80" />
      </div>
      {diff.isLoading ? (
        <Skeleton className="h-[60vh]" />
      ) : diff.error ? (
        <ErrorState error={diff.error} onRetry={() => void diff.refetch()} />
      ) : diff.data ? (
        <DiffViewer diff={diff.data} />
      ) : null}
    </div>
  );
}
