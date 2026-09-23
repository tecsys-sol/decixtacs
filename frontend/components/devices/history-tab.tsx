"use client";

import { GitCommitHorizontal, GitCompare } from "lucide-react";

import { EmptyState } from "@/components/common/empty-state";
import { RelativeTime } from "@/components/common/relative-time";
import { TableState } from "@/components/common/table-skeleton";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import type { Device } from "@/lib/types";
import { shortSha } from "@/lib/utils";

import { useDeviceHistory } from "./use-device-history";

export function HistoryTab({
  device,
  onDiff,
  onView,
}: {
  device: Device;
  onDiff: (oldRev: string, newRev: string) => void;
  onView: (rev: string) => void;
}) {
  const history = useDeviceHistory(device.id);
  const commits = history.data ?? [];
  return (
    <Card>
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Commit</TableHead>
            <TableHead className="w-full">Message</TableHead>
            <TableHead>Author</TableHead>
            <TableHead>When</TableHead>
            <TableHead />
          </TableRow>
        </TableHeader>
        <TableBody>
          <TableState
            cols={5}
            isLoading={history.isLoading}
            error={history.error}
            onRetry={() => void history.refetch()}
            isEmpty={commits.length === 0}
            empty={<EmptyState icon={GitCommitHorizontal} title="No history" description="Configuration history appears after the first successful backup." />}
          />
          {commits.map((c, i) => {
            const prev = commits[i + 1];
            return (
              <TableRow key={c.sha}>
                <TableCell className="font-mono text-xs">
                  <span title={c.sha}>{shortSha(c.sha, 10)}</span>
                </TableCell>
                <TableCell className="max-w-0">
                  <p className="truncate" title={c.message}>
                    {c.message.split("\n")[0]}
                  </p>
                </TableCell>
                <TableCell className="whitespace-nowrap" title={c.email}>
                  {c.author}
                </TableCell>
                <TableCell className="whitespace-nowrap text-xs">
                  <RelativeTime value={c.timestamp} />
                </TableCell>
                <TableCell className="whitespace-nowrap">
                  <div className="flex gap-1">
                    <Button variant="ghost" size="xs" onClick={() => onView(c.sha)}>
                      View
                    </Button>
                    {prev ? (
                      <Button variant="outline" size="xs" onClick={() => onDiff(prev.sha, c.sha)}>
                        <GitCompare /> Diff
                      </Button>
                    ) : null}
                  </div>
                </TableCell>
              </TableRow>
            );
          })}
        </TableBody>
      </Table>
    </Card>
  );
}
