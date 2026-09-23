import type { Edge, Node } from "@xyflow/react";

import type { Topology } from "@/lib/types";

export interface DeviceNodeData extends Record<string, unknown> {
  label: string;
  status: string;
  role: string | null;
  platform: string | null;
  backup: string | null;
}

export interface SiteNodeData extends Record<string, unknown> {
  label: string;
  kind: string;
  count: number;
}

const NODE_W = 168;
const NODE_H = 52;
const GAP = 16;
const PAD = 16;
const HEADER = 34;
const SITE_GAP = 48;

/**
 * Deterministic layout: every site is a group node holding its devices in a grid; groups are
 * placed in rows. Devices without a site go into an "Unassigned" group.
 */
export function layoutTopology(topo: Topology): { nodes: Node[]; edges: Edge[] } {
  const bySite = new Map<string, Topology["nodes"]>();
  for (const n of topo.nodes) {
    const key = n.site_id ?? "__none__";
    const list = bySite.get(key) ?? [];
    list.push(n);
    bySite.set(key, list);
  }
  const siteMeta = new Map(topo.sites.map((s) => [s.id, s]));
  const groups = [...bySite.entries()].sort((a, b) => {
    const an = siteMeta.get(a[0])?.name ?? "~";
    const bn = siteMeta.get(b[0])?.name ?? "~";
    return an.localeCompare(bn);
  });

  const nodes: Node[] = [];
  const perRow = Math.max(1, Math.ceil(Math.sqrt(groups.length)));
  let x = 0;
  let y = 0;
  let rowHeight = 0;

  groups.forEach(([siteId, devices], gi) => {
    const cols = Math.max(1, Math.min(4, Math.ceil(Math.sqrt(devices.length))));
    const rows = Math.ceil(devices.length / cols);
    const width = PAD * 2 + cols * NODE_W + (cols - 1) * GAP;
    const height = HEADER + PAD + rows * NODE_H + (rows - 1) * GAP + PAD;
    const site = siteMeta.get(siteId);
    const groupId = `site:${siteId}`;
    nodes.push({
      id: groupId,
      type: "site",
      position: { x, y },
      data: { label: site?.name ?? "Unassigned", kind: site?.kind ?? "", count: devices.length } satisfies SiteNodeData,
      style: { width, height },
      selectable: false,
      draggable: true,
    });
    [...devices]
      .sort((a, b) => a.label.localeCompare(b.label))
      .forEach((d, i) => {
        nodes.push({
          id: d.id,
          type: "device",
          parentId: groupId,
          extent: "parent",
          position: { x: PAD + (i % cols) * (NODE_W + GAP), y: HEADER + Math.floor(i / cols) * (NODE_H + GAP) },
          data: { label: d.label, status: d.status, role: d.role, platform: d.platform, backup: d.backup } satisfies DeviceNodeData,
          style: { width: NODE_W, height: NODE_H },
        });
      });
    rowHeight = Math.max(rowHeight, height);
    if ((gi + 1) % perRow === 0) {
      x = 0;
      y += rowHeight + SITE_GAP;
      rowHeight = 0;
    } else {
      x += width + SITE_GAP;
    }
  });

  const edges: Edge[] = topo.edges.map((e) => ({
    id: e.id,
    source: e.source,
    target: e.target,
    label: e.speed_mbps ? `${e.speed_mbps >= 1000 ? `${e.speed_mbps / 1000}G` : `${e.speed_mbps}M`}` : undefined,
    data: { interfaces: e.label, status: e.status },
    animated: e.status !== "up",
    style: {
      stroke: e.status === "up" ? "hsl(var(--muted-foreground))" : "hsl(var(--destructive))",
      strokeWidth: e.speed_mbps && e.speed_mbps >= 100_000 ? 3 : 1.5,
    },
  }));

  return { nodes, edges };
}
