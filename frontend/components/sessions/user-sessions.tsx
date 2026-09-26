"use client";

import { useQuery } from "@tanstack/react-query";
import { ChevronDown, ChevronRight, GitCompare, LogIn, ShieldAlert, SquareTerminal } from "lucide-react";
import Link from "next/link";
import * as React from "react";

import { EmptyState } from "@/components/common/empty-state";
import { RelativeTime } from "@/components/common/relative-time";
import { TableState } from "@/components/common/table-skeleton";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { api } from "@/lib/api";
import type { CommandLog, Page } from "@/lib/types";
import { cn, formatDateTime, formatDuration, shortSha } from "@/lib/utils";

export interface UserSession {
  id: string;
  username: string;
  device_address: string;
  device_id: string | null;
  device_name: string | null;
  source_address: string | null;
  port: string | null;
  start: string;
  end: string;
  login_at: string | null;
  commands: number;
  config_commands: number;
  denied: number;
  first_commands: string[];
  duration_s: number;
  change: { backup_id: string; commit: string | null; at: string; added: number; removed: number; author: string | null } | null;
}

export interface SessionSummary {
  sessions: number;
  users: number;
  commands: number;
  config_sessions: number;
  denied: number;
  logins: number;
  failed_logins: number;
}

const CONFIG_CMD = /^(set |delete |deactivate |activate |rename |insert |replace |load |rollback|commit|configure|conf t|config |no |interface |router |ip |ipv6 |vlan |switchport |shutdown|write( mem)?|copy run|\/)/i;

function isoPlus(iso: string, seconds: number): string {
  return new Date(new Date(iso).getTime() + seconds * 1000).toISOString();
}

/** The session's commands in order, like a terminal transcript. */
function Transcript({ s }: { s: UserSession }) {
  const q = useQuery({
    queryKey: ["session-commands", s.id],
    queryFn: () =>
      api.get<Page<CommandLog>>("/accounting/commands", {
        user: s.username,
        device: s.device_address,
        start: isoPlus(s.start, -1),
        end: isoPlus(s.end, 1),
        limit: 1000,
      }),
    enabled: s.commands > 0,
  });
  if (!s.commands)
    return (
      <p className="px-4 py-3 text-sm text-muted-foreground">
        Logged in {s.source_address ? `from ${s.source_address} ` : ""}at {formatDateTime(s.login_at ?? s.start)} - no commands were accounted (read-only look-around, or command
        accounting is off on the device).
      </p>
    );
  if (q.isLoading) return <Skeleton className="m-3 h-32" />;
  // accounting returns newest first; a session reads top-down; start+stop records are one line
  const seen = new Set<string>();
  const rows = [...(q.data?.items ?? [])].reverse().filter((c) => {
    const k = `${c.timestamp.slice(0, 19)}|${c.command}|${c.result}`;
    if (seen.has(k)) return false;
    seen.add(k);
    return true;
  });
  return (
    <div className="bg-[#0f1117] px-4 py-3 font-mono text-[12px] leading-[1.7] text-[#d7dbe4]" data-testid="session-transcript">
      <p className="mb-1 text-[#7d8597]">
        # {s.username}@{s.device_name ?? s.device_address}
        {s.port ? ` ${s.port}` : ""}
        {s.source_address ? ` from ${s.source_address}` : ""}
        {s.login_at ? ` · login ${formatDateTime(s.login_at)}` : ""}
      </p>
      {rows.map((c) => {
        const denied = c.result === "denied";
        const cfg = !denied && CONFIG_CMD.test(c.command.trim());
        return (
          <div key={c.id} className="flex gap-3">
            <span className="shrink-0 text-[#6b7385]">{new Date(c.timestamp).toLocaleTimeString()}</span>
            <span className={cn("min-w-0 break-all", denied && "text-[#ff8a80] line-through decoration-[#ff8a80]/60", cfg && "text-[#c4b5fd]", c.dangerous && !denied && "text-[#fbbf24]")}>
              <span className="select-none text-[#6b7385]">{cfg ? "# " : "> "}</span>
              {c.command}
            </span>
            {denied ? <span className="shrink-0 rounded bg-[#7f1d1d] px-1.5 text-[10.5px] text-[#fecaca]">denied</span> : null}
            {c.dangerous && !denied ? <span className="shrink-0 rounded bg-[#78350f] px-1.5 text-[10.5px] text-[#fde68a]">{c.dangerous}</span> : null}
          </div>
        );
      })}
      {(q.data?.total ?? 0) > 1000 ? <p className="mt-1 text-[#7d8597]"># … first 1,000 commands shown</p> : null}
      {s.change ? (
        <p className="mt-2 text-[#86efac]">
          # configuration change recorded {formatDateTime(s.change.at)}: +{s.change.added} −{s.change.removed}
          {s.device_id && s.change.commit ? (
            <Link href={`/devices/${s.device_id}?tab=diff&new=${s.change.commit}`} className="ml-2 underline">
              view diff
            </Link>
          ) : null}
        </p>
      ) : null}
    </div>
  );
}

/** Sessions with an expandable command transcript. */
export function SessionsTable({
  items,
  isLoading,
  error,
  onRetry,
  showDevice = true,
}: {
  items: UserSession[];
  isLoading?: boolean;
  error?: unknown;
  onRetry?: () => void;
  showDevice?: boolean;
}) {
  const [open, setOpen] = React.useState<Set<string>>(new Set());
  const toggle = (id: string) =>
    setOpen((o) => {
      const n = new Set(o);
      if (n.has(id)) n.delete(id);
      else n.add(id);
      return n;
    });
  const cols = showDevice ? 8 : 7;
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead className="w-8" />
          <TableHead>Started</TableHead>
          <TableHead>User</TableHead>
          {showDevice ? <TableHead>Device</TableHead> : null}
          <TableHead>From</TableHead>
          <TableHead>Duration</TableHead>
          <TableHead>Commands</TableHead>
          <TableHead>Result</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        <TableState
          cols={cols}
          isLoading={!!isLoading}
          error={error}
          onRetry={onRetry}
          isEmpty={!items.length}
          empty={<EmptyState icon={SquareTerminal} title="No sessions in this period" description="Sessions appear once TACACS+ accounting and login logs are shipped by the agent." />}
        />
        {items.map((s) => {
          const on = open.has(s.id);
          return (
            <React.Fragment key={s.id}>
              <TableRow className={cn("cursor-pointer", on && "bg-accent/30")} onClick={() => toggle(s.id)} aria-expanded={on}>
                <TableCell>{on ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}</TableCell>
                <TableCell className="whitespace-nowrap text-xs">
                  <span title={formatDateTime(s.start)}>
                    <RelativeTime value={s.start} />
                  </span>
                </TableCell>
                <TableCell className="font-medium">{s.username}</TableCell>
                {showDevice ? (
                  <TableCell>
                    {s.device_id ? (
                      <Link href={`/devices/${s.device_id}?tab=activity`} className="text-primary hover:underline" onClick={(e) => e.stopPropagation()}>
                        {s.device_name ?? s.device_address}
                      </Link>
                    ) : (
                      <span className="font-mono text-xs">{s.device_address}</span>
                    )}
                  </TableCell>
                ) : null}
                <TableCell className="font-mono text-xs">
                  {s.source_address ?? "—"}
                  {s.port ? <span className="ml-1 text-muted-foreground">{s.port}</span> : null}
                </TableCell>
                <TableCell className="text-xs">{s.duration_s >= 1 ? formatDuration(s.duration_s) : "—"}</TableCell>
                <TableCell>
                  <div className="flex flex-wrap items-center gap-1">
                    {s.commands ? <span className="text-sm tabular">{s.commands}</span> : <Badge variant="muted"><LogIn className="h-3 w-3" /> login only</Badge>}
                    {s.config_commands ? <Badge variant="info">{s.config_commands} config</Badge> : null}
                    {s.denied ? (
                      <Badge variant="danger">
                        <ShieldAlert className="h-3 w-3" /> {s.denied} denied
                      </Badge>
                    ) : null}
                  </div>
                  {s.first_commands.length ? <p className="mt-0.5 max-w-[320px] truncate font-mono text-[11px] text-muted-foreground">{s.first_commands.join(" ; ")}</p> : null}
                </TableCell>
                <TableCell>
                  {s.change ? (
                    s.device_id && s.change.commit ? (
                      <Link
                        href={`/devices/${s.device_id}?tab=diff&new=${s.change.commit}`}
                        className="inline-flex items-center gap-1 text-xs font-medium text-primary hover:underline"
                        onClick={(e) => e.stopPropagation()}
                        title={`Config change ${shortSha(s.change.commit)}`}
                      >
                        <GitCompare className="h-3.5 w-3.5" /> <span className="font-mono text-success">+{s.change.added}</span> <span className="font-mono text-danger">−{s.change.removed}</span>
                      </Link>
                    ) : (
                      <span className="text-xs">changed</span>
                    )
                  ) : s.config_commands ? (
                    <span className="text-xs text-muted-foreground">no change stored</span>
                  ) : (
                    <span className="text-xs text-muted-foreground">—</span>
                  )}
                </TableCell>
              </TableRow>
              {on ? (
                <TableRow className="hover:bg-transparent">
                  <TableCell colSpan={cols} className="p-0">
                    <Transcript s={s} />
                  </TableCell>
                </TableRow>
              ) : null}
            </React.Fragment>
          );
        })}
      </TableBody>
    </Table>
  );
}
