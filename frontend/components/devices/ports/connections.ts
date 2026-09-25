import type { EChartsOption } from "echarts";

import { resolveTheme, type ChartTheme } from "@/lib/charts";

import { peerLabel, type DevicePorts, type Peer, type Port } from "./types";

/** More BGP neighbours than this behind one port are folded into a single "N BGP peers" node. */
export const BGP_FOLD = 6;

export interface GraphNode {
  id: string;
  kind: "self" | "port" | "lag" | "device" | "bgp" | "asn" | "bgp-group";
  label: string;
  x: number;
  y: number;
  /** port names this node stands for (to select / highlight on the faceplate) */
  ports: string[];
  device_id?: string;
  detail?: string[];
  color?: string;
}

export interface GraphEdge {
  source: string;
  target: string;
  label?: string;
  dashed?: boolean;
  width?: number;
}

function speedWidth(speed: string | null): number {
  const n = speed ? parseFloat(speed) : 0;
  return n >= 400 ? 4.5 : n >= 100 ? 3.5 : n >= 40 ? 3 : n >= 10 ? 2.2 : 1.4;
}

function peerKey(p: Peer): string {
  if (p.kind === "device") return `dev:${p.device_id}`;
  if (p.kind === "asn") return `asn:${p.asn}`;
  return p.device_id ? `dev:${p.device_id}` : `bgp:${p.address}`;
}

/**
 * Radial map of one device: the device in the middle, its connected ports / LAGs on an inner ring,
 * whatever sits behind them on an outer ring. A peer reached over several ports is one node
 * between them. Crowded peering LANs fold into one node.
 */
export function buildConnections(data: DevicePorts, lagColors: Map<string, string>): { nodes: GraphNode[]; edges: GraphEdge[]; hidden: number } {
  // attachments: one per LAG, one per standalone port that leads somewhere
  const attachments: { id: string; kind: "port" | "lag"; label: string; ports: Port[]; peers: Peer[]; color?: string }[] = [];
  const lagOf = new Map<string, Port[]>();
  for (const p of data.ports) if (p.lag) lagOf.set(p.lag, [...(lagOf.get(p.lag) ?? []), p]);
  for (const lag of data.lags) {
    const members = lagOf.get(lag.name) ?? [];
    const speeds = [...new Set(members.map((m) => m.speed).filter(Boolean))];
    attachments.push({
      id: `lag:${lag.name}`,
      kind: "lag",
      label: `${lag.name}${members.length ? ` (${members.length}×${speeds[0] ?? ""})` : ""}`,
      ports: members,
      // the LAG's own neighbours plus devices its member links lead to (e.g. named in their descriptions)
      peers: [...(lag.peers ?? []), ...members.flatMap((m) => m.peers.filter((p) => p.kind === "device"))],
      color: lagColors.get(lag.name),
    });
  }
  let hidden = 0;
  for (const p of data.ports) {
    if (p.lag || p.state === "unused") continue;
    if (!p.peers.length) {
      hidden++;
      continue;
    }
    attachments.push({ id: `port:${p.name}`, kind: "port", label: p.name, ports: [p], peers: p.peers });
  }

  const nodes: GraphNode[] = [{ id: "self", kind: "self", label: data.device.hostname, x: 0, y: 0, ports: [] }];
  const edges: GraphEdge[] = [];
  const n = Math.max(attachments.length, 1);
  const R1 = 170 + Math.min(120, n * 4);
  const R2 = R1 + 190;
  const peerAngles = new Map<string, { node: GraphNode; angles: number[] }>();

  attachments.forEach((a, i) => {
    const ang = (2 * Math.PI * i) / n - Math.PI / 2;
    const speed = a.ports[0]?.speed ?? null;
    nodes.push({
      id: a.id,
      kind: a.kind,
      label: a.label,
      x: Math.cos(ang) * R1,
      y: Math.sin(ang) * R1,
      ports: a.ports.map((p) => p.name),
      color: a.color,
      detail: [a.ports[0]?.description, ...a.ports.map((p) => `${p.name}${p.speed ? ` ${p.speed}` : ""}`)].filter((x): x is string => !!x),
    });
    edges.push({ source: "self", target: a.id, width: speedWidth(speed) * (a.kind === "lag" ? 1.4 : 1) });

    const bgp = a.peers.filter((p) => p.kind === "bgp" && !p.device_id);
    const others = a.peers.filter((p) => !(p.kind === "bgp" && !p.device_id));
    const shown: Peer[] = [...others, ...(bgp.length > BGP_FOLD ? [] : bgp)];
    shown.forEach((p) => {
      const key = peerKey(p);
      let entry = peerAngles.get(key);
      if (!entry) {
        const node: GraphNode = {
          id: key,
          kind: p.kind === "device" || p.device_id ? "device" : p.kind,
          label: p.kind === "device" || p.device_id ? (p.hostname ?? "device") : peerLabel(p),
          x: 0,
          y: 0,
          ports: [],
          device_id: p.device_id,
          detail: [],
        };
        entry = { node, angles: [] };
        peerAngles.set(key, entry);
        nodes.push(node);
      }
      entry.angles.push(ang);
      entry.node.ports.push(...a.ports.map((x) => x.name));
      const via = p.kind === "bgp" ? `BGP ${p.address}${p.asn ? ` AS${p.asn}` : ""}` : p.interface ? `${p.interface} (${p.source})` : p.source;
      entry.node.detail!.push(`${a.label} → ${via}`);
      if (!edges.some((e) => e.source === a.id && e.target === key)) {
        edges.push({
          source: a.id,
          target: key,
          label: p.kind === "device" && p.interface ? p.interface : undefined,
          dashed: p.source === "description",
        });
      }
    });
    if (bgp.length > BGP_FOLD) {
      const id = `bgpgroup:${a.id}`;
      const asns = [...new Set(bgp.map((b) => b.asn).filter(Boolean))];
      nodes.push({
        id,
        kind: "bgp-group",
        label: `${bgp.length}${a.ports[0]?.bgp_total && a.ports[0].bgp_total > bgp.length ? "+" : ""} BGP peers`,
        x: Math.cos(ang) * R2,
        y: Math.sin(ang) * R2,
        ports: a.ports.map((p) => p.name),
        detail: bgp.slice(0, 18).map((b) => `${b.address}  ${peerLabel(b)}`).concat(bgp.length > 18 ? [`… ${bgp.length - 18} more`] : []),
      });
      edges.push({ source: a.id, target: id, label: `${asns.length} ASNs` });
    }
  });

  // Devices sit on the inner peer ring; BGP / ASN peers fan out on an outer arc around their
  // port; a peer shared by several ports sits at their mean angle.
  const sector = (2 * Math.PI) / Math.max(n, 1);
  const groups = new Map<string, GraphNode[]>();
  for (const { node, angles } of peerAngles.values()) {
    if (angles.length > 1) {
      const base = Math.atan2(
        angles.reduce((s, a) => s + Math.sin(a), 0),
        angles.reduce((s, a) => s + Math.cos(a), 0),
      );
      node.x = Math.cos(base) * (R2 + 20);
      node.y = Math.sin(base) * (R2 + 20);
      continue;
    }
    const key = `${angles[0]}|${node.kind === "device" ? "d" : "o"}`;
    groups.set(key, [...(groups.get(key) ?? []), node]);
  }
  for (const [key, list] of groups) {
    const [a, kind] = [Number(key.split("|")[0]), key.split("|")[1]];
    const outer = kind === "o";
    const span = Math.min(sector * 0.85, (outer ? 0.2 : 0.14) * (list.length - 1));
    list.forEach((node, i) => {
      const ang = list.length > 1 ? a - span / 2 + (span * i) / (list.length - 1) : a;
      const r = outer ? R2 + 110 + (list.length > 3 ? (i % 2) * 55 : 0) : R2;
      node.x = Math.cos(ang) * r;
      node.y = Math.sin(ang) * r;
    });
  }
  return { nodes, edges, hidden };
}

export function connectionsOption(graph: { nodes: GraphNode[]; edges: GraphEdge[] }, theme: ChartTheme): EChartsOption {
  const th = resolveTheme(theme);
  const t = th.tokens;
  const c = th.categorical;
  const style: Record<GraphNode["kind"], { color: string; symbol: string; size: number | [number, number] }> = {
    self: { color: t.brand, symbol: "roundRect", size: [150, 46] },
    port: { color: th.status.success, symbol: "roundRect", size: [18, 14] },
    lag: { color: c[0], symbol: "roundRect", size: [22, 18] },
    device: { color: c[0], symbol: "circle", size: 30 },
    bgp: { color: c[1], symbol: "circle", size: 16 },
    asn: { color: c[3], symbol: "diamond", size: 18 },
    "bgp-group": { color: c[1], symbol: "circle", size: 38 },
  };
  return {
    animationDurationUpdate: 400,
    tooltip: {
      trigger: "item",
      confine: true,
      backgroundColor: t.surface,
      borderColor: t.tooltipBorder,
      textStyle: { color: t.ink, fontFamily: th.fonts.body, fontSize: 12 },
      extraCssText: `box-shadow:${t.tooltipShadow};border-radius:${t.tooltipRadius}px;max-width:360px;white-space:normal;`,
      formatter: (p: unknown) => {
        const d = (p as { dataType: string; data: { name?: string; detail?: string[]; source?: string; target?: string } }).data;
        if ((p as { dataType: string }).dataType === "edge") return "";
        const esc = (s: string) => s.replace(/[&<>]/g, (ch) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" })[ch] ?? ch);
        return `<b>${esc(d.name ?? "")}</b>${(d.detail ?? []).map((x) => `<div style="opacity:.8;font-family:${th.fonts.mono};font-size:11px">${esc(x)}</div>`).join("")}`;
      },
    },
    series: [
      {
        type: "graph",
        layout: "none",
        roam: true,
        draggable: true,
        zoom: 0.85,
        edgeSymbol: ["none", "none"],
        emphasis: { focus: "adjacency", lineStyle: { width: 4 } },
        label: { show: true, color: t.ink, fontFamily: th.fonts.body, fontSize: 11 },
        edgeLabel: { show: true, fontSize: 9, color: t.label, fontFamily: th.fonts.mono, formatter: (p: unknown) => (p as { data: { label?: string } }).data.label ?? "" },
        data: graph.nodes.map((n) => {
          const s = style[n.kind];
          const color = n.color ?? s.color;
          return {
            id: n.id,
            name: n.label,
            x: n.x,
            y: n.y,
            symbol: s.symbol,
            symbolSize: s.size,
            detail: n.detail,
            itemStyle:
              n.kind === "self"
                ? { color, shadowBlur: 18, shadowColor: `${color}66` }
                : n.kind === "device"
                  ? { color: t.surface, borderColor: color, borderWidth: 3 }
                  : { color, borderColor: t.surface, borderWidth: 1.5 },
            label:
              n.kind === "self"
                ? { position: "inside", color: t.onBrand, fontWeight: 700, fontSize: 13, fontFamily: th.fonts.display }
                : n.kind === "port" || n.kind === "lag"
                  ? { position: n.x >= 0 ? "right" : "left", fontFamily: th.fonts.mono, fontSize: 10.5, color: t.ink2 }
                  : { position: n.x >= 0 ? "right" : "left", fontWeight: n.kind === "device" ? 700 : 500 },
          };
        }),
        links: graph.edges.map((e) => ({
          source: e.source,
          target: e.target,
          label: e.label,
          lineStyle: { color: t.link, width: e.width ?? 1.4, type: e.dashed ? "dashed" : "solid", opacity: 0.9, curveness: 0 },
        })),
      },
    ],
  } as EChartsOption;
}
