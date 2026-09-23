"use client";

import { useQuery } from "@tanstack/react-query";
import dynamic from "next/dynamic";
import { Waypoints } from "lucide-react";

import { EmptyState } from "@/components/common/empty-state";
import { ErrorState } from "@/components/common/error-state";
import { PageHeader } from "@/components/common/page-header";
import { Card } from "@/components/ui/card";
import { SimpleSelect } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { useSites } from "@/hooks/use-lookups";
import { useUrlState } from "@/hooks/use-url-state";
import { api } from "@/lib/api";
import type { Topology } from "@/lib/types";

const NetworkMap = dynamic(() => import("@/components/map/network-map").then((m) => m.NetworkMap), {
  ssr: false,
  loading: () => <Skeleton className="h-full w-full" />,
});

function Legend({ topo }: { topo: Topology }) {
  const counts = topo.nodes.reduce<Record<string, number>>((acc, n) => {
    acc[n.status] = (acc[n.status] ?? 0) + 1;
    return acc;
  }, {});
  const items = [
    { key: "up", label: "Up", cls: "bg-success" },
    { key: "down", label: "Down", cls: "bg-destructive" },
    { key: "unknown", label: "Unknown", cls: "bg-muted-foreground" },
  ];
  return (
    <div className="flex flex-wrap items-center gap-4 text-xs text-muted-foreground">
      {items.map((i) => (
        <span key={i.key} className="flex items-center gap-1.5">
          <span className={`h-2.5 w-2.5 rounded-full ${i.cls}`} aria-hidden /> {i.label}
          <span className="font-medium text-foreground tabular">{counts[i.key] ?? 0}</span>
        </span>
      ))}
      <span>
        {topo.edges.length} link{topo.edges.length === 1 ? "" : "s"} · {topo.sites.length} site{topo.sites.length === 1 ? "" : "s"}
      </span>
    </div>
  );
}

export default function MapPage() {
  const sites = useSites();
  const [f, setF] = useUrlState({ site: "" });
  const q = useQuery({
    queryKey: ["topology", f.site],
    queryFn: () => api.get<Topology>("/topology", { site_id: f.site }),
    refetchInterval: 60_000,
  });

  return (
    <>
      <PageHeader
        title="Network map"
        description="Devices grouped by site; links from NetBox cables. Click a device to open it."
        actions={
          <SimpleSelect
            aria-label="Site"
            value={f.site}
            onValueChange={(v) => setF({ site: v })}
            allowEmpty
            emptyLabel="All sites"
            className="w-56"
            options={(sites.data ?? []).map((s) => ({ value: s.id, label: s.name }))}
          />
        }
      />
      {q.data ? (
        <div className="mb-2">
          <Legend topo={q.data} />
        </div>
      ) : null}
      <Card className="h-[calc(100vh-13rem)] min-h-[420px] overflow-hidden">
        {q.isLoading ? (
          <Skeleton className="h-full w-full" />
        ) : q.error ? (
          <ErrorState error={q.error} onRetry={() => void q.refetch()} />
        ) : q.data && q.data.nodes.length ? (
          <NetworkMap topology={q.data} />
        ) : (
          <EmptyState icon={Waypoints} title="Nothing to draw" description="Add devices or sync NetBox to populate the map." className="h-full" />
        )}
      </Card>
    </>
  );
}
