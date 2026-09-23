"use client";

import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, RefreshCw } from "lucide-react";
import * as React from "react";

import { CodeViewer } from "@/components/common/code-viewer";
import { ErrorState } from "@/components/common/error-state";
import { Button } from "@/components/ui/button";
import { SimpleSelect } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { api } from "@/lib/api";
import type { RenderOut, TacacsServer } from "@/lib/types";

export function PreviewTab() {
  const [serverId, setServerId] = React.useState("");
  const servers = useQuery({ queryKey: ["tacacs", "servers"], queryFn: () => api.get<TacacsServer[]>("/tacacs/servers") });
  const q = useQuery({
    queryKey: ["tacacs", "render", serverId],
    queryFn: () => api.get<RenderOut>("/tacacs/render", { server_id: serverId || null }),
  });

  return (
    <div className="grid gap-3">
      <div className="flex flex-wrap items-center gap-2">
        <SimpleSelect
          aria-label="Server"
          value={serverId}
          onValueChange={setServerId}
          allowEmpty
          emptyLabel="Generic (no server)"
          options={(servers.data ?? []).map((s) => ({ value: s.id, label: s.name }))}
          className="w-64"
        />
        <Button variant="outline" size="sm" onClick={() => void q.refetch()} loading={q.isFetching}>
          <RefreshCw /> Re-render
        </Button>
        {q.data ? (
          <span className="font-mono text-[11px] text-muted-foreground" title="sha256 of the rendered configuration">
            sha256 {q.data.sha256.slice(0, 16)}…
          </span>
        ) : null}
      </div>
      {q.isLoading ? (
        <Skeleton className="h-[60vh]" />
      ) : q.error ? (
        <ErrorState error={q.error} onRetry={() => void q.refetch()} />
      ) : q.data ? (
        <>
          {q.data.warnings.length ? (
            <div className="rounded-lg border border-warning/40 bg-warning/10 p-3" role="status">
              <p className="mb-1 flex items-center gap-2 text-sm font-medium text-warning">
                <AlertTriangle className="h-4 w-4" /> {q.data.warnings.length} warning(s)
              </p>
              <ul className="list-inside list-disc text-xs">
                {q.data.warnings.map((w, i) => (
                  <li key={i}>{w}</li>
                ))}
              </ul>
            </div>
          ) : null}
          <CodeViewer content={q.data.content} filename="tac_plus-ng.cfg" />
        </>
      ) : null}
    </div>
  );
}
