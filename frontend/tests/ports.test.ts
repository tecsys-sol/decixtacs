import { describe, expect, it } from "vitest";

import { buildConnections, BGP_FOLD } from "@/components/devices/ports/connections";
import { layoutFaceplate, portNumber } from "@/components/devices/ports/layout";
import { lagColors, peerLabel, type DevicePorts, type Port } from "@/components/devices/ports/types";

function port(name: string, over: Partial<Port> = {}): Port {
  return {
    name,
    type: null,
    form: name.startsWith("et-") ? "qsfp" : name.startsWith("fxp") ? "rj45" : "sfp",
    speed: null,
    mgmt: name.startsWith("fxp"),
    in_template: true,
    state: "unused",
    description: null,
    lag: null,
    channels: [],
    interfaces: [],
    peers: [],
    bgp_total: 0,
    config_name: null,
    ...over,
  };
}

const mx204 = [
  port("fxp0"),
  ...[0, 1, 2, 3].map((i) => port(`et-0/0/${i}`)),
  ...[0, 1, 2, 3, 4, 5, 6, 7].map((i) => port(`xe-0/1/${i}`)),
];

describe("faceplate layout", () => {
  it("lays out an MX204: 4 QSFP in a row, 8 SFP+ in two rows, management on the right", () => {
    const l = layoutFaceplate(mx204, 1);
    const at = (n: string) => l.ports.find((p) => p.port.name === n)!;
    expect(l.ports).toHaveLength(13);
    expect(new Set(["et-0/0/0", "et-0/0/1", "et-0/0/2", "et-0/0/3"].map((n) => at(n).y)).size).toBe(1);
    // column-first numbering: 0 top, 1 bottom, 2 top ...
    expect(at("xe-0/1/0").y).toBeLessThan(at("xe-0/1/1").y);
    expect(at("xe-0/1/0").x).toBe(at("xe-0/1/1").x);
    expect(at("xe-0/1/2").x).toBeGreaterThan(at("xe-0/1/0").x);
    expect(at("fxp0").x).toBeGreaterThan(at("xe-0/1/7").x);
    expect(l.groups.map((g) => g.title)).toEqual([null, null, "MGMT"]);
    // ports stay inside the chassis
    for (const p of l.ports) expect(p.x + p.w).toBeLessThan(l.width);
  });

  it("wraps many ports without a device type into line-card rows", () => {
    const many = [0, 1, 2, 3].flatMap((fpc) => Array.from({ length: 24 }, (_, i) => port(`xe-${fpc}/0/${i}`, { in_template: false })));
    const l = layoutFaceplate(many, 1);
    expect(l.groups.map((g) => g.title)).toEqual(["slot 0/0", "slot 1/0", "slot 2/0", "slot 3/0"]);
    expect(new Set(l.groups.map((g) => g.y)).size).toBeGreaterThan(1);
    expect(l.height).toBeGreaterThan(96);
  });

  it("labels Arista-style ports by the changing number", () => {
    const l = layoutFaceplate([1, 2, 3, 4].map((i) => port(`Ethernet${i}/1`, { form: "qsfp" })), 1);
    expect(l.ports.map((p) => p.label)).toEqual(["1", "2", "3", "4"]);
  });

  it("numbers ports from their names", () => {
    expect(portNumber("xe-0/1/3")).toBe("3");
    expect(portNumber("et-0/0/1:2")).toBe("1");
    expect(portNumber("Ethernet12")).toBe("12");
  });
});

describe("connections", () => {
  const bgp = Array.from({ length: BGP_FOLD + 3 }, (_, i) => ({ kind: "bgp" as const, source: "bgp" as const, address: `185.1.0.${i + 10}`, asn: 64500 + i }));
  const data: DevicePorts = {
    device: { id: "d1", hostname: "mx204-a", vendor: "Juniper", platform: "junos" },
    device_type: null,
    model: null,
    vendor: null,
    model_source: null,
    has_config: true,
    ports: [
      port("et-0/0/0", { state: "up", peers: [{ kind: "device", source: "subnet", device_id: "d2", hostname: "mx204-b", interface: "et-0/0/0" }] }),
      port("et-0/0/1", { state: "up", peers: [{ kind: "device", source: "description", device_id: "d2", hostname: "mx204-b" }] }),
      port("xe-0/1/0", { state: "lag", lag: "ae0" }),
      port("xe-0/1/1", { state: "lag", lag: "ae0" }),
      port("xe-0/1/2", { state: "up" }),
    ],
    unmatched: [],
    lags: [
      { name: "ae0", description: "IX", disabled: false, inactive: false, lag: null, is_lag: true, mtu: null, speed: null, protocols: [], units: [], peers: bgp, bgp_total: bgp.length, members: ["xe-0/1/0", "xe-0/1/1"] },
    ],
    logical: [],
    summary: { ports: 5, configured: 5, up: 3, disabled: 0, unused: 0, lags: 1, peers: 2 },
  };

  it("merges a device reached over two ports and folds a crowded peering LAN", () => {
    const g = buildConnections(data, lagColors(data.ports));
    const dev = g.nodes.filter((n) => n.kind === "device");
    expect(dev).toHaveLength(1);
    expect(dev[0].ports).toEqual(["et-0/0/0", "et-0/0/1"]);
    const lag = g.nodes.find((n) => n.id === "lag:ae0")!;
    expect(lag.ports).toEqual(["xe-0/1/0", "xe-0/1/1"]);
    const fold = g.nodes.find((n) => n.kind === "bgp-group")!;
    expect(fold.label).toBe(`${BGP_FOLD + 3} BGP peers`);
    expect(g.nodes.some((n) => n.kind === "bgp")).toBe(false);
    expect(g.hidden).toBe(1); // xe-0/1/2 is configured but leads nowhere known
    expect(g.edges.find((e) => e.source === "port:et-0/0/1")?.dashed).toBe(true);
  });

  it("labels peers", () => {
    expect(peerLabel({ kind: "bgp", source: "bgp", address: "185.1.0.10", asn: 13335, name: "Cloudflare" })).toBe("AS13335 Cloudflare");
    expect(peerLabel({ kind: "device", source: "cable", hostname: "sw1", interface: "Ethernet1" })).toBe("sw1 · Ethernet1");
  });
});
