"use client";

import { useQuery } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { CircleCheck, CircleHelp, CircleX, Waypoints } from "lucide-react";
import * as React from "react";

import { Chart, useChartMode } from "@/components/charts/chart";
import { EmptyState } from "@/components/common/empty-state";
import { ErrorState } from "@/components/common/error-state";
import { PageHeader } from "@/components/common/page-header";
import { SimpleSelect } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { Segmented } from "@/components/ui/tabs";
import { useSites } from "@/hooks/use-lookups";
import { useUrlState } from "@/hooks/use-url-state";
import { api } from "@/lib/api";
import { networkGraphOption, STATUS, type GraphLayout } from "@/lib/charts";
import type { Topology } from "@/lib/types";

function Legend({ topo }: { topo: Topology }) {
  const mode = useChartMode();
  const counts = topo.nodes.reduce<Record<string, number>>((acc, n) => {
    const k = n.status === "up" || n.status === "down" ? n.status : "unknown";
    acc[k] = (acc[k] ?? 0) + 1;
    return acc;
  }, {});
  const items = [
    { key: "up", label: "Up", icon: CircleCheck, color: STATUS[mode].success },
    { key: "down", label: "Down", icon: CircleX, color: STATUS[mode].danger },
    { key: "unknown", label: "Unknown", icon: CircleHelp, color: STATUS[mode].neutral },
  ];
  return (
    <div className="flex flex-wrap items-center gap-x-5 gap-y-2 text-[13px] text-ink-3">
      {items.map((i) => (
        <span key={i.key} className="flex items-center gap-1.5">
          <i.icon className="h-4 w-4" style={{ color: i.color }} aria-hidden /> {i.label}
          <span className="font-bold text-foreground tabular">{counts[i.key] ?? 0}</span>
        </span>
      ))}
      <span>
        {topo.edges.length} link{topo.edges.length === 1 ? "" : "s"} · {topo.sites.length} site{topo.sites.length === 1 ? "" : "s"}
      </span>
      <span className="text-ink-3">Hollow = up · filled red = down · grey = unknown · ring colour = site</span>
    </div>
  );
}

export default function MapPage() {
  const router = useRouter();
  const mode = useChartMode();
  const sites = useSites();
  const [f, setF] = useUrlState({ site: "", layout: "clustered" });
  const layout: GraphLayout = f.layout === "force" ? "force" : "clustered";
  const q = useQuery({
    queryKey: ["topology", f.site],
    queryFn: () => api.get<Topology>("/topology", { site_id: f.site }),
    refetchInterval: 60_000,
  });
  const option = React.useMemo(() => (q.data && q.data.nodes.length ? networkGraphOption(q.data, mode, layout) : null), [q.data, mode, layout]);

  return (
    <>
      <PageHeader
        title="Network map"
        description="Devices clustered by site with live link flows; links come from NetBox cables. Scroll to zoom, drag to pan, click a device to open it."
        actions={
          <>
            <Segmented<GraphLayout>
              aria-label="Layout"
              value={layout}
              onChange={(v) => setF({ layout: v })}
              options={[
                { value: "clustered", label: "Clustered" },
                { value: "force", label: "Force" },
              ]}
            />
            <SimpleSelect
              aria-label="Site"
              value={f.site}
              onValueChange={(v) => setF({ site: v })}
              allowEmpty
              emptyLabel="All sites"
              className="w-56"
              options={(sites.data ?? []).map((s) => ({ value: s.id, label: s.name }))}
            />
          </>
        }
      />
      <section className="rise flex flex-col gap-3 rounded-xl border bg-card p-4 sm:p-5" style={{ animationDelay: ".1s" }}>
        {q.data ? <Legend topo={q.data} /> : null}
        <div className="h-[calc(100vh-19rem)] min-h-[440px]">
          {q.isLoading ? (
            <Skeleton className="h-full w-full" />
          ) : q.error ? (
            <ErrorState error={q.error} onRetry={() => void q.refetch()} />
          ) : option ? (
            <Chart
              option={option}
              height="100%"
              ariaLabel="Network topology graph"
              onEvents={{
                click: (p) => {
                  const e = p as { dataType?: string; data?: { deviceId?: string } };
                  if (e.dataType === "node" && e.data?.deviceId) router.push(`/devices/${e.data.deviceId}`);
                },
              }}
            />
          ) : (
            <EmptyState icon={Waypoints} art="network" title="Nothing to draw" description="Add devices or sync NetBox to populate the map." className="h-full" />
          )}
        </div>
      </section>
    </>
  );
}
