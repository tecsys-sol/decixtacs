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
import { Badge } from "@/components/ui/badge";
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
  runs,
  selected,
  onSelect,
}: {
  commits: CommitInfo[];
  backups: Map<string, Backup>;
  runs: Map<string, { count: number; last: string }>;
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
                onClick={() => onSelect(c, parent)}
                aria-pressed={on}
                title={parent ? `Compare with ${shortSha(parent.sha)}` : "First stored version - shown in full"}
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
                  <span className="font-mono text-[11.5px] text-muted-foreground">
                    {shortSha(c.sha, 7)}
                    {c.source === "rancid" ? (
                      <Badge variant="muted" className="ml-1.5 px-1.5 py-0 font-sans text-[10.5px]" title="Imported from RANCID's CVS history">
                        RANCID
                      </Badge>
                    ) : null}
                    {(runs.get(c.sha)?.count ?? 0) > 1 ? (
                      <span className="ml-1.5 font-sans">
                        · confirmed by {runs.get(c.sha)!.count} backups, last <RelativeTime value={runs.get(c.sha)!.last} />
                      </span>
                    ) : null}
                  </span>
                </span>
              </button>
            </li>
          );
        })}
      </ul>
    </section>
  );
}

/** Base revision meaning "nothing": the first stored version is diffed against an empty config. */
const EMPTY = "empty";

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
  const history = useDeviceHistory(device.id, 1000);
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
  // every backup run (also the unchanged scheduled ones) counted against the version it confirmed
  const runs = React.useMemo(() => {
    const m = new Map<string, { count: number; last: string }>();
    for (const b of backups.data?.items ?? []) {
      if (!b.commit_sha || b.status === "failed") continue;
      const cur = m.get(b.commit_sha) ?? { count: 0, last: b.collected_at };
      cur.count += 1;
      if (b.collected_at > cur.last) cur.last = b.collected_at;
      m.set(b.commit_sha, cur);
    }
    return m;
  }, [backups.data]);

  // Defaults: newest commit vs. the one before it; if only `new` is given, compare with its parent.
  const effectiveNew = newRev || commits[0]?.sha || "";
  const effectiveOld = React.useMemo(() => {
    if (oldRev) return oldRev;
    const idx = commits.findIndex((c) => c.sha === effectiveNew || c.sha.startsWith(effectiveNew));
    // the first stored version has no parent: compare it with an empty config
    return idx >= 0 ? (commits[idx + 1]?.sha ?? EMPTY) : (commits[1]?.sha ?? EMPTY);
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

  const options = [
    ...commits.map((c) => ({ value: c.sha, label: `${shortSha(c.sha)} · ${formatDateTime(c.timestamp)} · ${c.author}${c.source === "rancid" ? " · RANCID" : ""}` })),
    { value: EMPTY, label: "(empty - before the first backup)" },
  ];
  // keep a revision passed via URL selectable even if it is outside the loaded history window
  for (const rev of [effectiveOld, effectiveNew]) {
    if (rev && !options.some((o) => o.value === rev)) options.push({ value: rev, label: rev });
  }

  if (history.isLoading) return <Skeleton className="h-[60vh]" />;
  if (history.error) return <ErrorState error={history.error} onRetry={() => void history.refetch()} />;
  if (commits.length === 0 && !oldRev) {
    return (
      <section className="rounded-xl border bg-card">
        <EmptyState icon={GitCompare} title="No configuration stored yet" description="Run a backup to store the first version of this device's configuration." />
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
        <CommitList commits={commits} backups={bySha} runs={runs} selected={effectiveNew} onSelect={(c, parent) => onChange(parent?.sha ?? "", c.sha)} />
        <div className="rise flex min-w-0 flex-col gap-3" style={{ animationDelay: ".3s" }}>
          <div className="flex flex-wrap items-center gap-2">
            <SimpleSelect aria-label="Old revision" value={effectiveOld} onValueChange={(v) => onChange(v, effectiveNew)} options={options} className="w-full sm:w-72" />
            <Button variant="ghost" size="icon-sm" aria-label="Swap revisions" onClick={() => onChange(effectiveNew, effectiveOld)}>
              <ArrowLeftRight />
            </Button>
            <SimpleSelect aria-label="New revision" value={effectiveNew} onValueChange={(v) => onChange(effectiveOld, v)} options={options} className="w-full sm:w-72" />
          </div>
          {effectiveOld === EMPTY ? (
            <p className="rounded-lg border border-dashed bg-muted/30 px-3 py-2 text-[13px] text-ink-3" data-testid="first-version-note">
              This is the first stored version of the configuration, shown in full against an empty config.
              {commits.length < 2 ? " Changes appear here as a diff once the configuration changes and the next backup stores a new version." : ""}
            </p>
          ) : null}
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
      <BackupRuns items={backups.data?.items ?? []} onSelect={(sha) => onChange("", sha)} />
    </div>
  );
}

/** Every backup run of the device - also unchanged scheduled ones - and the version it stored or confirmed. */
function BackupRuns({ items, onSelect }: { items: Backup[]; onSelect: (sha: string) => void }) {
  const [all, setAll] = React.useState(false);
  const rows = all ? items : items.slice(0, 25);
  if (!items.length) return null;
  return (
    <section className="rise overflow-hidden rounded-xl border bg-card" style={{ animationDelay: ".34s" }} data-testid="backup-runs">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b px-4 py-3">
        <div>
          <h2 className="font-display text-[15px] font-semibold">Backup runs</h2>
          <p className="text-xs text-ink-3">
            Every collection, newest first. <b>Unchanged</b> runs found the same configuration and confirm the version shown; only <b>changed</b> runs create a new
            version above.
          </p>
        </div>
        <span className="text-xs text-ink-3">
          {items.length} run{items.length === 1 ? "" : "s"} · {items.filter((b) => b.changed).length} changed · {items.filter((b) => b.status === "failed").length} failed
        </span>
      </div>
      <div className="max-h-[420px] overflow-y-auto scrollbar-thin">
        <table className="w-full text-sm">
          <thead className="sticky top-0 bg-card text-left text-[11px] uppercase tracking-wide text-muted-foreground">
            <tr>
              <th className="px-4 py-2 font-medium">When</th>
              <th className="px-2 py-2 font-medium">Result</th>
              <th className="px-2 py-2 font-medium">Version</th>
              <th className="px-2 py-2 font-medium">Trigger</th>
              <th className="px-2 py-2 font-medium">Details</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((b) => (
              <tr key={b.id} className="border-t border-border/60">
                <td className="whitespace-nowrap px-4 py-1.5 text-xs">{formatDateTime(b.collected_at)}</td>
                <td className="px-2 py-1.5">
                  {b.status === "failed" ? (
                    <span className="rounded bg-danger-soft px-1.5 py-0.5 text-[11px] font-semibold text-danger">failed</span>
                  ) : b.changed ? (
                    <span className="rounded bg-accent px-1.5 py-0.5 text-[11px] font-semibold text-accent-foreground">changed</span>
                  ) : (
                    <span className="rounded bg-secondary px-1.5 py-0.5 text-[11px] font-semibold text-ink-3">unchanged</span>
                  )}
                </td>
                <td className="px-2 py-1.5">
                  {b.commit_sha ? (
                    <button type="button" className="font-mono text-xs text-primary hover:underline" onClick={() => onSelect(b.commit_sha!)}>
                      {shortSha(b.commit_sha, 8)}
                    </button>
                  ) : (
                    "—"
                  )}
                </td>
                <td className="px-2 py-1.5 text-xs">{humanize(b.trigger)}</td>
                <td className="max-w-[420px] truncate px-2 py-1.5 text-xs text-ink-3" title={b.error ?? b.reason ?? undefined}>
                  {b.status === "failed" ? b.error : b.changed ? `${b.reason ?? ""} · +${b.lines_added} −${b.lines_removed}${b.author ? ` · ${b.author}` : ""}` : "configuration identical to the version"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {items.length > 25 ? (
        <button type="button" className="w-full border-t py-2 text-xs font-semibold text-primary hover:bg-row-hover" onClick={() => setAll((v) => !v)}>
          {all ? "Show fewer" : `Show all ${items.length} runs`}
        </button>
      ) : null}
    </section>
  );
}
