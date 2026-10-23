"use client";

import { useQuery } from "@tanstack/react-query";
import { Activity, AlertTriangle, CheckCircle2, CircleSlash, Download, Grid3X3, Handshake, Network } from "lucide-react";
import type { EChartsOption } from "echarts";
import * as React from "react";

import { Chart, useChartTheme } from "@/components/charts/chart";
import { ChartBody, ChartCard } from "@/components/common/chart-card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { SimpleSelect } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Segmented } from "@/components/ui/tabs";
import { toast } from "@/hooks/use-toast";
import { api, errorMessage } from "@/lib/api";
import { barOption, heatmapOption, lineOption, palette } from "@/lib/charts";
import type { IxpMember } from "@/lib/types";
import { cn, formatNumber } from "@/lib/utils";

export type Period = "day" | "week" | "month" | "year" | "custom";
export type Category = "bits" | "pkts";
export type Protocol = "ipv4" | "ipv6";
export type ProtocolChoice = Protocol | "both";
/** custom range (IXP Manager 7.x supports it for P2P graphs), as ISO strings */
export interface Range {
  start: string;
  end: string;
}

const STANDARD: Exclude<Period, "custom">[] = ["day", "week", "month", "year"];

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
  /** computed by NOM: 95th percentile, peaks, sample step */
  derived?: { p95_in?: number; p95_out?: number; p95?: number; peak_in?: number; peak_out?: number; step_seconds?: number | null; samples?: number };
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
  share?: number;
  by_protocol?: Partial<Record<Protocol, { averagein: number; averageout: number; totalin: number; totalout: number }>>;
  peering_policy?: string | null;
  rs_client?: boolean;
  rs_sessions?: { up: number; down: number } | null;
  error?: string;
  reason?: string;
}

interface Opportunity {
  asn: number;
  name: string;
  dvli: number;
  peering_policy: string | null;
  rs_client: boolean;
  rs_sessions: { up: number; down: number } | null;
  via_route_servers: boolean;
  hint: string;
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
  capacity_mbps?: number | null;
  rs_client?: boolean;
  opportunities?: Opportunity[];
  error: string | null;
  reason: string | null;
}

interface Matrix {
  vlan_id?: number;
  vlan?: string | null;
  members: { asn: number; name: string; vli_id: number }[];
  cells: (number | null)[][];
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

/** "42 %" of a port's capacity (Mb/s); only for bit rates */
function utilisation(bps: number | undefined, capacityMbps: number | null | undefined): string | null {
  if (!bps || !capacityMbps) return null;
  const pct = (bps / (capacityMbps * 1e6)) * 100;
  return `${pct < 10 ? pct.toFixed(1) : pct.toFixed(0)} %`;
}

function timeLabel(t: number, period: Period, spanSeconds = 0): string {
  const d = new Date(t * 1000);
  if (period === "custom") period = spanSeconds <= 2 * 86400 ? "day" : spanSeconds <= 14 * 86400 ? "week" : spanSeconds <= 62 * 86400 ? "month" : "year";
  if (period === "day") return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  if (period === "year") return d.toLocaleDateString([], { month: "short", year: "2-digit" });
  return d.toLocaleDateString([], { day: "2-digit", month: "short" }) + (period === "week" ? ` ${String(d.getHours()).padStart(2, "0")}h` : "");
}

const REASON_TITLE: Record<string, string> = {
  no_integration: "No IXP Manager integration",
  auth: "IXP Manager rejected the API key",
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

function graphQuery(graph: string, params: Record<string, string | number | undefined>, period: Period, category: Category, range?: Range) {
  return {
    graph,
    category,
    period,
    ...(period === "custom" && range ? { period_start: range.start, period_end: range.end } : {}),
    ...params,
  };
}

/** One Grapher graph: in/out area chart with avg/max, 95th percentile and port utilisation, a CSV
 *  download, or the reason it is empty. */
export function TrafficChart({
  title,
  description,
  graph,
  params,
  period,
  range,
  category,
  capacityMbps,
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
  range?: Range;
  category: Category;
  /** port capacity in Mb/s: shows peak / 95th percentile as a share of it */
  capacityMbps?: number | null;
  height?: number;
  delay?: number;
  className?: string;
}) {
  const theme = useChartTheme();
  const query = graphQuery(graph, params, period, category, range);
  const q = useQuery({
    queryKey: ["ixp", "graph", query],
    queryFn: () => api.get<GraphResult>("/ixp/graph", query),
    staleTime: 60_000,
  });
  const r = q.data;
  const span = r?.points.length ? r.points[r.points.length - 1].t - r.points[0].t : 0;
  const option = React.useMemo(() => {
    if (!r?.points.length) return null;
    const pal = palette(theme);
    return lineOption(
      {
        categories: r.points.map((p) => timeLabel(p.t, period, span)),
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
  }, [r, theme, period, category, span]);
  const st = r?.statistics;
  const d = r?.derived;
  const empty = !!r && !!r.reason && r.reason !== "all_zero";
  const bits = category === "bits";
  const peakUtil = bits ? utilisation(Math.max(d?.peak_in ?? 0, d?.peak_out ?? 0), capacityMbps) : null;
  const p95Util = bits ? utilisation(d?.p95, capacityMbps) : null;
  const download = async () => {
    try {
      const ids = ["id", "svli", "dvli"].map((k) => params[k]).filter((x) => x !== undefined).join("-");
      await api.download("/ixp/graph.csv", query, `${graph}-${ids}-${String(params.protocol ?? "all")}-${period}.csv`);
    } catch (e) {
      toast.error("Could not export", errorMessage(e));
    }
  };
  return (
    <ChartCard
      title={title}
      description={
        st && !empty ? (
          <span className="grid gap-0.5 font-mono text-[11px]">
            <span>
              in avg {formatRate(st.averagein, category)} · max {formatRate(st.maxin, category)} — out avg {formatRate(st.averageout, category)} · max{" "}
              {formatRate(st.maxout, category)}
            </span>
            {d?.p95 !== undefined ? (
              <span title={d.step_seconds ? `95th percentile of ${d.samples} samples of ${Math.round(d.step_seconds / 60)} min` : undefined}>
                95th pct in {formatRate(d.p95_in, category)} · out {formatRate(d.p95_out, category)}
                {p95Util ? ` · ${p95Util} of ${formatRate((capacityMbps ?? 0) * 1e6)} port` : ""}
                {peakUtil ? ` · peak ${peakUtil}` : ""}
              </span>
            ) : null}
          </span>
        ) : (
          description
        )
      }
      delay={delay}
      className={className}
      actions={
        <div className="flex items-center gap-1">
          {actions}
          {r?.points.length ? (
            <Button variant="ghost" size="icon-sm" aria-label="Download CSV" title="Download as CSV" onClick={() => void download()}>
              <Download />
            </Button>
          ) : null}
        </div>
      }
    >
      <ChartBody
        loading={q.isLoading}
        error={q.error}
        onRetry={() => void q.refetch()}
        empty={empty}
        emptyTitle={r?.reason ? (REASON_TITLE[r.reason] ?? "No data") : "No data"}
        emptyDescription={r?.error ?? undefined}
        emptyIcon={r?.reason === "forbidden" || r?.reason === "auth" ? CircleSlash : Activity}
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

function toLocalInput(iso: string): string {
  const d = new Date(iso);
  const off = d.getTimezoneOffset() * 60_000;
  return new Date(d.getTime() - off).toISOString().slice(0, 16);
}

export function defaultRange(): Range {
  const end = new Date();
  end.setMinutes(0, 0, 0);
  return { start: new Date(end.getTime() - 48 * 3600_000).toISOString(), end: end.toISOString() };
}

export function GraphControls({
  period,
  setPeriod,
  category,
  setCategory,
  protocol,
  setProtocol,
  allowCustom,
  allowBoth,
  range,
  setRange,
}: {
  period: Period;
  setPeriod: (p: Period) => void;
  category: Category;
  setCategory: (c: Category) => void;
  protocol?: ProtocolChoice;
  setProtocol?: (p: ProtocolChoice) => void;
  /** offer a custom date range (IXP Manager supports it for P2P graphs) */
  allowCustom?: boolean;
  allowBoth?: boolean;
  range?: Range;
  setRange?: (r: Range) => void;
}) {
  const periods = (allowCustom ? [...STANDARD, "custom" as const] : STANDARD).map((p) => ({ value: p, label: p[0].toUpperCase() + p.slice(1) }));
  const protocols = [{ value: "ipv4" as const, label: "IPv4" }, { value: "ipv6" as const, label: "IPv6" }, ...(allowBoth ? [{ value: "both" as const, label: "Both" }] : [])];
  return (
    <div className="flex flex-wrap items-center gap-2">
      <Segmented aria-label="Period" value={period} onChange={setPeriod} options={periods} />
      {period === "custom" && range && setRange ? (
        <span className="flex items-center gap-1 text-xs">
          <Input
            type="datetime-local"
            aria-label="From"
            value={toLocalInput(range.start)}
            onChange={(e) => e.target.value && setRange({ ...range, start: new Date(e.target.value).toISOString() })}
            className="h-8 w-[11.5rem] text-xs"
          />
          –
          <Input
            type="datetime-local"
            aria-label="To"
            value={toLocalInput(range.end)}
            onChange={(e) => e.target.value && setRange({ ...range, end: new Date(e.target.value).toISOString() })}
            className="h-8 w-[11.5rem] text-xs"
          />
        </span>
      ) : null}
      <Segmented aria-label="Unit" value={category} onChange={setCategory} options={[{ value: "bits", label: "Bits/s" }, { value: "pkts", label: "Packets/s" }]} />
      {protocol && setProtocol ? <Segmented aria-label="Protocol" value={protocol} onChange={setProtocol} options={protocols} /> : null}
    </div>
  );
}

/** Exchange-wide traffic: total, per switch, per peering VLAN, and the P2P matrix of the busiest members. */
export function TrafficTab() {
  const [period, setPeriod] = React.useState<Period>("day");
  const [category, setCategory] = React.useState<Category>("bits");
  const [protocol, setProtocol] = React.useState<ProtocolChoice>("ipv4");
  const fabric = useQuery({ queryKey: ["ixp", "fabric"], queryFn: () => api.get<Fabric>("/ixp/fabric") });
  const switches = React.useMemo(() => (fabric.data?.fabric ?? []).flatMap((f) => f.switches.map((s) => ({ ...s, ixp: f.name }))), [fabric.data]);
  const vlans = React.useMemo(() => (fabric.data?.fabric ?? []).flatMap((f) => f.vlans.map((v) => ({ ...v, ixp: f.name }))), [fabric.data]);
  const [sw, setSw] = React.useState<string>("");
  const [vl, setVl] = React.useState<string>("");
  const swId = sw || (switches[0] ? String(switches[0].id) : "");
  const vlId = vl || (vlans[0] ? String(vlans[0].id) : "");
  const proto: Protocol = protocol === "ipv6" ? "ipv6" : "ipv4";
  const std = period === "custom" ? "day" : period;

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
        <GraphControls period={std} setPeriod={setPeriod} category={category} setCategory={setCategory} protocol={proto} setProtocol={setProtocol} />
      </div>
      <GraphHealth />
      <TrafficChart title="Exchange traffic" description="All peering ports (IXP Manager MRTG)" graph="ixp" params={{ id: 1 }} period={std} category={category} height={260} />
      <div className="grid gap-4 xl:grid-cols-2">
        <ChartCardWithPicker
          label="Switch"
          value={swId}
          onChange={setSw}
          options={switches.map((s) => ({ value: String(s.id), label: s.name }))}
          render={(id, picker) => (
            <TrafficChart title="Switch traffic" description="Member and core ports of the switch (MRTG)" graph="switch" params={{ id }} period={std} category={category} delay={1} actions={picker} />
          )}
        />
        <ChartCardWithPicker
          label="VLAN"
          value={vlId}
          onChange={setVl}
          options={vlans.map((v) => ({ value: String(v.id), label: v.name }))}
          render={(id, picker) => (
            <TrafficChart
              title={`Peering VLAN (${proto === "ipv4" ? "IPv4" : "IPv6"})`}
              description="Member-to-member traffic on the VLAN (sFlow)"
              graph="vlan"
              params={{ id, protocol: proto }}
              period={std}
              category={category}
              delay={2}
              actions={picker}
            />
          )}
        />
      </div>
      <P2PMatrix vlanId={vlId ? Number(vlId) : undefined} protocol={proto} period={std} category={category} />
    </div>
  );
}

/** Who exchanges how much with whom among the busiest members (IXP Manager shows one pair at a time). */
function P2PMatrix({ vlanId, protocol, period, category }: { vlanId?: number; protocol: Protocol; period: Exclude<Period, "custom">; category: Category }) {
  const theme = useChartTheme();
  const [top, setTop] = React.useState("12");
  const q = useQuery({
    queryKey: ["ixp", "p2p-matrix", vlanId, protocol, period, category, top],
    queryFn: () => api.get<Matrix>("/ixp/p2p-matrix", { vlan_id: vlanId, protocol, period, category, top: Number(top) }),
    staleTime: 120_000,
  });
  const m = q.data;
  const option = React.useMemo(() => {
    if (!m?.members.length) return null;
    const labels = m.members.map((x) => `AS${x.asn} ${x.name}`);
    const cells: [number, number, number][] = [];
    m.cells.forEach((row, a) => row.forEach((v, b) => {
      if (v !== null) cells.push([b, a, v]);
    }));
    const opt = heatmapOption(
      {
        xLabels: labels,
        yLabels: labels,
        cells,
        tooltip: (x, y, v) => `<b>${y}</b> receives from <b>${x}</b><br/>${formatRate(v, category)} average`,
      },
      theme,
    );
    // read like a matrix: busiest member top-left, every column labelled (slanted)
    const x = opt.xAxis as { axisLabel?: Record<string, unknown> };
    const y = opt.yAxis as Record<string, unknown>;
    return {
      ...opt,
      xAxis: { ...x, axisLabel: { ...(x.axisLabel ?? {}), interval: 0, rotate: 35, width: 140, overflow: "truncate" } },
      yAxis: { ...y, inverse: true },
    } as EChartsOption;
  }, [m, theme, category]);
  const height = Math.max(320, (m?.members.length ?? 0) * 30 + 120);
  return (
    <ChartCard
      title={
        <span className="flex items-center gap-2">
          <Grid3X3 className="h-4 w-4" /> P2P matrix
        </span>
      }
      description={`Average traffic between the ${m?.members.length || top} busiest members on ${m?.vlan ?? "the VLAN"} (${protocol === "ipv4" ? "IPv4" : "IPv6"}): row receives from column`}
      actions={
        <SimpleSelect aria-label="Members" value={top} onValueChange={setTop} options={["8", "12", "16", "20"].map((v) => ({ value: v, label: `Top ${v}` }))} className="w-28" />
      }
    >
      <ChartBody
        loading={q.isLoading}
        error={q.error}
        onRetry={() => void q.refetch()}
        empty={!option}
        emptyTitle={m?.reason ? (REASON_TITLE[m.reason] ?? "No P2P data") : "No P2P data"}
        emptyDescription={m?.error ?? undefined}
        emptyIcon={Grid3X3}
        height={height}
      >
        {option ? <Chart option={option} height={height} ariaLabel="P2P traffic matrix" /> : null}
      </ChartBody>
    </ChartCard>
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

const POLICY_VARIANT: Record<string, "success" | "info" | "warning" | "muted"> = { open: "success", selective: "info", restrictive: "warning" };

/** One member: port traffic per peering VLAN (with 95th percentile and utilisation), its P2P peers (busiest
 *  first, share of traffic, IPv4/IPv6), the pair graph of a chosen peer (any date range) and the members
 *  it exchanges no traffic with yet. */
export function MemberTraffic({ member }: { member: IxpMember }) {
  const theme = useChartTheme();
  const [period, setPeriod] = React.useState<Period>("day");
  const [range, setRange] = React.useState<Range>(defaultRange);
  const [category, setCategory] = React.useState<Category>("bits");
  const [protocol, setProtocol] = React.useState<ProtocolChoice>("ipv4");
  const conns = member.connections ?? [];
  const vlis = conns.flatMap((c) => c.vlans.filter((v) => v.vli_id));
  const [vlan, setVlan] = React.useState<number | null>(vlis[0]?.vlan_id ?? null);
  const current = vlis.find((v) => v.vlan_id === vlan) ?? vlis[0];
  const conn = conns.find((c) => c.vlans.some((v) => v.vlan_id === current?.vlan_id));
  const capacity = conn ? conn.ports.reduce((a, p) => a + (p.speed_mbps ?? 0), 0) || null : null;
  const [peer, setPeer] = React.useState<P2PRow | null>(null);
  const custom = period === "custom" ? { period_start: range.start, period_end: range.end } : {};
  const p2p = useQuery({
    queryKey: ["ixp", "p2p", member.asn, current?.vlan_id, protocol, period, category, custom],
    queryFn: () => api.get<P2PResult>(`/ixp/members/${member.asn}/p2p`, { vlan_id: current?.vlan_id ?? undefined, protocol, period, category, ...custom }),
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
  const protos: Protocol[] = protocol === "both" ? ["ipv4", "ipv6"] : [protocol];
  // the member's own port graph has no custom range in IXP Manager: it shows the day around it
  const portPeriod: Period = period === "custom" ? "day" : period;
  const both = protocol === "both";
  const opps = p2p.data?.opportunities ?? [];
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
          <GraphControls
            period={period}
            setPeriod={setPeriod}
            category={category}
            setCategory={setCategory}
            protocol={protocol}
            setProtocol={setProtocol}
            allowCustom
            allowBoth
            range={range}
            setRange={setRange}
          />
        </div>
      </div>
      {period === "custom" ? (
        <p className="text-xs text-muted-foreground">The custom range applies to the P2P graphs (IXP Manager offers it for P2P only); the port graph shows the last day.</p>
      ) : null}
      <div className={cn("grid gap-3", both && "xl:grid-cols-2")}>
        {protos.map((pr) => (
          <TrafficChart
            key={pr}
            title={`AS${member.asn} on ${current?.vlan ?? `VLAN ${current?.vlan_id}`}${both ? ` · ${pr === "ipv4" ? "IPv4" : "IPv6"}` : ""}`}
            description="All traffic of the member's port on the VLAN (sFlow)"
            graph="vlaninterface"
            params={{ id: current?.vli_id ?? undefined, protocol: pr }}
            period={portPeriod}
            category={category}
            capacityMbps={capacity}
            height={220}
          />
        ))}
      </div>
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
            emptyIcon={p2p.data?.reason === "forbidden" || p2p.data?.reason === "auth" ? CircleSlash : Activity}
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
          <div className="grid gap-3">
            {protos.map((pr) => (
              <TrafficChart
                key={pr}
                title={`AS${member.asn} ↔ AS${peer.asn} ${peer.name}${both ? ` · ${pr === "ipv4" ? "IPv4" : "IPv6"}` : ""}`}
                description="Member-to-member traffic (IXP Manager P2P, sFlow)"
                actions={
                  <Button variant="ghost" size="xs" onClick={() => setPeer(null)}>
                    All peers
                  </Button>
                }
                graph="p2p"
                params={{ svli: p2p.data?.svli, dvli: peer.dvli, protocol: pr }}
                period={period}
                range={range}
                category={category}
                height={both ? 180 : Math.max(220, top.length * 26 + 40) - 40}
              />
            ))}
          </div>
        ) : (
          <Card className="overflow-hidden">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Peer</TableHead>
                  <TableHead className="text-right">Avg in</TableHead>
                  <TableHead className="text-right">Avg out</TableHead>
                  <TableHead className="text-right">Share</TableHead>
                  {both ? <TableHead className="text-right">IPv6</TableHead> : <TableHead className="text-right">Max</TableHead>}
                </TableRow>
              </TableHeader>
              <TableBody>
                {rows.slice(0, 12).map((r) => {
                  const v6 = r.by_protocol?.ipv6;
                  const v6share = v6 && (r.totalin ?? 0) + (r.totalout ?? 0) ? (100 * (v6.totalin + v6.totalout)) / ((r.totalin ?? 0) + (r.totalout ?? 0)) : null;
                  return (
                    <TableRow key={r.dvli} className="cursor-pointer" onClick={() => setPeer(r)}>
                      <TableCell className="max-w-[200px] truncate text-xs">
                        <span className="font-mono">AS{r.asn}</span> {r.name}
                      </TableCell>
                      <TableCell className="text-right font-mono text-xs">{formatRate(r.averagein, category)}</TableCell>
                      <TableCell className="text-right font-mono text-xs">{formatRate(r.averageout, category)}</TableCell>
                      <TableCell className="text-right font-mono text-xs">{r.share !== undefined ? `${r.share.toFixed(1)} %` : "—"}</TableCell>
                      <TableCell className="text-right font-mono text-xs">
                        {both ? (v6share !== null ? `${v6share.toFixed(0)} %` : "—") : formatRate(Math.max(r.maxin ?? 0, r.maxout ?? 0), category)}
                      </TableCell>
                    </TableRow>
                  );
                })}
                {!rows.length ? (
                  <TableRow>
                    <TableCell colSpan={5} className="text-xs text-muted-foreground">
                      {p2p.isLoading ? "Loading…" : "No peer with traffic in this period."}
                    </TableCell>
                  </TableRow>
                ) : null}
              </TableBody>
            </Table>
          </Card>
        )}
      </div>
      {opps.length ? (
        <Card className="overflow-hidden" data-testid="peering-opportunities">
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Handshake className="h-4 w-4" /> Peering opportunities ({opps.length})
            </CardTitle>
            <CardDescription>
              Members on {current?.vlan ?? "the VLAN"} that exchanged no traffic with AS{member.asn} in this period
              {p2p.data?.rs_client ? " (AS" + member.asn + " uses the route servers)" : " (AS" + member.asn + " does not use the route servers)"}.
            </CardDescription>
          </CardHeader>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Member</TableHead>
                <TableHead>Policy</TableHead>
                <TableHead>Route servers</TableHead>
                <TableHead className="w-full">Next step</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {opps.slice(0, 25).map((o) => (
                <TableRow key={o.dvli}>
                  <TableCell className="whitespace-nowrap text-xs">
                    <span className="font-mono">AS{o.asn}</span> {o.name}
                  </TableCell>
                  <TableCell>{o.peering_policy ? <Badge variant={POLICY_VARIANT[o.peering_policy.toLowerCase()] ?? "muted"}>{o.peering_policy}</Badge> : "—"}</TableCell>
                  <TableCell className="text-xs">
                    {o.rs_client ? (o.rs_sessions ? `${o.rs_sessions.up} up${o.rs_sessions.down ? ` · ${o.rs_sessions.down} down` : ""}` : "client") : "no"}
                  </TableCell>
                  <TableCell className="text-xs text-muted-foreground">{o.hint}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
          {opps.length > 25 ? <p className="border-t px-4 py-2 text-xs text-muted-foreground">{opps.length - 25} more</p> : null}
        </Card>
      ) : null}
    </div>
  );
}
