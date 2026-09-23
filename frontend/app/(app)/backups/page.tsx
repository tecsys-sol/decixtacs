"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { DatabaseBackup, GitCompare, Play, Trash2 } from "lucide-react";
import * as React from "react";

import { Chart, useChartMode } from "@/components/charts/chart";
import { ChartBody, ChartCard } from "@/components/common/chart-card";
import { ConfirmDialog, useConfirm } from "@/components/common/confirm-dialog";
import { EmptyState } from "@/components/common/empty-state";
import { Field } from "@/components/common/field";
import { FilterBar } from "@/components/common/filter-bar";
import { PageHeader } from "@/components/common/page-header";
import { Pagination } from "@/components/common/pagination";
import { RelativeTime } from "@/components/common/relative-time";
import { StatusBadge } from "@/components/common/status-badge";
import { TableState } from "@/components/common/table-skeleton";
import { RiskBadge } from "@/components/diff/risk-panel";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { SimpleSelect } from "@/components/ui/select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { useAuth } from "@/hooks/use-auth";
import { useRecentBackups } from "@/hooks/use-backup-stats";
import { useNow } from "@/hooks/use-now";
import { useDebounce } from "@/hooks/use-debounce";
import { useDeviceNames } from "@/hooks/use-lookups";
import { toast } from "@/hooks/use-toast";
import { useOnOpen } from "@/hooks/use-reset";
import { useUrlState } from "@/hooks/use-url-state";
import { api, errorMessage } from "@/lib/api";
import { countBy, dailySeries } from "@/lib/aggregate";
import { barOption, divergingBarOption, donutOption, palette, STATUS } from "@/lib/charts";
import { BACKUP_STATUSES, PAGE_SIZE } from "@/lib/constants";
import type { Backup, BackupRunResult, Change, Page } from "@/lib/types";
import { formatBytes, formatNumber, humanize, shortSha } from "@/lib/utils";

function RunBackupDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (o: boolean) => void }) {
  const qc = useQueryClient();
  const { can } = useAuth();
  const devices = useDeviceNames();
  const [all, setAll] = React.useState(true);
  const [selected, setSelected] = React.useState<string[]>([]);
  const [filter, setFilter] = React.useState("");
  const [reason, setReason] = React.useState("");
  const [changeId, setChangeId] = React.useState("");
  const changes = useQuery({
    queryKey: ["changes", "open-for-backup"],
    queryFn: () => api.get<Page<Change>>("/changes", { limit: 100 }),
    select: (p) => p.items.filter((c) => ["approved", "implemented", "pending_approval"].includes(c.state)),
    enabled: open && can("changes:read"),
  });

  useOnOpen(open, () => {
    setAll(true);
    setSelected([]);
    setReason("");
    setChangeId("");
    setFilter("");
  });

  const run = useMutation({
    mutationFn: () =>
      api.post<BackupRunResult>("/backups/run", {
        device_ids: all ? [] : selected,
        reason: reason.trim() || null,
        change_request_id: changeId || null,
        run_async: true,
      }),
    onSuccess: (r) => {
      toast.success("Backup started", r.task_id ? `Task ${r.task_id.slice(0, 8)} queued` : undefined);
      void qc.invalidateQueries({ queryKey: ["backups"] });
      onOpenChange(false);
    },
    onError: (e) => toast.error("Could not start backup", errorMessage(e)),
  });

  const list = (devices.data ?? []).filter((d) => !filter || d.hostname.toLowerCase().includes(filter.toLowerCase()));

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Run configuration backup</DialogTitle>
          <DialogDescription>Collect running configurations now and commit changes to Git.</DialogDescription>
        </DialogHeader>
        <div className="grid gap-4">
          <Checkbox label="All backup-enabled devices" checked={all} onCheckedChange={setAll} />
          {all ? null : (
            <div className="grid gap-2">
              <Input value={filter} onChange={(e) => setFilter(e.target.value)} placeholder="Filter devices" aria-label="Filter devices" />
              <div className="max-h-48 overflow-y-auto rounded-md border p-2">
                {list.length ? (
                  list.map((d) => (
                    <div key={d.id} className="py-0.5">
                      <Checkbox
                        label={<span className="font-mono text-xs">{d.hostname}</span>}
                        checked={selected.includes(d.id)}
                        onCheckedChange={(c) => setSelected((s) => (c ? [...s, d.id] : s.filter((x) => x !== d.id)))}
                      />
                    </div>
                  ))
                ) : (
                  <p className="py-4 text-center text-xs text-muted-foreground">No devices</p>
                )}
              </div>
              <p className="text-xs text-muted-foreground">{selected.length} selected</p>
            </div>
          )}
          <Field label="Reason" htmlFor="reason" hint="Recorded in the Git commit message and the audit log">
            <Input id="reason" value={reason} onChange={(e) => setReason(e.target.value)} placeholder="Pre-maintenance snapshot" />
          </Field>
          {can("changes:read") ? (
            <Field label="Change request" htmlFor="chg">
              <SimpleSelect
                id="chg"
                value={changeId}
                onValueChange={setChangeId}
                allowEmpty
                emptyLabel="None"
                placeholder="Link to a change (optional)"
                options={(changes.data ?? []).map((c) => ({ value: c.id, label: `CHG-${c.number} · ${c.title}` }))}
              />
            </Field>
          ) : null}
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button onClick={() => run.mutate()} loading={run.isPending} disabled={!all && selected.length === 0}>
            <Play /> Run backup
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

export default function BackupsPage() {
  const { can } = useAuth();
  const qc = useQueryClient();
  const devices = useDeviceNames();
  const mode = useChartMode();
  const now = useNow();
  const [filters, setFilters] = useUrlState({ changed_only: "", status: "", author: "", device: "", offset: "0" });
  const [author, setAuthor] = React.useState(filters.author);
  const debouncedAuthor = useDebounce(author, 400);
  const [runOpen, setRunOpen] = React.useState(false);
  const confirm = useConfirm<Backup>();
  const offset = Number(filters.offset) || 0;

  React.useEffect(() => {
    if (debouncedAuthor !== filters.author) setFilters({ author: debouncedAuthor, offset: "0" });
  }, [debouncedAuthor, filters.author, setFilters]);

  const q = useQuery({
    queryKey: ["backups", "list", filters],
    queryFn: () =>
      api.get<Page<Backup>>("/backups", {
        changed_only: filters.changed_only === "1" ? true : undefined,
        status: filters.status,
        author: filters.author,
        device_id: filters.device,
        limit: PAGE_SIZE,
        offset,
      }),
    placeholderData: (p) => p,
    refetchInterval: 30_000,
  });

  const del = useMutation({
    mutationFn: (b: Backup) => api.delete(`/backups/${b.id}`),
    onSuccess: () => {
      toast.success("Backup record deleted", "Git history is retained.");
      confirm.close();
      void qc.invalidateQueries({ queryKey: ["backups"] });
    },
  });

  const items = q.data?.items ?? [];
  const stats = useRecentBackups(30, {
    device_id: filters.device || undefined,
    status: filters.status || undefined,
    author: filters.author || undefined,
    changed_only: filters.changed_only === "1",
  });
  const charts = React.useMemo(() => {
    const rows = stats.data?.items ?? [];
    const statusItems = countBy(rows, (b) => (b.status === "failed" ? "failed" : b.changed ? "changed" : "unchanged"));
    const colors: Record<string, string> = { changed: palette(mode)[0], unchanged: STATUS[mode].neutral, failed: STATUS[mode].danger };
    const changed = rows.filter((b) => b.changed);
    const perDay = dailySeries(changed, (b) => b.collected_at, 30, now);
    const added = dailySeries(changed, (b) => b.collected_at, 30, now, (b) => b.lines_added);
    const removed = dailySeries(changed, (b) => b.collected_at, 30, now, (b) => b.lines_removed);
    return {
      n: rows.length,
      changed: changed.length,
      status: donutOption(
        { items: statusItems.map((i) => ({ name: humanize(i.name), value: i.value, color: colors[i.name] })), centerValue: formatNumber(rows.length), centerLabel: "backups" },
        mode,
      ),
      perDay: barOption({ categories: perDay.labels, series: [{ name: "Config changes", data: perDay.data }], barWidth: 12, axisLabelInterval: 4 }, mode),
      lines: divergingBarOption({ categories: added.labels, added: added.data, removed: removed.data, showCategoryLabels: true }, mode),
    };
  }, [stats.data, now, mode]);
  const statsNote = stats.data && stats.data.total > stats.data.items.length ? ` · latest ${stats.data.items.length} of ${formatNumber(stats.data.total)}` : "";

  return (
    <>
      <PageHeader
        title="Backups"
        description="Every configuration collection across the fleet, stored in Git."
        actions={
          can("configs:backup") ? (
            <Button onClick={() => setRunOpen(true)}>
              <DatabaseBackup /> Run backup
            </Button>
          ) : null
        }
      />
      <div className="mb-4 grid gap-4 lg:grid-cols-2 xl:grid-cols-3">
        <ChartCard title="Backup outcomes" description={`Last 30 days, matching the filters${statsNote}`}>
          <ChartBody loading={stats.isLoading} error={stats.error} empty={!charts.n} emptyTitle="No backups in 30 days" emptyIcon={DatabaseBackup} emptyArt="default" height={240}>
            <Chart option={charts.status} height={240} ariaLabel="Backup outcomes" />
          </ChartBody>
        </ChartCard>
        <ChartCard title="Changes per day" description="Collections that changed the stored config" delay={1}>
          <ChartBody loading={stats.isLoading} error={stats.error} empty={!charts.changed} emptyTitle="No config changes in 30 days" emptyIcon={GitCompare} height={240}>
            <Chart option={charts.perDay} height={240} ariaLabel="Config changes per day" />
          </ChartBody>
        </ChartCard>
        <ChartCard title="Lines added and removed" description="Per day · added above, removed below the line" delay={2} className="lg:col-span-2 xl:col-span-1">
          <ChartBody loading={stats.isLoading} error={stats.error} empty={!charts.changed} emptyTitle="No config changes in 30 days" emptyIcon={GitCompare} height={240}>
            <Chart option={charts.lines} height={240} ariaLabel="Lines added and removed per day" />
          </ChartBody>
        </ChartCard>
      </div>
      <Card>
        <FilterBar>
          <SimpleSelect
            aria-label="Device"
            value={filters.device}
            onValueChange={(v) => setFilters({ device: v, offset: "0" })}
            options={(devices.data ?? []).map((d) => ({ value: d.id, label: d.hostname }))}
            allowEmpty
            emptyLabel="All devices"
            placeholder="Device"
            className="w-52"
          />
          <SimpleSelect
            aria-label="Status"
            value={filters.status}
            onValueChange={(v) => setFilters({ status: v, offset: "0" })}
            options={BACKUP_STATUSES.map((s) => ({ value: s, label: humanize(s) }))}
            allowEmpty
            emptyLabel="Any status"
            placeholder="Status"
            className="w-40"
          />
          <Input value={author} onChange={(e) => setAuthor(e.target.value)} placeholder="Author (exact)" className="w-44" aria-label="Author" />
          <div className="flex h-9 items-center">
            <Checkbox
              label="Changed only"
              checked={filters.changed_only === "1"}
              onCheckedChange={(c) => setFilters({ changed_only: c ? "1" : "", offset: "0" })}
            />
          </div>
        </FilterBar>
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Collected</TableHead>
              <TableHead>Device</TableHead>
              <TableHead>Status</TableHead>
              <TableHead>Commit</TableHead>
              <TableHead>Change</TableHead>
              <TableHead>Risk</TableHead>
              <TableHead>Author</TableHead>
              <TableHead className="w-full">Reason</TableHead>
              <TableHead>Size</TableHead>
              <TableHead />
            </TableRow>
          </TableHeader>
          <TableBody>
            <TableState
              cols={10}
              isLoading={q.isLoading}
              error={q.error}
              onRetry={() => void q.refetch()}
              isEmpty={items.length === 0}
              empty={<EmptyState icon={DatabaseBackup} title="No backups found" description="Adjust the filters or run a backup." />}
            />
            {items.map((b) => (
              <TableRow key={b.id}>
                <TableCell className="whitespace-nowrap text-xs">
                  <RelativeTime value={b.collected_at} />
                </TableCell>
                <TableCell className="whitespace-nowrap">
                  <Link href={`/devices/${b.device_id}`} className="font-medium hover:underline">
                    {devices.map.get(b.device_id) ?? b.device_id.slice(0, 8)}
                  </Link>
                </TableCell>
                <TableCell>
                  <StatusBadge status={b.status} dot={false} />
                  {b.error ? (
                    <p className="mt-0.5 max-w-[240px] truncate text-[11px] text-danger" title={b.error}>
                      {b.error}
                    </p>
                  ) : null}
                </TableCell>
                <TableCell className="font-mono text-xs">{shortSha(b.commit_sha)}</TableCell>
                <TableCell className="whitespace-nowrap text-xs tabular">
                  {b.changed ? (
                    <>
                      <span className="font-mono text-success">+{b.lines_added}</span> <span className="font-mono text-danger">−{b.lines_removed}</span>
                    </>
                  ) : (
                    <span className="text-muted-foreground">no change</span>
                  )}
                </TableCell>
                <TableCell>{b.changed && b.risk_score !== null ? <RiskBadge score={b.risk_score} /> : <span className="text-muted-foreground">—</span>}</TableCell>
                <TableCell className="whitespace-nowrap">{b.author ?? "—"}</TableCell>
                <TableCell className="max-w-0">
                  <div className="flex items-center gap-1.5">
                    <Badge variant="muted">{b.trigger}</Badge>
                    <span className="truncate text-xs text-muted-foreground" title={b.reason ?? undefined}>
                      {b.reason ?? ""}
                    </span>
                  </div>
                </TableCell>
                <TableCell className="whitespace-nowrap text-xs text-muted-foreground">{formatBytes(b.size_bytes)}</TableCell>
                <TableCell className="whitespace-nowrap">
                  <div className="flex gap-1">
                    {b.changed && b.commit_sha ? (
                      <Button asChild variant="ghost" size="icon-sm" aria-label="View diff" title="View diff">
                        <Link href={`/devices/${b.device_id}?tab=diff&new=${b.commit_sha}`}>
                          <GitCompare />
                        </Link>
                      </Button>
                    ) : null}
                    {can("configs:delete") ? (
                      <Button variant="ghost" size="icon-sm" aria-label="Delete backup record" title="Delete record" onClick={() => confirm.ask(b)}>
                        <Trash2 />
                      </Button>
                    ) : null}
                  </div>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
        {q.data ? <Pagination total={q.data.total} limit={PAGE_SIZE} offset={offset} onChange={(o) => setFilters({ offset: String(o) })} /> : null}
      </Card>
      <RunBackupDialog open={runOpen} onOpenChange={setRunOpen} />
      <ConfirmDialog
        open={confirm.open}
        onOpenChange={confirm.onOpenChange}
        title="Delete backup record?"
        description="Only the database record is removed; the Git history is immutable and kept."
        confirmLabel="Delete"
        destructive
        loading={del.isPending}
        onConfirm={() => confirm.target && del.mutate(confirm.target)}
      />
    </>
  );
}
