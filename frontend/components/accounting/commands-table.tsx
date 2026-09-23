"use client";

import Link from "next/link";
import { ShieldAlert, Terminal } from "lucide-react";

import { EmptyState } from "@/components/common/empty-state";
import { RelativeTime } from "@/components/common/relative-time";
import { StatusBadge } from "@/components/common/status-badge";
import { TableState } from "@/components/common/table-skeleton";
import { Badge } from "@/components/ui/badge";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import type { CommandLog } from "@/lib/types";
import { cn } from "@/lib/utils";

export function CommandsTable({
  items,
  isLoading,
  error,
  onRetry,
  hideDevice,
}: {
  items: CommandLog[];
  isLoading: boolean;
  error: unknown;
  onRetry?: () => void;
  hideDevice?: boolean;
}) {
  const cols = hideDevice ? 5 : 6;
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>Time</TableHead>
          <TableHead>User</TableHead>
          {hideDevice ? null : <TableHead>Device</TableHead>}
          <TableHead className="w-full">Command</TableHead>
          <TableHead>Priv</TableHead>
          <TableHead>Result</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        <TableState
          cols={cols}
          isLoading={isLoading}
          error={error}
          onRetry={onRetry}
          isEmpty={items.length === 0}
          empty={<EmptyState icon={Terminal} title="No commands found" description="TACACS+ accounting records matching the filters appear here." />}
        />
        {items.map((c) => (
          <TableRow key={c.id} className={cn(c.dangerous && "bg-destructive/5")}>
            <TableCell className="whitespace-nowrap text-xs">
              <RelativeTime value={c.timestamp} />
            </TableCell>
            <TableCell className="whitespace-nowrap font-medium">{c.username}</TableCell>
            {hideDevice ? null : (
              <TableCell className="whitespace-nowrap">
                {c.device_id ? (
                  <Link href={`/devices/${c.device_id}?tab=commands`} className="hover:underline">
                    {c.device_name ?? c.device_address}
                  </Link>
                ) : (
                  <span className="font-mono text-xs">{c.device_name ?? c.device_address}</span>
                )}
              </TableCell>
            )}
            <TableCell>
              <div className="flex flex-wrap items-center gap-2">
                <code className="break-all font-mono text-xs">{c.command}</code>
                {c.dangerous ? (
                  <Badge variant="danger" title={c.dangerous}>
                    <ShieldAlert /> Dangerous · {c.dangerous}
                  </Badge>
                ) : null}
              </div>
              {c.source_address ? <p className="mt-0.5 text-[11px] text-muted-foreground">from {c.source_address}</p> : null}
            </TableCell>
            <TableCell className="tabular">{c.priv_lvl ?? "—"}</TableCell>
            <TableCell>
              <StatusBadge status={c.result} dot={false} />
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}
