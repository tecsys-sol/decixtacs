"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { Plus, Workflow } from "lucide-react";
import * as React from "react";

import { ChangeFormDialog } from "@/components/changes/change-form-dialog";
import { EmptyState } from "@/components/common/empty-state";
import { FilterBar } from "@/components/common/filter-bar";
import { PageHeader } from "@/components/common/page-header";
import { Pagination } from "@/components/common/pagination";
import { RelativeTime } from "@/components/common/relative-time";
import { StatusBadge } from "@/components/common/status-badge";
import { TableState } from "@/components/common/table-skeleton";
import { TextFilter } from "@/components/common/text-filter";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { SimpleSelect } from "@/components/ui/select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { useAuth } from "@/hooks/use-auth";
import { useUrlState } from "@/hooks/use-url-state";
import { api } from "@/lib/api";
import { CHANGE_STATES, PAGE_SIZE } from "@/lib/constants";
import type { Change, Page } from "@/lib/types";
import { formatDateTime, humanize } from "@/lib/utils";

export default function ChangesPage() {
  const { can } = useAuth();
  const [f, setF] = useUrlState({ state: "", q: "", offset: "0" });
  const [createOpen, setCreateOpen] = React.useState(false);
  const offset = Number(f.offset) || 0;
  const q = useQuery({
    queryKey: ["changes", "list", f],
    queryFn: () => api.get<Page<Change>>("/changes", { state: f.state, q: f.q, limit: PAGE_SIZE, offset }),
    placeholderData: (p) => p,
  });
  const items = q.data?.items ?? [];

  return (
    <>
      <PageHeader
        title="Change requests"
        description="Four-eyes change workflow linked to configuration snapshots."
        actions={
          can("changes:write") ? (
            <Button onClick={() => setCreateOpen(true)}>
              <Plus /> New change
            </Button>
          ) : null
        }
      />
      <Card>
        <FilterBar>
          <TextFilter value={f.q} onCommit={(v) => setF({ q: v, offset: "0" })} placeholder="Search title" className="w-64" aria-label="Search title" />
          <SimpleSelect
            aria-label="State"
            value={f.state}
            onValueChange={(v) => setF({ state: v, offset: "0" })}
            allowEmpty
            emptyLabel="Any state"
            className="w-48"
            options={CHANGE_STATES.map((s) => ({ value: s, label: humanize(s) }))}
          />
        </FilterBar>
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Number</TableHead>
              <TableHead className="w-full">Title</TableHead>
              <TableHead>State</TableHead>
              <TableHead>Risk</TableHead>
              <TableHead>Devices</TableHead>
              <TableHead>Scheduled</TableHead>
              <TableHead>Created</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            <TableState cols={7} isLoading={q.isLoading} error={q.error} onRetry={() => void q.refetch()} isEmpty={items.length === 0} empty={<EmptyState icon={Workflow} title="No change requests" />} />
            {items.map((c) => (
              <TableRow key={c.id}>
                <TableCell className="whitespace-nowrap font-mono text-xs">
                  <Link href={`/changes/${c.id}`} className="text-primary hover:underline">
                    CHG-{c.number}
                  </Link>
                </TableCell>
                <TableCell className="max-w-0">
                  <Link href={`/changes/${c.id}`} className="block truncate font-medium hover:underline">
                    {c.title}
                  </Link>
                  {c.external_ticket ? <span className="text-xs text-muted-foreground">{c.external_ticket}</span> : null}
                </TableCell>
                <TableCell>
                  <StatusBadge status={c.state} />
                </TableCell>
                <TableCell>
                  <StatusBadge status={c.risk} dot={false} />
                </TableCell>
                <TableCell className="tabular">{c.device_ids.length}</TableCell>
                <TableCell className="whitespace-nowrap text-xs">{c.scheduled_start ? formatDateTime(c.scheduled_start) : "—"}</TableCell>
                <TableCell className="whitespace-nowrap text-xs">
                  <RelativeTime value={c.created_at} />
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
        {q.data ? <Pagination total={q.data.total} limit={PAGE_SIZE} offset={offset} onChange={(o) => setF({ offset: String(o) })} /> : null}
      </Card>
      <ChangeFormDialog open={createOpen} onOpenChange={setCreateOpen} />
    </>
  );
}
