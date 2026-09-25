export type PortState = "up" | "lag" | "disabled" | "unused";
export type PortForm = "qsfp" | "qsfpdd" | "sfp" | "rj45" | "virtual";

export interface Peer {
  kind: "device" | "bgp" | "asn";
  source: "cable" | "subnet" | "bgp" | "description";
  device_id?: string;
  hostname?: string;
  interface?: string | null;
  address?: string;
  asn?: number | null;
  name?: string | null;
  group?: string | null;
  unit?: string;
}

export interface IfaceUnit {
  name: string;
  description: string | null;
  vlan: number | null;
  addresses: string[];
  switching: { mode?: string; vlans?: string[] } | null;
  protocols: string[];
  disabled: boolean;
  vrf: string | null;
}

export interface ConfigInterface {
  name: string;
  description: string | null;
  disabled: boolean;
  inactive: boolean;
  lag: string | null;
  is_lag: boolean;
  mtu: number | null;
  speed: string | null;
  protocols: string[];
  units: IfaceUnit[];
  peers: Peer[];
  bgp_total: number;
  lag_peers?: Peer[];
  members?: string[];
}

export interface Port {
  name: string;
  type: string | null;
  form: PortForm;
  speed: string | null;
  mgmt: boolean;
  in_template: boolean;
  state: PortState;
  description: string | null;
  lag: string | null;
  channels: string[];
  interfaces: ConfigInterface[];
  peers: Peer[];
  bgp_total: number;
  config_name: string | null;
}

export interface DeviceTypeInfo {
  manufacturer: string;
  model: string;
  slug: string;
  u_height: number;
  part_number: string | null;
  airflow: string | null;
  console_ports: number;
  power_ports: number;
  module_bays: string[];
  source: "bundle" | "github" | "cache";
  library_url: string | null;
  has_front_image: boolean;
}

export interface DevicePorts {
  device: { id: string; hostname: string; vendor: string | null; platform: string | null };
  device_type: DeviceTypeInfo | null;
  model: string | null;
  vendor: string | null;
  model_source: "inventory" | "override" | "rancid" | null;
  has_config: boolean;
  ports: Port[];
  unmatched: ConfigInterface[];
  lags: ConfigInterface[];
  logical: ConfigInterface[];
  summary: { ports: number; configured: number; up: number; disabled: number; unused: number; lags: number; peers: number };
}

/** Human label for a peer: device + interface, "AS13335 Cloudflare", or the neighbour address. */
export function peerLabel(p: Peer): string {
  if (p.kind === "device") return p.interface ? `${p.hostname} · ${p.interface}` : (p.hostname ?? "device");
  const as = p.asn ? `AS${p.asn}` : "";
  const name = p.name ? ` ${p.name}` : "";
  if (p.kind === "asn") return `${as}${name}`.trim();
  return `${as}${name}`.trim() || (p.address ?? "BGP neighbour");
}

export const LAG_COLORS = ["#7c3aed", "#0284c7", "#d97706", "#db2777", "#0d9488", "#4f46e5", "#c2410c", "#65a30d"];

export function lagColors(ports: Port[]): Map<string, string> {
  const lags = [...new Set(ports.map((p) => p.lag).filter((x): x is string => !!x))].sort((a, b) =>
    a.localeCompare(b, undefined, { numeric: true }),
  );
  return new Map(lags.map((l, i) => [l, LAG_COLORS[i % LAG_COLORS.length]]));
}
