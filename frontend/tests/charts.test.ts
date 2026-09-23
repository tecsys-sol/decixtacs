import { describe, expect, it } from "vitest";

import { bucketSeries, countBy, dailySeries, dayHourMatrix, foldTop, histogram, peak } from "@/lib/aggregate";
import {
  barOption,
  CATEGORICAL,
  clusteredLayout,
  DIVERGING,
  divergingBarOption,
  donutOption,
  funnelOption,
  gaugeOption,
  heatmapOption,
  lineOption,
  networkGraphOption,
  SEQUENTIAL,
  sparklineOption,
  TOKENS,
} from "@/lib/charts";
import { reportPreview } from "@/lib/report-preview";

type AnyRec = Record<string, unknown>;
const series = (o: AnyRec) => o.series as AnyRec[];

describe("Aurora chart theme", () => {
  it("uses the approved categorical palette in fixed order", () => {
    expect(CATEGORICAL.light).toEqual(["#5b4ee6", "#dc6a22", "#0e9f7e", "#b88400", "#d9467a"]);
    expect(SEQUENTIAL.light).toEqual(["#f1f0fd", "#c9c3fb", "#8f85f0", "#5b4ee6", "#3326b8"]);
    expect(DIVERGING.light).toEqual({ added: "#2a78d6", removed: "#e34948" });
  });

  it("styles tooltips, animation and aria on every option", () => {
    const o = barOption({ categories: ["a"], series: [{ name: "n", data: [1] }] }, "light") as AnyRec;
    const tooltip = o.tooltip as AnyRec;
    expect(tooltip.backgroundColor).toBe("#ffffff");
    expect(tooltip.borderColor).toBe("#e4e5f1");
    expect(String(tooltip.extraCssText)).toContain("border-radius:10px");
    expect(o.animationDuration).toBe(1200);
    expect(o.animationEasing).toBe("cubicOut");
    expect(o.aria).toEqual({ enabled: true });
  });

  it("switches surface colours for dark mode", () => {
    const o = donutOption({ items: [{ name: "a", value: 1 }, { name: "b", value: 2 }] }, "dark") as AnyRec;
    expect((o.tooltip as AnyRec).backgroundColor).toBe(TOKENS.dark.surface);
    expect(((series(o)[0].itemStyle as AnyRec).borderColor as string).toLowerCase()).toBe("#1d1d36");
  });
});

describe("option builders", () => {
  it("builds a sparkline with a gradient area that fades to transparent", () => {
    const o = sparklineOption({ labels: ["d1", "d2"], data: [1, 2], name: "Devices", color: "#5b4ee6" }, "light") as AnyRec;
    const s = series(o)[0];
    expect(s.type).toBe("line");
    expect((s.lineStyle as AnyRec).width).toBe(2);
    const stops = ((s.areaStyle as AnyRec).color as AnyRec).colorStops as { color: string }[];
    expect(stops[0].color).toBe("rgba(91,78,230,0.2)");
    expect(stops[1].color).toBe("rgba(91,78,230,0)");
  });

  it("renders legends only for two or more series, and rounds only the outer stacked segment", () => {
    const single = barOption({ categories: ["a", "b"], series: [{ name: "One", data: [1, 2] }] }, "light") as AnyRec;
    expect((single.legend as AnyRec).show).toBe(false);
    const stacked = barOption(
      {
        categories: ["a"],
        series: [
          { name: "Changed", data: [1], stack: "s" },
          { name: "Failed", data: [2], stack: "s" },
        ],
      },
      "light",
    ) as AnyRec;
    expect((stacked.legend as AnyRec).show).not.toBe(false);
    const [first, last] = series(stacked);
    expect((first.itemStyle as AnyRec).borderRadius).toBe(0);
    expect((last.itemStyle as AnyRec).borderRadius).toEqual([4, 4, 0, 0]);
    // surface-coloured border gives the 2px gap between segments
    expect((last.itemStyle as AnyRec).borderColor).toBe("#ffffff");
  });

  it("puts horizontal bars on a reversed category y-axis", () => {
    const o = barOption({ categories: ["top", "second"], series: [{ name: "n", data: [9, 3] }], horizontal: true }, "light") as AnyRec;
    expect((o.yAxis as AnyRec).type).toBe("category");
    expect((o.yAxis as AnyRec).inverse).toBe(true);
    expect((series(o)[0].itemStyle as AnyRec).borderRadius).toEqual([0, 4, 4, 0]);
  });

  it("plots removed lines below the axis in the diverging pair", () => {
    const o = divergingBarOption({ categories: ["c1", "c2"], added: [5, 1], removed: [3, 0] }, "light") as AnyRec;
    const [added, removed] = series(o);
    expect(added.data).toEqual([5, 1]);
    expect(removed.data).toEqual([-3, -0]);
    expect((added.itemStyle as AnyRec).color).toBe("#2a78d6");
    expect((removed.itemStyle as AnyRec).color).toBe("#e34948");
  });

  it("builds arc and ring gauges and shows a dash for missing values", () => {
    const arc = series(gaugeOption({ value: 91.4, label: "+2.1" }, "light") as AnyRec)[0];
    expect(arc.startAngle).toBe(210);
    expect((arc.data as AnyRec[])[0]).toEqual({ value: 91.4, name: "+2.1" });
    const ring = series(gaugeOption({ value: null, variant: "ring" }, "light") as AnyRec)[0];
    expect(ring.startAngle).toBe(90);
    const fmt = (ring.detail as AnyRec).formatter as (v: number) => string;
    expect(fmt(0)).toBe("—");
  });

  it("builds a donut with a centre total and a rose variant", () => {
    const donut = series(donutOption({ items: [{ name: "Juniper", value: 3 }, { name: "Arista", value: 1 }], centerValue: "4", centerLabel: "devices" }, "light") as AnyRec)[0];
    expect(donut.radius).toEqual(["52%", "78%"]);
    expect(donut.padAngle).toBe(2);
    expect((donut.data as AnyRec[]).map((d) => (d.itemStyle as AnyRec).color)).toEqual(["#5b4ee6", "#dc6a22"]);
    const rose = series(donutOption({ items: [{ name: "a", value: 1 }], rose: true }, "light") as AnyRec)[0];
    expect(rose.roseType).toBe("radius");
  });

  it("stacks area lines and formats the axis", () => {
    const o = lineOption({ categories: ["00", "01"], series: [{ name: "A", data: [1, 2] }, { name: "B", data: [3, 4] }], area: true, stacked: true }, "light") as AnyRec;
    expect(series(o).every((s) => s.stack === "total" && s.areaStyle)).toBe(true);
  });

  it("maps heatmap magnitude to the sequential indigo ramp", () => {
    const o = heatmapOption({ xLabels: ["00"], yLabels: ["Mon"], cells: [[0, 0, 4]] }, "light") as AnyRec;
    expect(((o.visualMap as AnyRec).inRange as AnyRec).color).toEqual(SEQUENTIAL.light);
    expect((o.visualMap as AnyRec).max).toBe(4);
  });

  it("builds a funnel in one hue", () => {
    const s = series(funnelOption([{ name: "Draft", value: 4 }, { name: "Approved", value: 2 }], "light") as AnyRec)[0];
    expect(s.type).toBe("funnel");
    expect((s.data as AnyRec[]).length).toBe(2);
  });

  it("lays out the topology deterministically and animates healthy links", () => {
    const topo = {
      sites: [{ id: "s1", name: "Frankfurt" }, { id: "s2", name: "Mumbai" }],
      nodes: [
        { id: "a", label: "a", site_id: "s1", role: null, platform: null, status: "up", backup: null },
        { id: "b", label: "b", site_id: "s1", role: null, platform: null, status: "down", backup: null },
        { id: "c", label: "c", site_id: "s2", role: null, platform: null, status: "up", backup: null },
      ],
      edges: [
        { id: "e1", source: "a", target: "b", label: "ae0", speed_mbps: 100000, status: "down" },
        { id: "e2", source: "a", target: "c", label: "xe-0/0/1", speed_mbps: 10000, status: "up" },
      ],
    };
    expect([...clusteredLayout(topo).entries()]).toEqual([...clusteredLayout(topo).entries()]);
    const o = networkGraphOption(topo, "light") as AnyRec;
    const [graph, flows] = series(o);
    expect(graph.type).toBe("graph");
    expect((graph.categories as AnyRec[]).map((c) => c.name)).toEqual(["Frankfurt", "Mumbai"]);
    const nodes = graph.data as AnyRec[];
    expect((nodes.find((n) => n.id === "b")!.itemStyle as AnyRec).color).toBe("#e0452b");
    expect(flows.type).toBe("lines");
    expect((flows.data as unknown[]).length).toBe(1);
    const force = series(networkGraphOption(topo, "light", "force") as AnyRec);
    expect(force).toHaveLength(1);
    expect(force[0].layout).toBe("force");
    expect(force[0].roam).toBe(true);
  });
});

describe("aggregation helpers", () => {
  const now = new Date(2026, 8, 23, 14, 30).getTime();
  const iso = (hoursAgo: number) => new Date(now - hoursAgo * 3_600_000).toISOString();

  it("buckets rows per hour and group, ignoring rows outside the window", () => {
    const rows = [
      { t: iso(0.2), k: "pass" },
      { t: iso(0.3), k: "fail" },
      { t: iso(3.1), k: "pass" },
      { t: iso(30), k: "pass" },
    ];
    const s = bucketSeries(rows, (r) => r.t, "24h", now, { group: (r) => r.k, groupOrder: ["pass", "fail"] });
    expect(s.labels).toHaveLength(24);
    expect(s.labels[23]).toBe("14:00");
    expect(s.counted).toBe(3);
    expect(s.series.map((x) => x.name)).toEqual(["pass", "fail"]);
    expect(s.series[0].data[23]).toBe(1);
    expect(s.series[0].data.reduce((a, b) => a + b, 0)).toBe(2);
    expect(peak(s.series)).toBe(2);
  });

  it("builds daily totals and weekday x hour cells", () => {
    const rows = [{ t: iso(1) }, { t: iso(2) }, { t: iso(25) }];
    const d = dailySeries(rows, (r) => r.t, 7, now);
    expect(d.data.reduce((a, b) => a + b, 0)).toBe(3);
    expect(d.data[6]).toBe(2);
    const m = dayHourMatrix(rows.map((r) => r.t), now, 7);
    expect(m.cells).toHaveLength(7 * 24);
    expect(m.counted).toBe(3);
  });

  it("counts, folds and bins", () => {
    expect(countBy(["a", "b", "a", null], (x) => x)).toEqual([
      { name: "a", value: 2 },
      { name: "b", value: 1 },
      { name: "Unknown", value: 1 },
    ]);
    expect(foldTop([{ name: "a", value: 5 }, { name: "b", value: 3 }, { name: "c", value: 1 }], 2)).toEqual([
      { name: "a", value: 5 },
      { name: "Other", value: 4 },
    ]);
    expect(histogram([0, 55, 100, 99.9], 10).data).toEqual([1, 0, 0, 0, 0, 1, 0, 0, 0, 2]);
  });

  it("derives a report preview from text and numeric columns", () => {
    const p = reportPreview({
      title: "t",
      columns: ["Device", "Changes", "Last change"],
      rows: [
        ["edge1", 3, "2026-09-01"],
        ["edge2", 5, "2026-09-02"],
        ["edge1", 1, "2026-09-03"],
      ],
      start: "",
      end: "",
    });
    expect(p?.valueLabel).toBe("Changes");
    expect(p?.items).toEqual([
      { name: "edge2", value: 5 },
      { name: "edge1", value: 4 },
    ]);
  });
});
