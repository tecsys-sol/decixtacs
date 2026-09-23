"use client";

import {
  Background,
  Controls,
  Handle,
  MiniMap,
  Position,
  ReactFlow,
  type Node,
  type NodeProps,
  type NodeTypes,
} from "@xyflow/react";
import { useRouter } from "next/navigation";
import { useTheme } from "next-themes";
import * as React from "react";

import "@xyflow/react/dist/style.css";

import type { Topology } from "@/lib/types";
import { cn } from "@/lib/utils";

import { layoutTopology, type DeviceNodeData, type SiteNodeData } from "./topology-layout";

const STATUS_CLS: Record<string, string> = {
  up: "border-success/60 bg-success/10",
  down: "border-destructive/70 bg-destructive/15",
  unknown: "border-border bg-muted/40",
};
const DOT_CLS: Record<string, string> = { up: "bg-success", down: "bg-destructive", unknown: "bg-muted-foreground" };

function DeviceNode({ data, selected }: NodeProps<Node<DeviceNodeData>>) {
  const status = STATUS_CLS[data.status] ? data.status : "unknown";
  return (
    <div
      className={cn(
        "flex h-full w-full cursor-pointer flex-col justify-center rounded-md border px-2.5 text-left shadow-sm transition-shadow hover:shadow-md",
        STATUS_CLS[status],
        selected && "ring-2 ring-primary",
      )}
      title={`${data.label} · ${data.status}${data.backup ? ` · backup ${data.backup}` : ""}`}
    >
      <Handle type="target" position={Position.Left} className="!h-1.5 !w-1.5 !border-0 !bg-muted-foreground/60" />
      <div className="flex items-center gap-1.5">
        <span className={cn("h-2 w-2 shrink-0 rounded-full", DOT_CLS[status])} aria-hidden />
        <span className="truncate text-xs font-semibold text-foreground">{data.label}</span>
      </div>
      <span className="truncate text-[10px] text-muted-foreground">
        {[data.role, data.platform].filter(Boolean).join(" · ") || "—"}
        {data.backup === "failed" ? <span className="ml-1 text-destructive">backup failed</span> : null}
      </span>
      <Handle type="source" position={Position.Right} className="!h-1.5 !w-1.5 !border-0 !bg-muted-foreground/60" />
    </div>
  );
}

function SiteNode({ data }: NodeProps<Node<SiteNodeData>>) {
  return (
    <div className="h-full w-full rounded-xl border border-dashed border-primary/40 bg-primary/[0.03]">
      <div className="flex items-center justify-between px-3 pt-2 text-xs">
        <span className="font-semibold text-foreground">{data.label}</span>
        <span className="text-muted-foreground">
          {data.kind ? `${data.kind} · ` : ""}
          {data.count} device{data.count === 1 ? "" : "s"}
        </span>
      </div>
    </div>
  );
}

const nodeTypes: NodeTypes = { device: DeviceNode, site: SiteNode };

export function NetworkMap({ topology }: { topology: Topology }) {
  const router = useRouter();
  const { resolvedTheme } = useTheme();
  const { nodes, edges } = React.useMemo(() => layoutTopology(topology), [topology]);

  return (
    <ReactFlow
      nodes={nodes}
      edges={edges}
      nodeTypes={nodeTypes}
      fitView
      fitViewOptions={{ padding: 0.15 }}
      minZoom={0.1}
      maxZoom={2}
      nodesConnectable={false}
      colorMode={resolvedTheme === "light" ? "light" : "dark"}
      onNodeClick={(_, n) => {
        if (n.type === "device") router.push(`/devices/${n.id}`);
      }}
      proOptions={{ hideAttribution: true }}
    >
      <Background gap={24} size={1} />
      <Controls showInteractive={false} />
      <MiniMap
        pannable
        zoomable
        nodeColor={(n) => (n.type === "site" ? "transparent" : (n.data as DeviceNodeData).status === "down" ? "#e5484d" : (n.data as DeviceNodeData).status === "up" ? "#30a46c" : "#888")}
        className="!bg-card"
      />
    </ReactFlow>
  );
}
