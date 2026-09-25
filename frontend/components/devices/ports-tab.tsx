"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Boxes, Cable, ExternalLink, Image as ImageIcon, Network, PlugZap, Server, Settings2, Unplug } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import * as React from "react";

import { Chart, useChartTheme } from "@/components/charts/chart";
import { ChartBody, ChartCard } from "@/components/common/chart-card";
import { EmptyState } from "@/components/common/empty-state";
import { ErrorState } from "@/components/common/error-state";
import { Field } from "@/components/common/field";
import { KpiTile } from "@/components/common/kpi-tile";
import { Badge, type BadgeVariant } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { useAuth } from "@/hooks/use-auth";
import { useOnOpen } from "@/hooks/use-reset";
import { toast } from "@/hooks/use-toast";
import { api, errorMessage } from "@/lib/api";
import type { Device } from "@/lib/types";
import { cn } from "@/lib/utils";

import { buildConnections, connectionsOption } from "./ports/connections";
import { Faceplate } from "./ports/faceplate";
import { lagColors as makeLagColors, peerLabel, type ConfigInterface, type DevicePorts, type Peer, type Port } from "./ports/types";

const STATE: Record<Port["state"], { label: string; variant: BadgeVariant }> = {
  up: { label: "In use", variant: "success" },
  lag: { label: "LAG member", variant: "info" },
  disabled: { label: "Disabled", variant: "danger" },
  unused: { label: "Unused", variant: "muted" },
};

const SOURCE_LABEL: Record<Peer["source"], string> = {
  cable: "NetBox cable",
  subnet: "shared point-to-point subnet",
  bgp: "BGP neighbour",
  description: "named in the description",
};

function FrontPhoto({ deviceId, model }: { deviceId: string; model: string }) {
  const q = useQuery({
    queryKey: ["device", deviceId, "front-image", model],
    queryFn: async () => URL.createObjectURL(await api.get<Blob>(`/devices/${deviceId}/front-image`, undefined, { responseType: "blob" })),
    staleTime: Infinity,
    retry: false,
  });
  React.useEffect(() => () => (q.data ? URL.revokeObjectURL(q.data) : undefined), [q.data]);
  if (q.isLoading) return <Skeleton className="h-24 w-full" />;
  if (!q.data) return null;
  return (
    <figure className="grid gap-1.5">
      {/* eslint-disable-next-line @next/next/no-img-element -- blob URL of an authenticated download */}
      <img src={q.data} alt={`Front panel photo of ${model}`} className="w-full rounded-md border bg-black/80 object-contain" />
      <figcaption className="flex items-center gap-1.5 text-[11px] text-muted-foreground">
        <ImageIcon className="h-3 w-3" /> Front panel photo · NetBox devicetype-library (CC0). Port numbering on the chassis can differ from interface names.
      </figcaption>
    </figure>
  );
}

function ModelDialog({ open, onOpenChange, device, current }: { open: boolean; onOpenChange: (o: boolean) => void; device: Device; current: DevicePorts | undefined }) {
  const qc = useQueryClient();
  const [model, setModel] = React.useState("");
  const [vendor, setVendor] = React.useState("");
  useOnOpen(open, () => {
    setModel(current?.model ?? "");
    setVendor(current?.vendor ?? "");
  });
  const save = useMutation({
    mutationFn: () => api.put(`/devices/${device.id}/device-type`, { model: model.trim(), vendor: vendor.trim() || null }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["device", device.id, "ports"] });
      toast.success("Device type set");
      onOpenChange(false);
    },
    onError: (e) => toast.error("Model not found", errorMessage(e)),
  });
  const clear = useMutation({
    mutationFn: () => api.delete(`/devices/${device.id}/device-type`),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["device", device.id, "ports"] });
      onOpenChange(false);
    },
  });
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Device model for the port view</DialogTitle>
          <DialogDescription>
            Looked up in the NetBox devicetype-library, e.g. <code>MX204</code>, <code>QFX5120-48Y</code>, <code>DCS-7280CR3-32P4</code>. Normally this comes from
            NetBox; set it here when NetBox has no or a different model name.
          </DialogDescription>
        </DialogHeader>
        <form
          className="grid gap-3"
          onSubmit={(e) => {
            e.preventDefault();
            if (model.trim()) save.mutate();
          }}
        >
          <Field label="Model" htmlFor="dt-model" required>
            <Input id="dt-model" value={model} onChange={(e) => setModel(e.target.value)} placeholder="MX204" className="font-mono" autoComplete="off" />
          </Field>
          <Field label="Vendor" htmlFor="dt-vendor" hint="juniper, arista, cisco, fortinet, mikrotik, sophos, nokia …">
            <Input id="dt-vendor" value={vendor} onChange={(e) => setVendor(e.target.value)} placeholder="juniper" autoComplete="off" />
          </Field>
          <DialogFooter>
            {current?.model_source === "override" ? (
              <Button type="button" variant="ghost" loading={clear.isPending} onClick={() => clear.mutate()}>
                Use NetBox model
              </Button>
            ) : null}
            <Button type="submit" disabled={!model.trim()} loading={save.isPending}>
              Look up &amp; save
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

function PeerLine({ p }: { p: Peer }) {
  const label = peerLabel(p);
  return (
    <li className="flex flex-wrap items-baseline gap-x-2 py-0.5 text-xs">
      {p.device_id ? (
        <Link href={`/devices/${p.device_id}?tab=ports`} className="font-medium text-primary hover:underline">
          {p.kind === "bgp" ? `${label} (${p.hostname})` : label}
        </Link>
      ) : (
        <span className="font-medium">{label}</span>
      )}
      {p.address ? <span className="font-mono text-muted-foreground">{p.address}</span> : null}
      <span className="text-[10.5px] text-muted-foreground">{SOURCE_LABEL[p.source]}</span>
    </li>
  );
}

function IfaceBlock({ i }: { i: ConfigInterface }) {
  return (
    <div className="grid gap-1.5 rounded-md border bg-muted/20 p-2.5 text-xs">
      <div className="flex flex-wrap items-center gap-1.5">
        <span className="font-mono font-semibold">{i.name}</span>
        {i.disabled ? <Badge variant="danger">disable</Badge> : null}
        {i.inactive ? <Badge variant="warning">inactive</Badge> : null}
        {i.mtu ? <Badge variant="muted">MTU {i.mtu}</Badge> : null}
        {i.speed ? <Badge variant="muted">speed {i.speed}</Badge> : null}
        {i.protocols.map((p) => (
          <Badge key={p} variant="secondary">
            {p}
          </Badge>
        ))}
      </div>
      {i.description ? <p>{i.description}</p> : null}
      {i.units.length ? (
        <table className="w-full">
          <thead className="text-left text-[10.5px] uppercase tracking-wide text-muted-foreground">
            <tr>
              <th className="py-0.5 font-medium">Unit</th>
              <th className="py-0.5 font-medium">VLAN</th>
              <th className="py-0.5 font-medium">Addresses / VLANs</th>
            </tr>
          </thead>
          <tbody>
            {i.units.map((u) => (
              <tr key={u.name} className={cn("border-t align-top", u.disabled && "opacity-50")}>
                <td className="py-1 pr-2 font-mono">{u.name}</td>
                <td className="py-1 pr-2 font-mono">{u.vlan ?? "—"}</td>
                <td className="py-1">
                  {u.description ? <p className="text-muted-foreground">{u.description}</p> : null}
                  {u.addresses.map((a) => (
                    <p key={a} className="font-mono">
                      {a}
                    </p>
                  ))}
                  {u.switching ? (
                    <p>
                      {u.switching.mode ?? "switching"} {u.switching.vlans?.length ? <span className="font-mono">{u.switching.vlans.join(", ")}</span> : null}
                    </p>
                  ) : null}
                  {u.vrf ? <p className="text-muted-foreground">VRF {u.vrf}</p> : null}
                  {u.protocols.length ? <p className="text-muted-foreground">{u.protocols.join(" · ")}</p> : null}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : null}
    </div>
  );
}

function PortDetail({ port, lag, lagColor }: { port: Port | null; lag: ConfigInterface | null; lagColor?: string }) {
  if (!port)
    return (
      <div className="grid h-full place-items-center p-6 text-center text-sm text-muted-foreground">
        <div>
          <PlugZap className="mx-auto mb-2 h-6 w-6" />
          Click a port on the front panel or in the map to see its configuration and what it connects to.
        </div>
      </div>
    );
  const bgp = port.peers.filter((p) => p.kind === "bgp");
  const other = port.peers.filter((p) => p.kind !== "bgp");
  return (
    <div className="grid gap-3 p-4" data-testid="port-detail">
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-mono text-base font-semibold">{port.name}</span>
        <Badge variant={STATE[port.state].variant}>{STATE[port.state].label}</Badge>
        {port.speed ? <Badge variant="muted">{port.speed}</Badge> : null}
        {port.type ? <span className="font-mono text-[11px] text-muted-foreground">{port.type}</span> : null}
        {port.mgmt ? <Badge variant="info">management</Badge> : null}
      </div>
      {port.description ? <p className="text-sm">{port.description}</p> : null}
      {port.lag ? (
        <p className="flex items-center gap-2 text-sm">
          <span className="h-3 w-3 rounded-sm" style={{ backgroundColor: lagColor }} aria-hidden />
          Member of <span className="font-mono font-semibold">{port.lag}</span>
          {lag?.description ? <span className="text-muted-foreground">· {lag.description}</span> : null}
        </p>
      ) : null}
      {port.channels.length ? <p className="text-xs text-muted-foreground">Channelised: {port.channels.join(", ")}</p> : null}
      {other.length ? (
        <div>
          <p className="mb-1 flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
            <Cable className="h-3.5 w-3.5" /> Connected to
          </p>
          <ul>
            {other.map((p, i) => (
              <PeerLine key={i} p={p} />
            ))}
          </ul>
        </div>
      ) : null}
      {bgp.length ? (
        <details open={bgp.length <= 8}>
          <summary className="cursor-pointer text-xs font-semibold uppercase tracking-wide text-muted-foreground">
            {port.bgp_total > bgp.length ? `${bgp.length} of ${port.bgp_total}` : bgp.length} BGP neighbour{bgp.length === 1 ? "" : "s"} on this port
          </summary>
          <ul className="mt-1 max-h-56 overflow-y-auto scrollbar-thin">
            {bgp.map((p, i) => (
              <PeerLine key={i} p={p} />
            ))}
          </ul>
        </details>
      ) : null}
      {[...port.interfaces, ...(lag ? [lag] : [])].map((i) => (
        <IfaceBlock key={i.name} i={i} />
      ))}
      {port.state === "unused" ? <p className="text-sm text-muted-foreground">Nothing configured on this port.</p> : null}
    </div>
  );
}

export function PortsTab({ device }: { device: Device }) {
  const { can } = useAuth();
  const theme = useChartTheme();
  const router = useRouter();
  const q = useQuery({ queryKey: ["device", device.id, "ports"], queryFn: () => api.get<DevicePorts>(`/devices/${device.id}/ports`) });
  const [selected, setSelected] = React.useState<string | null>(null);
  const [highlight, setHighlight] = React.useState<Set<string> | null>(null);
  const [modelOpen, setModelOpen] = React.useState(false);
  const [onlyUsed, setOnlyUsed] = React.useState(true);
  const data = q.data;
  const lagColors = React.useMemo(() => makeLagColors(data?.ports ?? []), [data]);
  const graph = React.useMemo(() => (data ? buildConnections(data, lagColors) : null), [data, lagColors]);
  const option = React.useMemo(() => (graph ? connectionsOption(graph, theme) : null), [graph, theme]);

  if (q.isLoading) return <Skeleton className="h-[70vh]" />;
  if (q.error || !data) return <ErrorState error={q.error} onRetry={() => void q.refetch()} />;
  if (!data.has_config)
    return (
      <Card>
        <EmptyState icon={Unplug} title="No configuration backed up yet" description="The port view is built from the device's configuration. Run a backup first." />
      </Card>
    );

  const port = data.ports.find((p) => p.name === selected) ?? null;
  const lag = port?.lag ? (data.lags.find((l) => l.name === port.lag) ?? null) : null;
  const dt = data.device_type;
  const rows = data.ports.filter((p) => !onlyUsed || p.state !== "unused");
  const select = (name: string) => setSelected((s) => (s === name ? null : name));

  return (
    <div className="grid gap-4">
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-5">
        <KpiTile label="Ports" value={data.summary.ports} icon={Boxes} sub={dt ? `${dt.manufacturer} ${dt.model}` : "from the configuration"} />
        <KpiTile label="In use" value={data.summary.up} icon={PlugZap} tone="success" delay={1} />
        <KpiTile label="Unused" value={data.summary.unused} icon={Unplug} delay={2} sub="free for new connections" />
        <KpiTile label="Disabled" value={data.summary.disabled} icon={Unplug} tone={data.summary.disabled ? "warning" : "default"} delay={3} />
        <KpiTile label="Neighbours" value={data.summary.peers} icon={Network} delay={4} sub={`${data.summary.lags} LAG${data.summary.lags === 1 ? "" : "s"}`} />
      </div>

      <Card className="overflow-hidden">
        <div className="flex flex-wrap items-center gap-3 border-b px-4 py-3">
          <Server className="h-4 w-4 text-muted-foreground" />
          <div className="min-w-0">
            <p className="font-display text-[15px] font-semibold">
              {dt ? `${dt.manufacturer} ${dt.model}` : data.model ? `${data.model} (not in the library)` : "Model unknown"}
            </p>
            <p className="text-xs text-muted-foreground">
              {dt
                ? `${dt.u_height}U · ${dt.airflow ?? "airflow n/a"} · ${dt.console_ports} console · ${dt.module_bays.length ? `${dt.module_bays.length} module bays · ` : ""}template from ${dt.source === "bundle" ? "the bundled library" : "GitHub"}`
                : "Ports are taken from the configuration. Set the model to use the vendor's front-panel layout."}
              {data.model_source ? ` · model from ${data.model_source === "inventory" ? "NetBox" : data.model_source === "rancid" ? "RANCID header" : "manual setting"}` : ""}
            </p>
          </div>
          <div className="ml-auto flex items-center gap-2">
            {dt?.library_url ? (
              <Button asChild variant="ghost" size="xs">
                <a href={dt.library_url} target="_blank" rel="noreferrer">
                  <ExternalLink /> Library entry
                </a>
              </Button>
            ) : null}
            {can("devices:write") ? (
              <Button variant="outline" size="xs" onClick={() => setModelOpen(true)}>
                <Settings2 /> {dt ? "Change model" : "Set model"}
              </Button>
            ) : null}
          </div>
        </div>
        <div className="grid gap-4 p-4">
          {dt?.has_front_image ? <FrontPhoto deviceId={device.id} model={dt.model} /> : null}
          <Faceplate
            ports={data.ports}
            vendor={dt?.manufacturer ?? data.device.vendor}
            model={dt?.model ?? data.model}
            uHeight={dt?.u_height ?? 1}
            lagColors={lagColors}
            selected={selected}
            onSelect={select}
            highlight={highlight}
          />
          <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-[11.5px] text-muted-foreground">
            <span className="inline-flex items-center gap-1.5"><span className="h-2.5 w-2.5 rounded-full bg-[#22c55e]" /> in use</span>
            <span className="inline-flex items-center gap-1.5"><span className="h-2.5 w-2.5 rounded-full bg-[#ef4444]" /> disabled</span>
            <span className="inline-flex items-center gap-1.5"><span className="h-2.5 w-2.5 rounded-full bg-[#3b414d]" /> unused</span>
            <span className="inline-flex items-center gap-1.5"><span className="h-2.5 w-2.5 rounded-full bg-[#fde68a]" /> neighbour known</span>
            {[...lagColors].map(([l, c]) => (
              <button
                key={l}
                type="button"
                className="inline-flex items-center gap-1.5 rounded px-1 hover:bg-muted"
                onMouseEnter={() => setHighlight(new Set(data.ports.filter((p) => p.lag === l).map((p) => p.name)))}
                onMouseLeave={() => setHighlight(null)}
              >
                <span className="h-2.5 w-2.5 rounded-sm" style={{ backgroundColor: c }} /> <span className="font-mono">{l}</span>
              </button>
            ))}
          </div>
        </div>
      </Card>

      <div className="grid gap-4 xl:grid-cols-[minmax(0,1.5fr)_minmax(340px,1fr)]">
        <ChartCard
          title="Connections"
          description={
            graph
              ? `Ports and LAGs with what is on the other end · ${graph.hidden ? `${graph.hidden} configured port(s) without a known neighbour not shown · ` : ""}drag to rearrange, scroll to zoom`
              : undefined
          }
        >
          <ChartBody empty={!graph || graph.nodes.length <= 1} emptyTitle="No neighbours found in the configuration" emptyIcon={Network} height={560}>
            {option ? (
              <Chart
                option={option}
                height={560}
                ariaLabel={`Connections of ${device.hostname}`}
                onEvents={{
                  click: (p) => {
                    const id = (p as { data?: { id?: string } }).data?.id ?? "";
                    const node = graph?.nodes.find((n) => n.id === id);
                    if (!node) return;
                    if (node.kind === "device" && node.device_id) router.push(`/devices/${node.device_id}?tab=ports`);
                    else if (node.ports[0]) setSelected(node.ports[0]);
                  },
                  mouseover: (p) => {
                    const id = (p as { data?: { id?: string } }).data?.id ?? "";
                    const node = graph?.nodes.find((n) => n.id === id);
                    if (node?.ports.length) setHighlight(new Set(node.ports));
                  },
                  mouseout: () => setHighlight(null),
                }}
              />
            ) : null}
          </ChartBody>
        </ChartCard>
        <Card className="max-h-[640px] overflow-y-auto scrollbar-thin">
          <PortDetail port={port} lag={lag} lagColor={port?.lag ? lagColors.get(port.lag) : undefined} />
        </Card>
      </div>

      <Card className="overflow-hidden">
        <div className="flex items-center justify-between border-b px-4 py-2.5">
          <p className="font-display text-[15px] font-semibold">Ports</p>
          <Checkbox label="Only configured ports" checked={onlyUsed} onCheckedChange={setOnlyUsed} />
        </div>
        <div className="overflow-x-auto">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Port</TableHead>
                <TableHead>Speed</TableHead>
                <TableHead>State</TableHead>
                <TableHead>Description</TableHead>
                <TableHead>LAG</TableHead>
                <TableHead>Addresses / VLANs</TableHead>
                <TableHead>Connected to</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {rows.map((p) => {
                const units = p.interfaces.flatMap((i) => i.units);
                const lagIf = p.lag ? data.lags.find((l) => l.name === p.lag) : null;
                const addr = [...units, ...(lagIf?.units ?? [])].flatMap((u) => [...u.addresses, ...(u.vlan ? [`vlan ${u.vlan}`] : []), ...(u.switching?.vlans ?? []).map((v) => `vlan ${v}`)]);
                const peers = p.peers.filter((x) => x.kind !== "bgp");
                const bgp = p.peers.filter((x) => x.kind === "bgp").length;
                return (
                  <TableRow key={p.name} className={cn("cursor-pointer", selected === p.name && "bg-accent/40")} onClick={() => select(p.name)}>
                    <TableCell className="whitespace-nowrap font-mono text-xs font-semibold">
                      {p.name}
                      {p.channels.length ? <span className="ml-1 font-sans font-normal text-muted-foreground">+{p.channels.length} ch</span> : null}
                    </TableCell>
                    <TableCell className="text-xs">{p.speed ?? "—"}</TableCell>
                    <TableCell>
                      <Badge variant={STATE[p.state].variant}>{STATE[p.state].label}</Badge>
                    </TableCell>
                    <TableCell className="max-w-[260px] truncate text-sm" title={p.description ?? undefined}>
                      {p.description ?? <span className="text-muted-foreground">—</span>}
                    </TableCell>
                    <TableCell>
                      {p.lag ? (
                        <span className="inline-flex items-center gap-1.5 font-mono text-xs">
                          <span className="h-2.5 w-2.5 rounded-sm" style={{ backgroundColor: lagColors.get(p.lag) }} />
                          {p.lag}
                        </span>
                      ) : (
                        "—"
                      )}
                    </TableCell>
                    <TableCell className="max-w-[220px] font-mono text-xs">
                      {addr.length ? (
                        <span title={addr.join("\n")}>
                          {addr.slice(0, 2).join(", ")}
                          {addr.length > 2 ? ` +${addr.length - 2}` : ""}
                        </span>
                      ) : (
                        "—"
                      )}
                    </TableCell>
                    <TableCell className="max-w-[280px] text-xs">
                      {peers.slice(0, 2).map((x, i) => (
                        <div key={i} className="truncate">
                          {x.device_id ? (
                            <Link href={`/devices/${x.device_id}?tab=ports`} className="text-primary hover:underline" onClick={(e) => e.stopPropagation()}>
                              {peerLabel(x)}
                            </Link>
                          ) : (
                            peerLabel(x)
                          )}
                        </div>
                      ))}
                      {bgp ? <div className="text-muted-foreground">{p.bgp_total > bgp ? p.bgp_total : bgp} BGP neighbour(s)</div> : null}
                      {!peers.length && !bgp ? <span className="text-muted-foreground">—</span> : null}
                    </TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
        </div>
        {data.unmatched.length ? (
          <p className="border-t px-4 py-2.5 text-xs text-muted-foreground">
            Also in the configuration but not on the {dt?.model ?? "chassis"} front panel (module / line-card ports):{" "}
            <span className="font-mono">{data.unmatched.map((u) => u.name).join(", ")}</span>
          </p>
        ) : null}
      </Card>

      <ModelDialog open={modelOpen} onOpenChange={setModelOpen} device={device} current={data} />
    </div>
  );
}
