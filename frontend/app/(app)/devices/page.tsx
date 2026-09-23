"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { DatabaseBackup, Plus, Search, Server } from "lucide-react";
import * as React from "react";

import { EmptyState } from "@/components/common/empty-state";
import { FilterBar } from "@/components/common/filter-bar";
import { PageHeader } from "@/components/common/page-header";
import { Pagination } from "@/components/common/pagination";
import { RelativeTime } from "@/components/common/relative-time";
import { StatusBadge } from "@/components/common/status-badge";
import { TableState } from "@/components/common/table-skeleton";
import { DeviceFormDialog } from "@/components/devices/device-form-dialog";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { SimpleSelect } from "@/components/ui/select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { useAuth } from "@/hooks/use-auth";
import { useDebounce } from "@/hooks/use-debounce";
import { usePlatforms, useSites } from "@/hooks/use-lookups";
import { toast } from "@/hooks/use-toast";
import { useUrlState } from "@/hooks/use-url-state";
import { api } from "@/lib/api";
import { BACKUP_STATUSES, DEVICE_STATUSES, PAGE_SIZE } from "@/lib/constants";
import type { BackupRunResult, Device, Page } from "@/lib/types";
import { humanize } from "@/lib/utils";

export default function DevicesPage() {
  const { can } = useAuth();
  const qc = useQueryClient();
  const [filters, setFilters] = useUrlState({ q: "", site: "", platform: "", status: "", backup_status: "", offset: "0" });
  const [q, setQ] = React.useState(filters.q);
  const debouncedQ = useDebounce(q, 300);
  const [createOpen, setCreateOpen] = React.useState(false);
  const sites = useSites();
  const platforms = usePlatforms();

  React.useEffect(() => {
    if (debouncedQ !== filters.q) setFilters({ q: debouncedQ, offset: "0" });
  }, [debouncedQ, filters.q, setFilters]);

  const offset = Number(filters.offset) || 0;
  const query = useQuery({
    queryKey: ["devices", "list", filters],
    queryFn: () =>
      api.get<Page<Device>>("/devices", {
        q: filters.q,
        site_id: filters.site,
        platform: filters.platform,
        status: filters.status,
        backup_status: filters.backup_status,
        limit: PAGE_SIZE,
        offset,
      }),
    placeholderData: (prev) => prev,
  });

  const backup = useMutation({
    mutationFn: (ids: string[]) => api.post<BackupRunResult>("/backups/run", { device_ids: ids, reason: "manual (UI)", run_async: true }),
    onSuccess: () => {
      toast.success("Backup queued", "Results appear in Backups shortly.");
      void qc.invalidateQueries({ queryKey: ["backups"] });
    },
  });

  const setFilter = (k: keyof typeof filters) => (v: string) => setFilters({ [k]: v, offset: "0" });
  const items = query.data?.items ?? [];

  return (
    <>
      <PageHeader
        title="Devices"
        description="Network inventory with backup and reachability status."
        actions={
          can("devices:write") ? (
            <Button onClick={() => setCreateOpen(true)}>
              <Plus /> Add device
            </Button>
          ) : null
        }
      />
      <Card>
        <FilterBar>
          <div className="relative min-w-[220px] flex-1">
            <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
            <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Hostname, IP or serial" className="pl-8" aria-label="Search devices" />
          </div>
          <SimpleSelect
            aria-label="Site"
            value={filters.site}
            onValueChange={setFilter("site")}
            options={(sites.data ?? []).map((s) => ({ value: s.id, label: s.name }))}
            allowEmpty
            emptyLabel="All sites"
            placeholder="Site"
            className="w-44"
          />
          <SimpleSelect
            aria-label="Platform"
            value={filters.platform}
            onValueChange={setFilter("platform")}
            options={(platforms.data ?? []).map((p) => ({ value: p.slug, label: p.name }))}
            allowEmpty
            emptyLabel="All platforms"
            placeholder="Platform"
            className="w-44"
          />
          <SimpleSelect
            aria-label="Status"
            value={filters.status}
            onValueChange={setFilter("status")}
            options={DEVICE_STATUSES.map((s) => ({ value: s, label: humanize(s) }))}
            allowEmpty
            emptyLabel="Any status"
            placeholder="Status"
            className="w-40"
          />
          <SimpleSelect
            aria-label="Backup status"
            value={filters.backup_status}
            onValueChange={setFilter("backup_status")}
            options={BACKUP_STATUSES.map((s) => ({ value: s, label: humanize(s) }))}
            allowEmpty
            emptyLabel="Any backup"
            placeholder="Backup"
            className="w-40"
          />
        </FilterBar>
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Hostname</TableHead>
              <TableHead>Management IP</TableHead>
              <TableHead>Site</TableHead>
              <TableHead>Platform</TableHead>
              <TableHead>Role</TableHead>
              <TableHead>Status</TableHead>
              <TableHead>Reachability</TableHead>
              <TableHead>Last backup</TableHead>
              <TableHead className="w-0" />
            </TableRow>
          </TableHeader>
          <TableBody>
            <TableState
              cols={9}
              isLoading={query.isLoading}
              error={query.error}
              onRetry={() => void query.refetch()}
              isEmpty={items.length === 0}
              empty={
                <EmptyState
                  icon={Server}
                  title="No devices match"
                  description="Adjust the filters or add a device, or sync inventory from NetBox under Integrations."
                />
              }
            />
            {items.map((d) => (
              <TableRow key={d.id}>
                <TableCell>
                  <Link href={`/devices/${d.id}`} className="font-medium text-primary hover:underline">
                    {d.hostname}
                  </Link>
                  {d.tags.length ? (
                    <div className="mt-0.5 flex flex-wrap gap-1">
                      {d.tags.slice(0, 3).map((t) => (
                        <Badge key={t} variant="outline" className="px-1 py-0 text-[10px]">
                          {t}
                        </Badge>
                      ))}
                    </div>
                  ) : null}
                </TableCell>
                <TableCell className="font-mono text-xs">{d.management_ip}</TableCell>
                <TableCell>{d.site?.name ?? "—"}</TableCell>
                <TableCell>{d.platform?.name ?? "—"}</TableCell>
                <TableCell>{d.role ? humanize(d.role) : "—"}</TableCell>
                <TableCell>
                  <StatusBadge status={d.status} dot={false} />
                </TableCell>
                <TableCell>
                  <StatusBadge status={d.reachability} />
                </TableCell>
                <TableCell>
                  <div className="flex items-center gap-2">
                    {d.last_backup_status ? <StatusBadge status={d.last_backup_status} dot={false} /> : null}
                    <RelativeTime value={d.last_backup_at} className="text-xs text-muted-foreground" />
                  </div>
                </TableCell>
                <TableCell>
                  {can("configs:backup") ? (
                    <Button
                      variant="ghost"
                      size="icon-sm"
                      aria-label={`Back up ${d.hostname} now`}
                      title="Back up now"
                      onClick={() => backup.mutate([d.id])}
                    >
                      <DatabaseBackup />
                    </Button>
                  ) : null}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
        {query.data ? (
          <Pagination total={query.data.total} limit={PAGE_SIZE} offset={offset} onChange={(o) => setFilters({ offset: String(o) })} />
        ) : null}
      </Card>
      <DeviceFormDialog open={createOpen} onOpenChange={setCreateOpen} />
    </>
  );
}
