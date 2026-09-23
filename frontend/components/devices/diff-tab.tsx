"use client";

import { useQuery } from "@tanstack/react-query";
import { ArrowLeftRight, GitCommitHorizontal, GitCompare, ShieldCheck } from "lucide-react";
import * as React from "react";

import { Chart, useChartTheme } from "@/components/charts/chart";
import { ChartBody, ChartCard } from "@/components/common/chart-card";
import { EmptyState } from "@/components/common/empty-state";
import { ErrorState } from "@/components/common/error-state";
import { RelativeTime } from "@/components/common/relative-time";
import { DiffViewer } from "@/components/diff/diff-viewer";
import { Button } from "@/components/ui/button";
import { SimpleSelect } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { api } from "@/lib/api";
import { divergingBarOption, gaugeOption, lineOption, type ChartTheme } from "@/lib/charts";
import { riskLevel } from "@/lib/status";
import type { Backup, CommitInfo, Device, DiffOut, Page } from "@/lib/types";
import { cn, formatDate, formatDateTime, humanize, parseDate, shortSha } from "@/lib/utils";

import { useDeviceHistory } from "./use-device-history";

function riskColor(level: string, theme: ChartTheme): string {
  const s = theme.status;
  return level === "low" ? s.success : level === "medium" ? s.warning : s.danger;
}

/** All stored backup records of a device (commit -> lines changed, size, risk). */
export function useDeviceBackups(deviceId: string) {
  return useQuery({
    queryKey: ["backups", "device", deviceId, "all"],
    queryFn: () => api.get<Page<Backup>>("/backups", { device_id: deviceId, limit: 500 }),
  });
}

type DotKind = "selected" | "planned" | "unplanned" | "failed" | "plain";

const DOT_CLS: Record<DotKind, string> = {
  selected: "bg-[var(--ill-brand)]",
  planned: "bg-[var(--ill-green)]",
  unplanned: "bg-[var(--ill-orange)]",
  failed: "bg-danger",
  plain: "bg-[var(--ill-brand-2)]",
};

const DOT_LABEL: Record<DotKind, string> = {
  selected: "Selected revision",
  planned: "Linked to a change request",
  unplanned: "Unplanned change (no change request)",
  failed: "Collected with errors",
  plain: "Revision",
};

function CommitList({
  commits,
  backups,
  selected,
  onSelect,
}: {
  commits: CommitInfo[];
  backups: Map<string, Backup>;
  selected: string;
  onSelect: (c: CommitInfo, parent: CommitInfo | undefined) => void;
}) {
  return (
    <section className="rise flex min-h-0 flex-col gap-1 rounded-xl border bg-card p-4" style={{ animationDelay: ".26s" }}>
      <h2 className="font-display text-[15px] font-semibold">Commits</h2>
      <p className="mb-2 flex flex-wrap gap-x-3 gap-y-1 text-[11.5px] text-ink-3">
        {(["planned", "unplanned", "failed"] as const).map((k) => (
          <span key={k} className="inline-flex items-center gap-1.5">
            <span className={cn("h-2 w-2 rounded-full", DOT_CLS[k])} aria-hidden />
            {k === "planned" ? "Change request" : k === "unplanned" ? "Unplanned" : "Failed"}
          </span>
        ))}
      </p>
      <ul className="-mx-1 flex max-h-[560px] flex-col gap-1.5 overflow-y-auto px-1 scrollbar-thin" aria-label="Configuration commits">
        {commits.map((c, i) => {
          const b = backups.get(c.sha);
          const on = c.sha === selected || (!!selected && c.sha.startsWith(selected));
          const parent = commits[i + 1];
          const kind: DotKind = on ? "selected" : !parent ? "plain" : b?.status === "failed" ? "failed" : b?.changed ? (b.change_request_id ? "planned" : "unplanned") : "plain";
          return (
            <li key={c.sha}>
              <button
                type="button"
                disabled={!parent}
                onClick={() => onSelect(c, parent)}
                aria-pressed={on}
                title={parent ? `Compare with ${shortSha(parent.sha)}` : "Oldest revision - nothing to compare with"}
                className={cn(
                  "flex w-full items-start gap-2.5 rounded-lg border px-3 py-2.5 text-left transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:cursor-default",
                  on ? "border-[var(--ill-soft)] bg-[var(--ill-softer)]" : "border-border/70 bg-card hover:bg-row-hover",
                )}
              >
                <span className={cn("mt-[5px] h-[9px] w-[9px] shrink-0 rounded-full", DOT_CLS[kind])} role="img" aria-label={DOT_LABEL[kind]} />
                <span className="flex min-w-0 flex-col gap-0.5">
                  <span className="truncate text-[13px] font-bold">{c.message.split("\n")[0] || "(no message)"}</span>
                  <span className="truncate text-xs text-ink-3">
                    {c.author}
                    {b?.changed ? (
                      <>
                        {" · "}
                        <span className="font-mono text-success">+{b.lines_added}</span> <span className="font-mono text-danger">−{b.lines_removed}</span>
                      </>
                    ) : null}
                    {" · "}
                    <RelativeTime value={c.timestamp} />
                  </span>
                  <span className="font-mono text-[11.5px] text-muted-foreground">{shortSha(c.sha, 7)}</span>
                </span>
              </button>
            </li>
          );
        })}
      </ul>
    </section>
  );
}

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
  const theme = useChartTheme();
  const history = useDeviceHistory(device.id);
  const backups = useDeviceBackups(device.id);
  const commits = React.useMemo(() => history.data ?? [], [history.data]);
  const bySha = React.useMemo(() => {
    const m = new Map<string, Backup>();
    // unchanged polls reuse the last sha; the record that created the commit is the changing one
    for (const b of backups.data?.items ?? []) {
      if (!b.commit_sha) continue;
      const cur = m.get(b.commit_sha);
      if (!cur || (b.changed && !cur.changed)) m.set(b.commit_sha, b);
    }
    return m;
  }, [backups.data]);

  // Defaults: newest commit vs. the one before it; if only `new` is given, compare with its parent.
  const effectiveNew = newRev || commits[0]?.sha || "";
  const effectiveOld = React.useMemo(() => {
    if (oldRev) return oldRev;
    const idx = commits.findIndex((c) => c.sha === effectiveNew || c.sha.startsWith(effectiveNew));
    return idx >= 0 ? (commits[idx + 1]?.sha ?? "") : (commits[1]?.sha ?? "");
  }, [oldRev, commits, effectiveNew]);

  const diff = useQuery({
    queryKey: ["device", device.id, "diff", effectiveOld, effectiveNew],
    queryFn: () => api.get<DiffOut>(`/devices/${device.id}/diff`, { old: effectiveOld, new: effectiveNew, context: 3 }),
    enabled: !!effectiveOld && !!effectiveNew,
  });

  // --- charts ------------------------------------------------------------------------------
  const churn = React.useMemo(() => {
    const changed = (backups.data?.items ?? []).filter((b) => b.changed).slice(0, 30).reverse();
    return {
      n: changed.length,
      option: divergingBarOption(
        {
          categories: changed.map((b) => shortSha(b.commit_sha, 7)),
          added: changed.map((b) => b.lines_added),
          removed: changed.map((b) => b.lines_removed),
          details: changed.map((b) => `${shortSha(b.commit_sha, 7)} · ${b.reason ?? humanize(b.trigger)} · ${b.author ?? "unknown"} · ${formatDate(b.collected_at)}`),
        },
        theme,
      ),
    };
  }, [backups.data, theme]);

  const size = React.useMemo(() => {
    const rows = (backups.data?.items ?? [])
      .filter((b) => b.size_bytes != null && b.status !== "failed")
      .sort((a, b) => (parseDate(a.collected_at)?.getTime() ?? 0) - (parseDate(b.collected_at)?.getTime() ?? 0));
    return {
      n: rows.length,
      option: lineOption(
        {
          categories: rows.map((b) => formatDate(b.collected_at)),
          series: [{ name: "Config size (KB)", data: rows.map((b) => Math.round(((b.size_bytes ?? 0) / 1024) * 10) / 10) }],
          area: true,
          min: "dataMin",
          format: (v) => `${v} KB`,
          axisFormat: (v) => `${v}`,
          markMax: rows.length > 2,
          showSymbols: rows.length <= 12,
        },
        theme,
      ),
    };
  }, [backups.data, theme]);

  const risk = diff.data?.risk;
  const level = risk ? (risk.level as string) || riskLevel(risk.score) : "low";
  const riskOption = React.useMemo(
    () => gaugeOption({ value: risk ? risk.score : null, variant: "ring", label: risk ? `${humanize(level)} risk` : "No diff selected", color: riskColor(level, theme) }, theme),
    [risk, level, theme],
  );

  const options = commits.map((c) => ({ value: c.sha, label: `${shortSha(c.sha)} · ${formatDateTime(c.timestamp)} · ${c.author}` }));
  // keep a revision passed via URL selectable even if it is outside the loaded history window
  for (const rev of [effectiveOld, effectiveNew]) {
    if (rev && !options.some((o) => o.value === rev)) options.push({ value: rev, label: rev });
  }

  if (history.isLoading) return <Skeleton className="h-[60vh]" />;
  if (history.error) return <ErrorState error={history.error} onRetry={() => void history.refetch()} />;
  if (commits.length < 2 && !oldRev) {
    return (
      <section className="rounded-xl border bg-card">
        <EmptyState icon={GitCompare} title="Nothing to compare yet" description="At least two stored revisions are needed for a diff. Run a backup after the next change." />
      </section>
    );
  }
  const selectedCommit = commits.find((c) => c.sha === effectiveNew || c.sha.startsWith(effectiveNew));

  return (
    <div className="grid grid-cols-[minmax(0,1fr)] gap-4">
      <div className="grid gap-4 lg:grid-cols-2 xl:grid-cols-[1.6fr_1fr_0.8fr]">
        <ChartCard title="Lines changed per commit" description={`Last ${churn.n || 30} changing commits · added above, removed below the line`}>
          <ChartBody loading={backups.isLoading} error={backups.error} empty={!churn.n} emptyTitle="No changes recorded" emptyIcon={GitCommitHorizontal} height={190}>
            <Chart
              option={churn.option}
              height={190}
              ariaLabel="Lines added and removed per commit"
              onEvents={{
                click: (p) => {
                  const sha = (backups.data?.items ?? []).filter((b) => b.changed).slice(0, 30).reverse()[(p as { dataIndex: number }).dataIndex]?.commit_sha;
                  if (sha) onChange("", sha);
                },
              }}
            />
          </ChartBody>
        </ChartCard>
        <ChartCard title="Config size" description="Stored running config, per backup" delay={1}>
          <ChartBody loading={backups.isLoading} error={backups.error} empty={!size.n} emptyTitle="No size data yet" emptyIcon={GitCommitHorizontal} height={190}>
            <Chart option={size.option} height={190} ariaLabel="Config size over time" />
          </ChartBody>
        </ChartCard>
        <ChartCard title="Change risk" description="Selected diff" delay={2} className="lg:col-span-2 xl:col-span-1">
          <ChartBody loading={diff.isLoading} empty={!risk} emptyTitle="Select two revisions" emptyIcon={ShieldCheck} emptyArt="default" height={190}>
            <Chart option={riskOption} height={190} ariaLabel={`Change risk ${risk?.score ?? ""} ${level}`} />
          </ChartBody>
        </ChartCard>
      </div>

      <div className="grid grid-cols-[minmax(0,1fr)] gap-4 xl:grid-cols-[300px_minmax(0,1fr)]">
        <CommitList commits={commits} backups={bySha} selected={effectiveNew} onSelect={(c, parent) => onChange(parent?.sha ?? "", c.sha)} />
        <div className="rise flex min-w-0 flex-col gap-3" style={{ animationDelay: ".3s" }}>
          <div className="flex flex-wrap items-center gap-2">
            <SimpleSelect aria-label="Old revision" value={effectiveOld} onValueChange={(v) => onChange(v, effectiveNew)} options={options} className="w-full sm:w-72" />
            <Button variant="ghost" size="icon-sm" aria-label="Swap revisions" onClick={() => onChange(effectiveNew, effectiveOld)}>
              <ArrowLeftRight />
            </Button>
            <SimpleSelect aria-label="New revision" value={effectiveNew} onValueChange={(v) => onChange(effectiveOld, v)} options={options} className="w-full sm:w-72" />
          </div>
          {diff.isLoading ? (
            <Skeleton className="h-[60vh]" />
          ) : diff.error ? (
            <ErrorState error={diff.error} onRetry={() => void diff.refetch()} />
          ) : diff.data ? (
            <DiffViewer
              diff={diff.data}
              title={selectedCommit ? `${selectedCommit.message.split("\n")[0]} · ${selectedCommit.author}` : undefined}
              maxHeight="62vh"
            />
          ) : null}
        </div>
      </div>
    </div>
  );
}
