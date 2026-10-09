"use client";

import { useQuery } from "@tanstack/react-query";
import { Activity, AlertTriangle, CheckCircle2, CircleSlash, Network } from "lucide-react";
import * as React from "react";

import { Chart, useChartTheme } from "@/components/charts/chart";
import { ChartBody, ChartCard } from "@/components/common/chart-card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { SimpleSelect } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Segmented } from "@/components/ui/tabs";
import { api } from "@/lib/api";
import { barOption, lineOption, palette } from "@/lib/charts";
import type { IxpMember } from "@/lib/types";
import { cn, formatNumber } from "@/lib/utils";

export type Period = "day" | "week" | "month" | "year";
export type Category = "bits" | "pkts";
export type Protocol = "ipv4" | "ipv6";

interface GraphPoint {
  t: number;
  in: number;
  out: number;
  max_in: number;
  max_out: number;
}

interface GraphResult {
  graph: string;
  params: Record<string, string | number>;
  points: GraphPoint[];
  statistics: Record<string, number> | null;
  error: string | null;
  reason: string | null;
}

interface Fabric {
  integration: {
    id: string;
    name: string;
    base_url: string;
    last_sync_at: string | null;
    last_sync_status: string | null;
    vlan_interface_lookup: string | null;
    vlan_interfaces: number;
    member_vlans: number;
  } | null;
  fabric: { id: number | null; name: string | null; switches: { id: number; name: string }[]; vlans: { id: number; name: string }[] }[];
  message: string | null;
}

interface P2PRow {
  asn: number;
  name: string;
  dvli: number;
  averagein?: number;
  averageout?: number;
  maxin?: number;
  maxout?: number;
  totalin?: number;
  totalout?: number;
  error?: string;
  reason?: string;
}

interface P2PResult {
  asn: number;
  name?: string;
  vlan_id?: number;
  vlan?: string | null;
  svli?: number;
  peers: P2PRow[];
  peers_total?: number;
  peers_with_traffic?: number;
  error: string | null;
  reason: string | null;
}

interface HealthCheck {
  label: string;
  graph: string;
  ok: boolean;
  points?: number;
  reason: string | null;
  error: string | null;
}

/** 1.2 Gb/s, 850 kpps */
export function formatRate(v: number | null | undefined, category: Category = "bits"): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  const units = category === "bits" ? ["b/s", "kb/s", "Mb/s", "Gb/s", "Tb/s"] : ["pps", "kpps", "Mpps", "Gpps", "Tpps"];
  let n = Math.abs(v);
  let i = 0;
  while (n >= 1000 && i < units.length - 1) {
    n /= 1000;
    i += 1;
  }
  return `${v < 0 ? "-" : ""}${n >= 100 || i === 0 ? n.toFixed(0) : n.toFixed(1)} ${units[i]}`;
}

function timeLabel(t: number, period: Period): string {
  const d = new Date(t * 1000);
  if (period === "day") return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  if (period === "year") return d.toLocaleDateString([], { month: "short", year: "2-digit" });
  return d.toLocaleDateString([], { day: "2-digit", month: "short" }) + (period === "week" ? ` ${String(d.getHours()).padStart(2, "0")}h` : "");
}

const REASON_TITLE: Record<string, string> = {
  no_integration: "No IXP Manager integration",
  forbidden: "IXP Manager refused the graph",
  no_data: "No data in IXP Manager",
  all_zero: "No traffic recorded",
  not_found: "Unknown graph",
  unreachable: "IXP Manager unreachable",
  bad_response: "IXP Manager error",
  invalid: "Invalid graph request",
  no_vlan_interface: "Member not mapped in IXP Manager",
  no_object: "Nothing to graph",
};

/** One Grapher graph: in/out area chart with avg/max, or the reason it is empty. */
export function TrafficChart({
  title,
  description,
  graph,
  params,
  period,
  category,
  height = 240,
  delay,
  className,
  actions,
}: {
  title: React.ReactNode;
  description?: React.ReactNode;
  actions?: React.ReactNode;
  graph: string;
  params: Record<string, string | number | undefined>;
  period: Period;
  category: Category;
  height?: number;
  delay?: number;
  className?: string;
}) {
  const theme = useChartTheme();
  const q = useQuery({
    queryKey: ["ixp", "graph", graph, params, period, category],
    queryFn: () => api.get<GraphResult>("/ixp/graph", { graph, period, category, ...params }),
    staleTime: 60_000,
  });
  const r = q.data;
  const option = React.useMemo(() => {
    if (!r?.points.length) return null;
    const pal = palette(theme);
    return lineOption(
      {
        categories: r.points.map((p) => timeLabel(p.t, period)),
        series: [
          { name: "In", data: r.points.map((p) => p.in), color: pal[0] },
          { name: "Out", data: r.points.map((p) => p.out), color: pal[1] },
        ],
        area: true,
        min: 0,
        format: (v) => formatRate(v, category),
        axisFormat: (v) => formatRate(v, category),
      },
      theme,
    );
  }, [r, theme, period, category]);
  const st = r?.statistics;
  const empty = !!r && (!!r.reason && r.reason !== "all_zero");
  return (
    <ChartCard
      title={title}
      description={
        st && !empty ? (
          <span className="font-mono text-[11px]">
            in avg {formatRate(st.averagein, category)} · max {formatRate(st.maxin, category)} — out avg {formatRate(st.averageout, category)} · max {formatRate(st.maxout, category)}
          </span>
        ) : (
          description
        )
      }
      delay={delay}
      className={className}
      actions={actions}
    >
      <ChartBody
        loading={q.isLoading}
        error={q.error}
        onRetry={() => void q.refetch()}
        empty={empty}
        emptyTitle={r?.reason ? (REASON_TITLE[r.reason] ?? "No data") : "No data"}
        emptyDescription={r?.error ?? undefined}
        emptyIcon={r?.reason === "forbidden" ? CircleSlash : Activity}
        height={height}
      >
        {option ? <Chart option={option} height={height} ariaLabel={typeof title === "string" ? title : graph} /> : null}
        {r?.reason === "all_zero" ? <p className="px-1 pt-1 text-xs text-warning">{r.error}</p> : null}
      </ChartBody>
    </ChartCard>
  );
}

function GraphHealth() {
  const q = useQuery({ queryKey: ["ixp", "graph-health"], queryFn: () => api.get<{ checks: HealthCheck[]; error: string | null }>("/ixp/graphs/health"), staleTime: 60_000 });
  if (q.isLoading) return <Skeleton className="h-28" />;
  const checks = q.data?.checks ?? [];
  if (!checks.length) return null;
  const bad = checks.filter((c) => !c.ok);
  return (
    <Card data-testid="graph-health">
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          {bad.length ? <AlertTriangle className="h-4 w-4 text-warning" /> : <CheckCircle2 className="h-4 w-4 text-success" />}
          Graph sources {bad.length ? `- ${bad.length} of ${checks.length} not populating` : "- all populating"}
        </CardTitle>
        <CardDescription>One graph of each kind fetched from IXP Manager now; a failing kind shows why.</CardDescription>
      </CardHeader>
      <div className="grid gap-2 px-6 pb-5 md:grid-cols-2 xl:grid-cols-5">
        {checks.map((c) => (
          <div key={c.graph} className={cn("rounded-md border px-3 py-2 text-xs", c.ok ? "border-success/30" : "border-warning/40 bg-warning-soft")}>
            <div className="flex items-center justify-between gap-2">
              <span className="font-medium text-foreground">{c.label}</span>
              {c.ok ? <Badge variant="success">ok</Badge> : <Badge variant="warning">{(c.reason ?? "fail").replace("_", " ")}</Badge>}
            </div>
            {!c.ok && c.error ? <p className="mt-1 text-muted-foreground">{c.error}</p> : null}
          </div>
        ))}
      </div>
    </Card>
  );
}

export function GraphControls({
  period,
  setPeriod,
  category,
  setCategory,
  protocol,
  setProtocol,
}: {
  period: Period;
  setPeriod: (p: Period) => void;
  category: Category;
  setCategory: (c: Category) => void;
  protocol?: Protocol;
  setProtocol?: (p: Protocol) => void;
}) {
  return (
    <div className="flex flex-wrap items-center gap-2">
      <Segmented aria-label="Period" value={period} onChange={setPeriod} options={(["day", "week", "month", "year"] as const).map((p) => ({ value: p, label: p[0].toUpperCase() + p.slice(1) }))} />
      <Segmented aria-label="Unit" value={category} onChange={setCategory} options={[{ value: "bits", label: "Bits/s" }, { value: "pkts", label: "Packets/s" }]} />
      {protocol && setProtocol ? (
        <Segmented aria-label="Protocol" value={protocol} onChange={setProtocol} options={[{ value: "ipv4", label: "IPv4" }, { value: "ipv6", label: "IPv6" }]} />
      ) : null}
    </div>
  );
}

/** Exchange-wide traffic: total, per switch, per peering VLAN. */
export function TrafficTab() {
  const [period, setPeriod] = React.useState<Period>("day");
  const [category, setCategory] = React.useState<Category>("bits");
  const [protocol, setProtocol] = React.useState<Protocol>("ipv4");
  const fabric = useQuery({ queryKey: ["ixp", "fabric"], queryFn: () => api.get<Fabric>("/ixp/fabric") });
  const switches = React.useMemo(() => (fabric.data?.fabric ?? []).flatMap((f) => f.switches.map((s) => ({ ...s, ixp: f.name }))), [fabric.data]);
  const vlans = React.useMemo(() => (fabric.data?.fabric ?? []).flatMap((f) => f.vlans.map((v) => ({ ...v, ixp: f.name }))), [fabric.data]);
  const [sw, setSw] = React.useState<string>("");
  const [vl, setVl] = React.useState<string>("");
  const swId = sw || (switches[0] ? String(switches[0].id) : "");
  const vlId = vl || (vlans[0] ? String(vlans[0].id) : "");

  if (fabric.isLoading) return <Skeleton className="h-[60vh]" />;
  if (!fabric.data?.integration)
    return (
      <Card className="p-6 text-sm text-muted-foreground">
        <Network className="mb-2 h-5 w-5" />
        {fabric.data?.message ?? "No IXP Manager integration is configured."}
      </Card>
    );
  const integ = fabric.data.integration;
  return (
    <div className="grid gap-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-sm text-muted-foreground">
          From IXP Manager&apos;s Grapher ({integ.name}). {integ.vlan_interface_lookup && integ.vlan_interface_lookup !== "ok" ? <span className="text-warning">Member/P2P graphs: {integ.vlan_interface_lookup}.</span> : null}
        </p>
        <GraphControls period={period} setPeriod={setPeriod} category={category} setCategory={setCategory} protocol={protocol} setProtocol={setProtocol} />
      </div>
      <GraphHealth />
      <TrafficChart title="Exchange traffic" description="All peering ports (IXP Manager MRTG)" graph="ixp" params={{ id: 1 }} period={period} category={category} height={260} />
      <div className="grid gap-4 xl:grid-cols-2">
        <ChartCardWithPicker
          label="Switch"
          value={swId}
          onChange={setSw}
          options={switches.map((s) => ({ value: String(s.id), label: s.name }))}
          render={(id, picker) => (
            <TrafficChart title="Switch traffic" description="Member and core ports of the switch (MRTG)" graph="switch" params={{ id }} period={period} category={category} delay={1} actions={picker} />
          )}
        />
        <ChartCardWithPicker
          label="VLAN"
          value={vlId}
          onChange={setVl}
          options={vlans.map((v) => ({ value: String(v.id), label: v.name }))}
          render={(id, picker) => (
            <TrafficChart
              title={`Peering VLAN (${protocol === "ipv4" ? "IPv4" : "IPv6"})`}
              description="Member-to-member traffic on the VLAN (sFlow)"
              graph="vlan"
              params={{ id, protocol }}
              period={period}
              category={category}
              delay={2}
              actions={picker}
            />
          )}
        />
      </div>
    </div>
  );
}

function ChartCardWithPicker({
  label,
  value,
  onChange,
  options,
  render,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  options: { value: string; label: string }[];
  render: (id: string, picker: React.ReactNode) => React.ReactNode;
}) {
  if (!options.length)
    return (
      <Card className="p-6 text-sm text-muted-foreground">
        No {label.toLowerCase()} in IXP Manager&apos;s IX-F export - sync the integration.
      </Card>
    );
  const picker = options.length > 1 ? <SimpleSelect aria-label={label} value={value} onValueChange={onChange} options={options} className="w-52" /> : null;
  return <>{render(value, picker)}</>;
}

/** One member: traffic per peering VLAN and its P2P peers (busiest first), with the pair graph of a chosen peer. */
export function MemberTraffic({ member }: { member: IxpMember }) {
  const theme = useChartTheme();
  const [period, setPeriod] = React.useState<Period>("day");
  const [category, setCategory] = React.useState<Category>("bits");
  const [protocol, setProtocol] = React.useState<Protocol>("ipv4");
  const vlis = (member.connections ?? []).flatMap((c) => c.vlans.filter((v) => v.vli_id).map((v) => v));
  const [vlan, setVlan] = React.useState<number | null>(vlis[0]?.vlan_id ?? null);
  const current = vlis.find((v) => v.vlan_id === vlan) ?? vlis[0];
  const [peer, setPeer] = React.useState<P2PRow | null>(null);
  const p2p = useQuery({
    queryKey: ["ixp", "p2p", member.asn, current?.vlan_id, protocol, period, category],
    queryFn: () => api.get<P2PResult>(`/ixp/members/${member.asn}/p2p`, { vlan_id: current?.vlan_id ?? undefined, protocol, period, category }),
    staleTime: 60_000,
  });
  const rows = React.useMemo(() => (p2p.data?.peers ?? []).filter((r) => !r.error && (r.totalin ?? 0) + (r.totalout ?? 0) > 0), [p2p.data]);
  const top = rows.slice(0, 15);
  const bars = React.useMemo(() => {
    const pal = palette(theme);
    return barOption(
      {
        categories: top.map((r) => `AS${r.asn} ${r.name}`),
        series: [
          { name: "To member (avg in)", data: top.map((r) => r.averagein ?? 0), color: pal[0] },
          { name: "From member (avg out)", data: top.map((r) => r.averageout ?? 0), color: pal[1] },
        ],
        horizontal: true,
        labelWidth: 170,
        format: (v) => formatRate(v, category),
      },
      theme,
    );
  }, [top, theme, category]);

  if (!vlis.length)
    return (
      <p className="px-4 pb-3 text-xs text-muted-foreground">
        Traffic graphs: this member&apos;s VLAN interface is not known yet - IXP Manager keys member and P2P graphs by it (found through the MAC addresses configured in IXP Manager; the integration&apos;s API key must belong to a superuser).
      </p>
    );
  return (
    <div className="grid gap-3 px-3 pb-4" data-testid="member-traffic">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="text-sm font-medium">Traffic</span>
        <div className="flex flex-wrap items-center gap-2">
          {vlis.length > 1 ? (
            <SimpleSelect
              aria-label="VLAN"
              value={String(current?.vlan_id ?? "")}
              onValueChange={(v) => {
                setVlan(Number(v));
                setPeer(null);
              }}
              options={vlis.map((v) => ({ value: String(v.vlan_id), label: v.vlan ?? `VLAN ${v.vlan_id}` }))}
              className="w-48"
            />
          ) : null}
          <GraphControls period={period} setPeriod={setPeriod} category={category} setCategory={setCategory} protocol={protocol} setProtocol={setProtocol} />
        </div>
      </div>
      <TrafficChart
        title={`AS${member.asn} on ${current?.vlan ?? `VLAN ${current?.vlan_id}`}`}
        description="All traffic of the member's port on the VLAN (sFlow)"
        graph="vlaninterface"
        params={{ id: current?.vli_id ?? undefined, protocol }}
        period={period}
        category={category}
        height={220}
      />
      <div className="grid gap-3 xl:grid-cols-[1.1fr_1fr]">
        <ChartCard
          title="Top peers (P2P)"
          description={
            p2p.data?.peers_total !== undefined
              ? `${formatNumber(p2p.data.peers_with_traffic ?? 0)} of ${formatNumber(p2p.data.peers_total)} members exchanged traffic with AS${member.asn} - click one for its graph`
              : "Traffic with each other member on the VLAN"
          }
        >
          <ChartBody
            loading={p2p.isLoading}
            error={p2p.error}
            onRetry={() => void p2p.refetch()}
            empty={!top.length}
            emptyTitle={p2p.data?.reason ? (REASON_TITLE[p2p.data.reason] ?? "No P2P data") : "No P2P traffic"}
            emptyDescription={p2p.data?.error ?? undefined}
            emptyIcon={p2p.data?.reason === "forbidden" ? CircleSlash : Activity}
            height={Math.max(220, top.length * 26 + 40)}
          >
            <Chart
              option={bars}
              height={Math.max(220, top.length * 26 + 40)}
              ariaLabel="Traffic per peer"
              onEvents={{
                click: (e: unknown) => {
                  const i = (e as { dataIndex?: number }).dataIndex;
                  if (typeof i === "number" && top[i]) setPeer(top[i]);
                },
              }}
            />
          </ChartBody>
        </ChartCard>
        {peer ? (
          <TrafficChart
            title={`AS${member.asn} ↔ AS${peer.asn} ${peer.name}`}
            description="Member-to-member traffic (IXP Manager P2P, sFlow)"
            actions={
              <Button variant="ghost" size="xs" onClick={() => setPeer(null)}>
                All peers
              </Button>
            }
            graph="p2p"
            params={{ svli: p2p.data?.svli, dvli: peer.dvli, protocol }}
            period={period}
            category={category}
            height={Math.max(220, top.length * 26 + 40) - 40}
          />
        ) : (
          <Card className="overflow-hidden">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Peer</TableHead>
                  <TableHead className="text-right">Avg in</TableHead>
                  <TableHead className="text-right">Avg out</TableHead>
                  <TableHead className="text-right">Max</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {rows.slice(0, 12).map((r) => (
                  <TableRow key={r.dvli} className="cursor-pointer" onClick={() => setPeer(r)}>
                    <TableCell className="max-w-[200px] truncate text-xs">
                      <span className="font-mono">AS{r.asn}</span> {r.name}
                    </TableCell>
                    <TableCell className="text-right font-mono text-xs">{formatRate(r.averagein, category)}</TableCell>
                    <TableCell className="text-right font-mono text-xs">{formatRate(r.averageout, category)}</TableCell>
                    <TableCell className="text-right font-mono text-xs">{formatRate(Math.max(r.maxin ?? 0, r.maxout ?? 0), category)}</TableCell>
                  </TableRow>
                ))}
                {!rows.length ? (
                  <TableRow>
                    <TableCell colSpan={4} className="text-xs text-muted-foreground">
                      {p2p.isLoading ? "Loading…" : "No peer with traffic in this period."}
                    </TableCell>
                  </TableRow>
                ) : null}
              </TableBody>
            </Table>
          </Card>
        )}
      </div>
    </div>
  );
}
