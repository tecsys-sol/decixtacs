"use client";

import { useQuery } from "@tanstack/react-query";
import { LogIn } from "lucide-react";
import * as React from "react";

import { EmptyState } from "@/components/common/empty-state";
import { FilterBar } from "@/components/common/filter-bar";
import { Pagination } from "@/components/common/pagination";
import { RelativeTime } from "@/components/common/relative-time";
import { TableState } from "@/components/common/table-skeleton";
import { TextFilter } from "@/components/common/text-filter";
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import { SimpleSelect } from "@/components/ui/select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { api } from "@/lib/api";
import { PAGE_SIZE } from "@/lib/constants";
import type { LoginRecord, Page } from "@/lib/types";

export function LoginsTab() {
  const [username, setUsername] = React.useState("");
  const [success, setSuccess] = React.useState("");
  const [offset, setOffset] = React.useState(0);
  const q = useQuery({
    queryKey: ["login-history", username, success, offset],
    queryFn: () => api.get<Page<LoginRecord>>("/login-history", { username, success: success === "" ? undefined : success === "true", limit: PAGE_SIZE, offset }),
    placeholderData: (p) => p,
  });
  const items = q.data?.items ?? [];
  return (
    <Card>
      <FilterBar>
        <TextFilter value={username} onCommit={(v) => { setUsername(v); setOffset(0); }} placeholder="Username" className="w-48" aria-label="Username" />
        <SimpleSelect aria-label="Result" value={success} onValueChange={(v) => { setSuccess(v); setOffset(0); }} allowEmpty emptyLabel="All attempts" className="w-40" options={[{ value: "true", label: "Successful" }, { value: "false", label: "Failed" }]} />
      </FilterBar>
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Time</TableHead>
            <TableHead>User</TableHead>
            <TableHead>Result</TableHead>
            <TableHead>Method</TableHead>
            <TableHead>Source IP</TableHead>
            <TableHead className="w-full">Reason</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          <TableState cols={6} isLoading={q.isLoading} error={q.error} onRetry={() => void q.refetch()} isEmpty={items.length === 0} empty={<EmptyState icon={LogIn} title="No login attempts" />} />
          {items.map((l) => (
            <TableRow key={l.id}>
              <TableCell className="whitespace-nowrap text-xs">
                <RelativeTime value={l.timestamp} />
              </TableCell>
              <TableCell className="font-medium">{l.username}</TableCell>
              <TableCell>{l.success ? <Badge variant="success" dot>Success</Badge> : <Badge variant="danger" dot>Failed</Badge>}</TableCell>
              <TableCell>
                <Badge variant="outline">{l.method}</Badge>
              </TableCell>
              <TableCell className="font-mono text-xs">{l.source_ip ?? "—"}</TableCell>
              <TableCell className="text-xs text-muted-foreground">{l.reason ?? ""}</TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
      {q.data ? <Pagination total={q.data.total} limit={PAGE_SIZE} offset={offset} onChange={setOffset} /> : null}
    </Card>
  );
}
