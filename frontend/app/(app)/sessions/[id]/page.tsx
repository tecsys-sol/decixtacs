"use client";

import { useQuery } from "@tanstack/react-query";
import { useParams } from "next/navigation";
import { Search } from "lucide-react";
import * as React from "react";

import { ErrorState } from "@/components/common/error-state";
import { KeyValue } from "@/components/common/field";
import { PageHeader } from "@/components/common/page-header";
import { CastPlayer, type CastPlayerHandle } from "@/components/sessions/cast-player";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { api } from "@/lib/api";
import type { Page, Recording } from "@/lib/types";
import { cn, formatBytes, formatDateTime, formatDuration } from "@/lib/utils";

function fmtT(t: number) {
  const m = Math.floor(t / 60);
  const s = Math.floor(t % 60);
  return `${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
}

export default function SessionReplayPage() {
  const { id } = useParams<{ id: string }>();
  const player = React.useRef<CastPlayerHandle>(null);
  const [now, setNow] = React.useState(0);
  const [filter, setFilter] = React.useState("");

  // The API has no single-recording endpoint; locate the metadata in the list.
  const meta = useQuery({
    queryKey: ["sessions", "meta", id],
    queryFn: async () => {
      for (let offset = 0; offset < 5000; offset += 500) {
        const page = await api.get<Page<Recording>>("/sessions", { limit: 500, offset });
        const hit = page.items.find((r) => r.id === id);
        if (hit || page.items.length < 500) return hit ?? null;
      }
      return null;
    },
  });

  // Fetch the cast with the bearer token and hand the player a blob: URL.
  const cast = useQuery({
    queryKey: ["sessions", "cast", id],
    queryFn: async () => {
      const blob = await api.get<Blob>(`/sessions/${id}/cast`, undefined, { responseType: "blob", headers: { Accept: "*/*" } });
      return URL.createObjectURL(blob);
    },
    staleTime: Infinity,
    gcTime: 0,
  });

  React.useEffect(() => {
    const url = cast.data;
    return () => {
      if (url) URL.revokeObjectURL(url);
    };
  }, [cast.data]);

  const commands = React.useMemo(() => meta.data?.commands ?? [], [meta.data]);
  const markers = React.useMemo<[number, string][]>(() => commands.map((c) => [c.t, c.cmd]), [commands]);
  const activeIdx = React.useMemo(() => {
    let idx = -1;
    commands.forEach((c, i) => {
      if (c.t <= now + 0.01) idx = i;
    });
    return idx;
  }, [commands, now]);
  const shown = commands.map((c, i) => ({ ...c, i })).filter((c) => !filter || c.cmd.toLowerCase().includes(filter.toLowerCase()));

  const r = meta.data;
  return (
    <>
      <PageHeader
        breadcrumbs={[{ label: "Sessions", href: "/sessions" }, { label: "Replay" }]}
        title={r ? `${r.username}@${r.device_address}` : "Session replay"}
        description={r ? `${formatDateTime(r.started_at)} · ${formatDuration(r.duration_s)}` : undefined}
      />
      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_340px]">
        <div className="min-w-0">
          {cast.isLoading || meta.isLoading ? (
            <Skeleton className="aspect-video w-full" />
          ) : cast.error ? (
            <Card>
              <ErrorState error={cast.error} onRetry={() => void cast.refetch()} />
            </Card>
          ) : cast.data ? (
            <CastPlayer ref={player} src={cast.data} markers={markers} onTime={setNow} />
          ) : null}
          <p className="mt-2 text-xs text-muted-foreground">Replays are recorded in the audit log.</p>
        </div>
        <div className="grid content-start gap-4">
          <Card>
            <CardHeader>
              <CardTitle>Command index</CardTitle>
            </CardHeader>
            <CardContent className="grid gap-2">
              <div className="relative">
                <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
                <Input value={filter} onChange={(e) => setFilter(e.target.value)} placeholder="Filter commands" className="h-8 pl-8 text-xs" aria-label="Filter commands" />
              </div>
              {meta.isLoading ? (
                <Skeleton className="h-60" />
              ) : shown.length ? (
                <ol className="max-h-[55vh] overflow-y-auto rounded-md border scrollbar-thin">
                  {shown.map((c) => (
                    <li key={c.i}>
                      <button
                        type="button"
                        onClick={() => player.current?.seek(c.t)}
                        className={cn(
                          "flex w-full items-start gap-2 border-b px-2 py-1.5 text-left font-mono text-xs last:border-0 hover:bg-muted/50",
                          c.i === activeIdx && "bg-primary/10 text-primary",
                        )}
                        aria-current={c.i === activeIdx ? "true" : undefined}
                      >
                        <span className="shrink-0 text-muted-foreground tabular">{fmtT(c.t)}</span>
                        <span className="break-all">{c.cmd}</span>
                      </button>
                    </li>
                  ))}
                </ol>
              ) : (
                <p className="py-6 text-center text-xs text-muted-foreground">{commands.length ? "No matching commands" : "No commands captured"}</p>
              )}
            </CardContent>
          </Card>
          {r ? (
            <Card>
              <CardHeader>
                <CardTitle>Details</CardTitle>
              </CardHeader>
              <CardContent>
                <KeyValue
                  items={[
                    ["User", r.username],
                    ["Device", <span key="d" className="font-mono">{r.device_address}</span>],
                    ["Source", r.source_address ? <span key="s" className="font-mono">{r.source_address}</span> : null],
                    ["Started", formatDateTime(r.started_at)],
                    ["Ended", r.ended_at ? formatDateTime(r.ended_at) : null],
                    ["Size", formatBytes(r.size_bytes)],
                  ]}
                />
              </CardContent>
            </Card>
          ) : null}
        </div>
      </div>
    </>
  );
}
