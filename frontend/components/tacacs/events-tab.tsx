"use client";

import { useQuery } from "@tanstack/react-query";
import { Fingerprint } from "lucide-react";
import * as React from "react";

import { EmptyState } from "@/components/common/empty-state";
import { FilterBar } from "@/components/common/filter-bar";
import { Pagination } from "@/components/common/pagination";
import { RelativeTime } from "@/components/common/relative-time";
import { StatusBadge } from "@/components/common/status-badge";
import { TableState } from "@/components/common/table-skeleton";
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { SimpleSelect } from "@/components/ui/select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { useDebounce } from "@/hooks/use-debounce";
import { useOnChange } from "@/hooks/use-reset";
import { api } from "@/lib/api";
import { PAGE_SIZE } from "@/lib/constants";
import type { AuthEvent, Page } from "@/lib/types";

export function EventsTab() {
  const [username, setUsername] = React.useState("");
  const [result, setResult] = React.useState("");
  const [offset, setOffset] = React.useState(0);
  const u = useDebounce(username.trim(), 350);
  useOnChange(u, () => setOffset(0));

  const q = useQuery({
    queryKey: ["tacacs", "events", u, result, offset],
    queryFn: () => api.get<Page<AuthEvent>>("/tacacs/events", { username: u, result, limit: PAGE_SIZE, offset }),
    placeholderData: (p) => p,
    refetchInterval: 30_000,
  });
  const items = q.data?.items ?? [];
  return (
    <Card>
      <FilterBar>
        <Input value={username} onChange={(e) => setUsername(e.target.value)} placeholder="Username (exact)" className="w-52" aria-label="Username" />
        <SimpleSelect
          aria-label="Result"
          value={result}
          onValueChange={(v) => { setResult(v); setOffset(0); }}
          allowEmpty
          emptyLabel="Any result"
          className="w-40"
          options={["pass", "fail", "permit", "deny", "error"].map((r) => ({ value: r, label: r }))}
        />
      </FilterBar>
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Time</TableHead>
            <TableHead>User</TableHead>
            <TableHead>Kind</TableHead>
            <TableHead>Device</TableHead>
            <TableHead>Source</TableHead>
            <TableHead>Result</TableHead>
            <TableHead className="w-full">Detail</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          <TableState cols={7} isLoading={q.isLoading} error={q.error} onRetry={() => void q.refetch()} isEmpty={items.length === 0} empty={<EmptyState icon={Fingerprint} title="No authentication events" />} />
          {items.map((e) => (
            <TableRow key={e.id}>
              <TableCell className="whitespace-nowrap text-xs">
                <RelativeTime value={e.timestamp} />
              </TableCell>
              <TableCell className="font-medium">{e.username}</TableCell>
              <TableCell>
                <Badge variant="outline">{e.kind}</Badge>
              </TableCell>
              <TableCell className="font-mono text-xs">{e.device_address}</TableCell>
              <TableCell className="font-mono text-xs">{e.source_address ?? "—"}</TableCell>
              <TableCell>
                <StatusBadge status={e.result} dot={false} />
              </TableCell>
              <TableCell className="max-w-0">
                <code className="block truncate font-mono text-xs text-muted-foreground" title={e.detail ?? undefined}>
                  {e.detail ?? ""}
                </code>
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
      {q.data ? <Pagination total={q.data.total} limit={PAGE_SIZE} offset={offset} onChange={setOffset} /> : null}
    </Card>
  );
}
