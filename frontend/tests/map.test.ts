import { describe, expect, it } from "vitest";

import { aggregateSites, linkWidth, siteGraphOption } from "@/lib/charts";
import { chartTheme } from "@/lib/charts";

const topo = {
  sites: [
    { id: "fra", name: "Frankfurt", lat: 50.1, lon: 8.7 },
    { id: "ams", name: "Amsterdam", lat: 52.4, lon: 4.9 },
  ],
  nodes: [
    { id: "a", label: "mx-fra", site_id: "fra", role: null, platform: null, status: "up", backup: null },
    { id: "b", label: "mx-fra2", site_id: "fra", role: null, platform: null, status: "down", backup: null },
    { id: "c", label: "mx-ams", site_id: "ams", role: null, platform: null, status: "up", backup: null },
    { id: "d", label: "lab", site_id: null, role: null, platform: null, status: "unknown", backup: null },
  ],
  edges: [
    { id: "1", source: "a", target: "b", label: "et-0/0/0 - et-0/0/0", speed_mbps: 100_000, status: "up", kind: "subnet" },
    { id: "2", source: "a", target: "c", label: "et-0/0/1 - et-0/0/0", speed_mbps: 100_000, status: "up", kind: "subnet" },
    { id: "3", source: "b", target: "c", label: "ae1", speed_mbps: 20_000, status: "down", kind: "description" },
  ],
};

describe("site overview", () => {
  it("folds devices into sites and links into bundles between them", () => {
    const { sites, links } = aggregateSites(topo);
    const fra = sites.find((s) => s.id === "fra")!;
    expect(fra).toMatchObject({ devices: 2, down: 1, internal: 1 });
    expect(sites.find((s) => s.name === "No site")?.devices).toBe(1);
    expect(links).toHaveLength(1);
    expect(links[0]).toMatchObject({ count: 2, capacity: 120_000, down: 1, inferred: 1 });
  });

  it("places sites by coordinates and draws one line per site pair", () => {
    const opt = siteGraphOption(aggregateSites({ ...topo, nodes: topo.nodes.slice(0, 3) }), chartTheme("aurora", "light"));
    const series = (opt.series as { data: { value: number[]; siteId: string }[]; links: unknown[] }[])[0];
    const fra = series.data.find((d) => d.siteId === "fra")!.value;
    const ams = series.data.find((d) => d.siteId === "ams")!.value;
    expect(fra[1]).toBeGreaterThan(ams[1]); // Frankfurt is south of Amsterdam
    expect(fra[0]).toBeGreaterThan(ams[0]); // and east
    expect(series.links).toHaveLength(1);
  });

  it("scales line width with capacity", () => {
    expect(linkWidth(100_000)).toBeGreaterThan(linkWidth(10_000));
    expect(linkWidth(10_000)).toBeGreaterThan(linkWidth(1_000));
    expect(linkWidth(null)).toBeGreaterThan(0);
  });
});
