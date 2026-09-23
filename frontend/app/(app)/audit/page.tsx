"use client";

import { useMutation, useQuery } from "@tanstack/react-query";
import { ChevronDown, ChevronRight, History, ShieldAlert, ShieldCheck } from "lucide-react";
import * as React from "react";

import { EmptyState } from "@/components/common/empty-state";
import { FilterBar } from "@/components/common/filter-bar";
import { JsonView } from "@/components/common/json-view";
import { PageHeader } from "@/components/common/page-header";
import { Pagination } from "@/components/common/pagination";
import { RelativeTime } from "@/components/common/relative-time";
import { StatusBadge } from "@/components/common/status-badge";
import { TableState } from "@/components/common/table-skeleton";
import { TextFilter } from "@/components/common/text-filter";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { toast } from "@/hooks/use-toast";
import { useUrlState } from "@/hooks/use-url-state";
import { api, errorMessage } from "@/lib/api";
import { PAGE_SIZE } from "@/lib/constants";
import type { AuditEvent, AuditVerify, Page } from "@/lib/types";
import { cn, formatDateTime, formatNumber, localInputToIso } from "@/lib/utils";

const DEFAULTS = { actor: "", action: "", target_type: "", start: "", end: "", offset: "0" };

export default function AuditPage() {
  const [f, setF] = useUrlState(DEFAULTS);
  const offset = Number(f.offset) || 0;
  const [expanded, setExpanded] = React.useState<string | null>(null);
  const [verify, setVerify] = React.useState<AuditVerify | null>(null);
  const set = (k: keyof typeof DEFAULTS) => (v: string) => setF({ [k]: v, offset: "0" });

  const q = useQuery({
    queryKey: ["audit", f],
    queryFn: () =>
      api.get<Page<AuditEvent>>("/audit", {
        actor: f.actor,
        action: f.action,
        target_type: f.target_type,
        start: localInputToIso(f.start),
        end: localInputToIso(f.end),
        limit: PAGE_SIZE,
        offset,
      }),
    placeholderData: (p) => p,
  });

  const verifyChain = useMutation({
    mutationFn: () => api.get<AuditVerify>("/audit/verify"),
    onSuccess: (r) => {
      setVerify(r);
      if (r.intact) toast.success("Audit chain intact", `${formatNumber(r.events_verified)} events verified`);
      else toast.error("Audit chain broken", "Tampering or data loss detected - investigate immediately.");
    },
    onError: (e) => toast.error("Verification failed", errorMessage(e)),
  });

  const items = q.data?.items ?? [];

  return (
    <>
      <PageHeader
        title="Audit log"
        description="Hash-chained record of every change made through the portal and API."
        actions={
          <Button variant="outline" onClick={() => verifyChain.mutate()} loading={verifyChain.isPending}>
            <ShieldCheck /> Verify chain
          </Button>
        }
      />
      {verify ? (
        <div
          role="status"
          className={cn(
            "mb-4 flex items-center gap-3 rounded-lg border p-3 text-sm",
            verify.intact ? "border-success/40 bg-success/10" : "border-destructive/40 bg-destructive/10",
          )}
        >
          {verify.intact ? <ShieldCheck className="h-5 w-5 text-success" /> : <ShieldAlert className="h-5 w-5 text-destructive" />}
          <div>
            <p className="font-medium">{verify.intact ? "Chain intact" : "Chain verification FAILED"}</p>
            <p className="text-xs text-muted-foreground">{formatNumber(verify.events_verified)} events verified</p>
          </div>
        </div>
      ) : null}
      <Card>
        <FilterBar>
          <TextFilter value={f.actor} onCommit={set("actor")} placeholder="Actor (exact)" className="w-40" aria-label="Actor" />
          <TextFilter value={f.action} onCommit={set("action")} placeholder="Action, e.g. config.* " className="w-52 font-mono text-xs" aria-label="Action" />
          <TextFilter value={f.target_type} onCommit={set("target_type")} placeholder="Target type" className="w-40" aria-label="Target type" />
          <Input type="datetime-local" value={f.start} onChange={(e) => set("start")(e.target.value)} className="w-52" aria-label="From" />
          <Input type="datetime-local" value={f.end} onChange={(e) => set("end")(e.target.value)} className="w-52" aria-label="To" />
        </FilterBar>
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead className="w-6" />
              <TableHead>Time</TableHead>
              <TableHead>Actor</TableHead>
              <TableHead>Action</TableHead>
              <TableHead className="w-full">Target</TableHead>
              <TableHead>Source IP</TableHead>
              <TableHead>Outcome</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            <TableState cols={7} isLoading={q.isLoading} error={q.error} onRetry={() => void q.refetch()} isEmpty={items.length === 0} empty={<EmptyState icon={History} title="No audit events match" />} />
            {items.map((e) => {
              const open = expanded === e.id;
              const hasDetail = !!(e.before || e.after);
              return (
                <React.Fragment key={e.id}>
                  <TableRow className={cn(hasDetail && "cursor-pointer")} onClick={() => hasDetail && setExpanded(open ? null : e.id)} aria-expanded={hasDetail ? open : undefined}>
                    <TableCell className="pr-0">
                      {hasDetail ? open ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" /> : null}
                    </TableCell>
                    <TableCell className="whitespace-nowrap text-xs" title={formatDateTime(e.timestamp)}>
                      <RelativeTime value={e.timestamp} />
                    </TableCell>
                    <TableCell className="whitespace-nowrap font-medium">{e.actor_name}</TableCell>
                    <TableCell>
                      <code className="whitespace-nowrap rounded bg-muted px-1.5 py-0.5 font-mono text-[11px]">{e.action}</code>
                    </TableCell>
                    <TableCell className="max-w-0">
                      <p className="truncate">
                        {e.target_type ? <span className="text-muted-foreground">{e.target_type}: </span> : null}
                        {e.target_name ?? e.target_id ?? "—"}
                      </p>
                    </TableCell>
                    <TableCell className="font-mono text-xs">{e.source_ip ?? "—"}</TableCell>
                    <TableCell>
                      <StatusBadge status={e.outcome} dot={false} />
                    </TableCell>
                  </TableRow>
                  {open ? (
                    <TableRow className="hover:bg-transparent">
                      <TableCell colSpan={7} className="bg-muted/20">
                        <div className="grid gap-3 md:grid-cols-2">
                          <div>
                            <p className="mb-1 text-xs font-medium text-muted-foreground">Before</p>
                            <JsonView value={e.before} />
                          </div>
                          <div>
                            <p className="mb-1 text-xs font-medium text-muted-foreground">After</p>
                            <JsonView value={e.after} />
                          </div>
                        </div>
                      </TableCell>
                    </TableRow>
                  ) : null}
                </React.Fragment>
              );
            })}
          </TableBody>
        </Table>
        {q.data ? <Pagination total={q.data.total} limit={PAGE_SIZE} offset={offset} onChange={(o) => setF({ offset: String(o) })} /> : null}
      </Card>
    </>
  );
}
