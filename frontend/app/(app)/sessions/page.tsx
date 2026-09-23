"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { PlayCircle, SquareTerminal } from "lucide-react";

import { EmptyState } from "@/components/common/empty-state";
import { FilterBar } from "@/components/common/filter-bar";
import { PageHeader } from "@/components/common/page-header";
import { Pagination } from "@/components/common/pagination";
import { TableState } from "@/components/common/table-skeleton";
import { TextFilter } from "@/components/common/text-filter";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { SimpleSelect } from "@/components/ui/select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { useDeviceNames } from "@/hooks/use-lookups";
import { useUrlState } from "@/hooks/use-url-state";
import { api } from "@/lib/api";
import { PAGE_SIZE } from "@/lib/constants";
import type { Page, Recording } from "@/lib/types";
import { formatBytes, formatDateTime, formatDuration } from "@/lib/utils";

export default function SessionsPage() {
  const devices = useDeviceNames();
  const [f, setF] = useUrlState({ user: "", device_id: "", command: "", offset: "0" });
  const offset = Number(f.offset) || 0;
  const q = useQuery({
    queryKey: ["sessions", f],
    queryFn: () => api.get<Page<Recording>>("/sessions", { user: f.user, device_id: f.device_id, command: f.command, limit: PAGE_SIZE, offset }),
    placeholderData: (p) => p,
  });
  const items = q.data?.items ?? [];

  return (
    <>
      <PageHeader title="Session recordings" description="Terminal sessions captured by the SSH bastion, with command index and replay." />
      <Card>
        <FilterBar>
          <TextFilter value={f.user} onCommit={(v) => setF({ user: v, offset: "0" })} placeholder="User (exact)" className="w-44" aria-label="User" />
          <SimpleSelect
            aria-label="Device"
            value={f.device_id}
            onValueChange={(v) => setF({ device_id: v, offset: "0" })}
            allowEmpty
            emptyLabel="All devices"
            className="w-52"
            options={(devices.data ?? []).map((d) => ({ value: d.id, label: d.hostname }))}
          />
          <TextFilter value={f.command} onCommit={(v) => setF({ command: v, offset: "0" })} placeholder="Typed command contains…" className="w-64 font-mono text-xs" aria-label="Command" />
        </FilterBar>
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Started</TableHead>
              <TableHead>User</TableHead>
              <TableHead>Device</TableHead>
              <TableHead>Source</TableHead>
              <TableHead>Duration</TableHead>
              <TableHead>Commands</TableHead>
              <TableHead>Size</TableHead>
              <TableHead />
            </TableRow>
          </TableHeader>
          <TableBody>
            <TableState cols={8} isLoading={q.isLoading} error={q.error} onRetry={() => void q.refetch()} isEmpty={items.length === 0} empty={<EmptyState icon={SquareTerminal} title="No recordings" description="Recordings are uploaded by the SSH bastion after each session." />} />
            {items.map((r) => (
              <TableRow key={r.id}>
                <TableCell className="whitespace-nowrap text-xs">{formatDateTime(r.started_at)}</TableCell>
                <TableCell className="font-medium">{r.username}</TableCell>
                <TableCell>
                  {r.device_id ? (
                    <Link href={`/devices/${r.device_id}`} className="hover:underline">
                      {devices.map.get(r.device_id) ?? r.device_address}
                    </Link>
                  ) : (
                    <span className="font-mono text-xs">{r.device_address}</span>
                  )}
                </TableCell>
                <TableCell className="font-mono text-xs">{r.source_address ?? "—"}</TableCell>
                <TableCell className="tabular">{formatDuration(r.duration_s)}</TableCell>
                <TableCell className="max-w-[280px]">
                  <span className="tabular">{r.commands.length}</span>
                  {r.commands.length ? (
                    <span className="ml-2 truncate font-mono text-[11px] text-muted-foreground">
                      {r.commands.slice(0, 3).map((c) => c.cmd).join(" · ")}
                    </span>
                  ) : null}
                </TableCell>
                <TableCell className="text-xs text-muted-foreground">{formatBytes(r.size_bytes)}</TableCell>
                <TableCell>
                  <Button asChild size="xs" variant="outline">
                    <Link href={`/sessions/${r.id}`}>
                      <PlayCircle /> Replay
                    </Link>
                  </Button>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
        {q.data ? <Pagination total={q.data.total} limit={PAGE_SIZE} offset={offset} onChange={(o) => setF({ offset: String(o) })} /> : null}
      </Card>
    </>
  );
}
