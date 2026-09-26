"use client";

import { useQuery } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { ArrowLeft, Building2, CircleCheck, CircleHelp, CircleX, Server, Waypoints } from "lucide-react";
import * as React from "react";

import { Chart, useChartTheme } from "@/components/charts/chart";
import { EmptyState } from "@/components/common/empty-state";
import { ErrorState } from "@/components/common/error-state";
import { PageHeader } from "@/components/common/page-header";
import { Button } from "@/components/ui/button";
import { SimpleSelect } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { Segmented } from "@/components/ui/tabs";
import { useSites } from "@/hooks/use-lookups";
import { useUrlState } from "@/hooks/use-url-state";
import { api } from "@/lib/api";
import { aggregateSites, networkGraphOption, siteGraphOption, type GraphLayout } from "@/lib/charts";
import type { Topology } from "@/lib/types";
import { cn } from "@/lib/utils";

type View = "sites" | "devices";

const SOURCES = [
  { key: "cable", label: "NetBox cables" },
  { key: "subnet", label: "Point-to-point subnets" },
  { key: "description", label: "Interface descriptions" },
] as const;

function Legend({ topo, view }: { topo: Topology; view: View }) {
  const theme = useChartTheme();
  const inside = topo.nodes.filter((n) => !n.external);
  const counts = inside.reduce<Record<string, number>>((acc, n) => {
    const k = n.status === "up" || n.status === "down" ? n.status : "unknown";
    acc[k] = (acc[k] ?? 0) + 1;
    return acc;
  }, {});
  const kinds = topo.edges.reduce<Record<string, number>>((acc, e) => {
    acc[e.kind ?? "cable"] = (acc[e.kind ?? "cable"] ?? 0) + 1;
    return acc;
  }, {});
  const items = [
    { key: "up", label: "Up", icon: CircleCheck, color: theme.status.success },
    { key: "down", label: "Down", icon: CircleX, color: theme.status.danger },
    { key: "unknown", label: "Unknown", icon: CircleHelp, color: theme.status.neutral },
  ];
  const external = topo.nodes.length - inside.length;
  return (
    <div className="flex flex-wrap items-center gap-x-5 gap-y-2 text-[13px] text-ink-3">
      {items.map((i) => (
        <span key={i.key} className="flex items-center gap-1.5">
          <i.icon className="h-4 w-4" style={{ color: i.color }} aria-hidden /> {i.label}
          <span className="font-bold text-foreground tabular">{counts[i.key] ?? 0}</span>
        </span>
      ))}
      <span>
        {topo.edges.length} link{topo.edges.length === 1 ? "" : "s"}
        {SOURCES.filter((s) => kinds[s.key]).map((s) => ` · ${kinds[s.key]} ${s.key === "cable" ? "cabled" : s.key === "subnet" ? "routed" : "described"}`).join("")}
      </span>
      {external ? <span>{external} neighbour{external === 1 ? "" : "s"} at other sites (faded)</span> : null}
      <span className="text-ink-3">
        {view === "sites" ? "Bubble size = devices · line = links between sites (width by capacity)" : "Line width = capacity · dashed = only named in descriptions · red = down"}
      </span>
    </div>
  );
}

export default function MapPage() {
  const router = useRouter();
  const theme = useChartTheme();
  const sites = useSites();
  const [f, setF] = useUrlState({ site: "", layout: "clustered", view: "", sources: "cable,subnet,description" });
  const layout: GraphLayout = f.layout === "force" ? "force" : "clustered";
  const multiSite = (sites.data?.length ?? 0) > 1;
  // default: the location overview when there is more than one site and none is selected
  const view: View = f.site ? "devices" : f.view === "devices" || f.view === "sites" ? (f.view as View) : multiSite ? "sites" : "devices";
  const sources = new Set(f.sources.split(",").filter(Boolean));
  const q = useQuery({
    queryKey: ["topology", f.site, f.sources],
    queryFn: () => api.get<Topology>("/topology", { site_id: f.site || undefined, sources: f.sources || "none" }),
    refetchInterval: 60_000,
  });
  const siteName = sites.data?.find((s) => s.id === f.site)?.name;

  const option = React.useMemo(() => {
    if (!q.data || !q.data.nodes.length) return null;
    return view === "sites" ? siteGraphOption(aggregateSites(q.data), theme) : networkGraphOption(q.data, theme, layout);
  }, [q.data, theme, layout, view]);

  const toggleSource = (key: string) => {
    const next = new Set(sources);
    if (next.has(key)) next.delete(key);
    else next.add(key);
    setF({ sources: SOURCES.map((s) => s.key).filter((k) => next.has(k)).join(",") || "none" });
  };

  return (
    <>
      <PageHeader
        title={siteName ? `Network map · ${siteName}` : "Network map"}
        description={
          view === "sites"
            ? "Locations and the links between them, from NetBox cables and the backed-up configurations. Click a site to see its devices."
            : siteName
              ? `Devices at ${siteName} and how they connect, including neighbours at other sites. Click a device to open it.`
              : "Devices clustered by site; links from NetBox cables and the backed-up configurations. Scroll to zoom, drag to pan, click a device to open it."
        }
        actions={
          <>
            {f.site ? (
              <Button variant="ghost" size="sm" onClick={() => setF({ site: "", view: "sites" })}>
                <ArrowLeft /> All sites
              </Button>
            ) : (
              <Segmented<View>
                aria-label="View"
                value={view}
                onChange={(v) => setF({ view: v })}
                options={[
                  { value: "sites", label: <><Building2 /> Sites</> },
                  { value: "devices", label: <><Server /> Devices</> },
                ]}
              />
            )}
            {view === "devices" ? (
              <Segmented<GraphLayout>
                aria-label="Layout"
                value={layout}
                onChange={(v) => setF({ layout: v })}
                options={[
                  { value: "clustered", label: "Clustered" },
                  { value: "force", label: "Force" },
                ]}
              />
            ) : null}
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
        <div className="flex flex-wrap items-center gap-2 text-xs">
          <span className="font-semibold text-ink-3">Links from</span>
          {SOURCES.map((s) => (
            <button
              key={s.key}
              type="button"
              aria-pressed={sources.has(s.key)}
              onClick={() => toggleSource(s.key)}
              className={cn(
                "rounded-full border px-2.5 py-1 font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                sources.has(s.key) ? "border-primary/40 bg-accent text-accent-foreground" : "text-ink-3 hover:bg-row-hover",
              )}
            >
              {s.label}
            </button>
          ))}
        </div>
        {q.data ? <Legend topo={q.data} view={view} /> : null}
        <div className="h-[calc(100vh-21rem)] min-h-[440px]">
          {q.isLoading ? (
            <Skeleton className="h-full w-full" />
          ) : q.error ? (
            <ErrorState error={q.error} onRetry={() => void q.refetch()} />
          ) : option ? (
            <Chart
              option={option}
              height="100%"
              ariaLabel={view === "sites" ? "Sites and the links between them" : "Network topology graph"}
              onEvents={{
                click: (p) => {
                  const e = p as { dataType?: string; data?: { deviceId?: string; siteId?: string } };
                  if (e.dataType !== "node") return;
                  if (e.data?.siteId) {
                    if (e.data.siteId !== "__none__") setF({ site: e.data.siteId });
                    else setF({ view: "devices" });
                  } else if (e.data?.deviceId) router.push(`/devices/${e.data.deviceId}?tab=ports`);
                },
              }}
            />
          ) : (
            <EmptyState icon={Waypoints} art="network" title="Nothing to draw" description="Add devices or sync NetBox, and run a backup so links can be found in the configurations." className="h-full" />
          )}
        </div>
      </section>
    </>
  );
}
