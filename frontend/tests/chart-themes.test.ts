import { readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

import {
  barOption,
  CHART_THEMES,
  chartTheme,
  donutOption,
  heatmapOption,
  lineOption,
  networkGraphOption,
  palette,
  resolveTheme,
  severityColor,
  sparklineOption,
} from "@/lib/charts";
import { designFromCookie, DESIGN_INIT_SCRIPT, DESIGNS } from "@/lib/theme";

type AnyRec = Record<string, unknown>;
const series = (o: AnyRec) => o.series as AnyRec[];

const meridian = chartTheme("meridian", "light");
const meridianDark = chartTheme("meridian", "dark");
const aurora = chartTheme("aurora", "light");

describe("chart design themes", () => {
  it("keeps every categorical palette in its fixed, approved order", () => {
    expect(CHART_THEMES.meridian.light.categorical).toEqual(["#009683", "#e0673a", "#4f6bd8", "#b88400", "#b0527e"]);
    expect(CHART_THEMES.meridian.dark.categorical).toEqual(["#10a18b", "#e06f43", "#6f86e6", "#b58a00", "#c7689a"]);
    expect(CHART_THEMES.aurora.light.categorical).toEqual(["#5b4ee6", "#dc6a22", "#0e9f7e", "#b88400", "#d9467a"]);
    expect(CHART_THEMES.meridian.light.sequential).toEqual(["#eef4ef", "#bfe0d6", "#7fc3b3", "#2e9c89", "#0b5f59"]);
    expect(CHART_THEMES.meridian.light.severity).toEqual({ critical: "#b3261e", high: "#c2502a", medium: "#b88400", low: "#7c7a70" });
    // series take palette slots in order and never re-sort (colour follows the entity)
    const o = barOption({ categories: ["a"], series: ["s1", "s2", "s3"].map((name) => ({ name, data: [1] })) }, meridian) as AnyRec;
    expect(series(o).map((s) => (s.itemStyle as AnyRec).color)).toEqual(meridian.categorical.slice(0, 3));
    expect(o.color).toEqual(meridian.categorical);
  });

  it("defines a complete token set for all four design × mode combinations", () => {
    for (const d of DESIGNS) {
      for (const m of ["light", "dark"] as const) {
        const t = chartTheme(d, m);
        expect(t.design).toBe(d);
        expect(t.mode).toBe(m);
        expect(t.categorical).toHaveLength(5);
        expect(t.sequential).toHaveLength(5);
        expect(new Set(t.categorical).size).toBe(5);
        for (const v of Object.values(t.tokens)) expect(v === "" || v === undefined).toBe(false);
      }
    }
  });

  it("builds different options per design theme", () => {
    const input = { items: [{ name: "a", value: 1 }, { name: "b", value: 2 }] };
    const a = donutOption(input, aurora) as AnyRec;
    const m = donutOption(input, meridian) as AnyRec;
    expect((a.tooltip as AnyRec).backgroundColor).toBe("#ffffff");
    expect((m.tooltip as AnyRec).backgroundColor).toBe("#fffdf8");
    expect((m.tooltip as AnyRec).borderColor).toBe("#e6dfd0");
    expect(String((m.tooltip as AnyRec).extraCssText)).toContain("border-radius:12px");
    expect(((m.textStyle as AnyRec).fontFamily as string).startsWith("'IBM Plex Sans'")).toBe(true);
    expect(((a.textStyle as AnyRec).fontFamily as string).startsWith("Manrope")).toBe(true);
    expect((series(m)[0].data as AnyRec[]).map((d) => (d.itemStyle as AnyRec).color)).toEqual(["#009683", "#e0673a"]);
    const label = series(m)[0].label as AnyRec;
    expect(label.fontFamily).toBe(meridian.fonts.display);

    const la = lineOption({ categories: ["1", "2"], series: [{ name: "x", data: [1, 2] }] }, aurora) as AnyRec;
    const lm = lineOption({ categories: ["1", "2"], series: [{ name: "x", data: [1, 2] }] }, meridianDark) as AnyRec;
    expect(((la.xAxis as AnyRec).axisLine as AnyRec).lineStyle).toEqual({ color: "#e4e5f1" });
    expect(((lm.xAxis as AnyRec).axisLine as AnyRec).lineStyle).toEqual({ color: "#3a332a" });
    expect(((lm.yAxis as AnyRec).axisLabel as AnyRec).color).toBe(meridianDark.tokens.label);

    const h = heatmapOption({ xLabels: ["00"], yLabels: ["Mon"], cells: [[0, 0, 1]] }, meridian) as AnyRec;
    expect(((h.visualMap as AnyRec).inRange as AnyRec).color).toEqual(meridian.sequential);

    const sa = sparklineOption({ labels: ["a"], data: [1], name: "n" }, aurora) as AnyRec;
    const sm = sparklineOption({ labels: ["a"], data: [1], name: "n" }, meridian) as AnyRec;
    expect((series(sa)[0].lineStyle as AnyRec).color).not.toBe((series(sm)[0].lineStyle as AnyRec).color);
  });

  it("maps severities and graph status through the theme", () => {
    expect(severityColor("critical", meridian)).toBe("#b3261e");
    expect(severityColor("HIGH", meridian)).toBe("#c2502a");
    expect(severityColor("unknown", meridian)).toBe("#7c7a70");
    expect(severityColor("high", "light")).toBe(palette("light")[1]);
    const topo = {
      sites: [{ id: "s1", name: "Delhi" }],
      nodes: [{ id: "a", label: "a", site_id: "s1", role: null, platform: null, status: "down", backup: null }],
      edges: [],
    };
    const g = series(networkGraphOption(topo, meridian) as AnyRec)[0];
    expect(((g.data as AnyRec[])[0].itemStyle as AnyRec).color).toBe(meridian.status.danger);
  });

  it("treats a bare mode as Aurora (backwards compatible)", () => {
    expect(resolveTheme("dark")).toBe(CHART_THEMES.aurora.dark);
    const input = { categories: ["a"], series: [{ name: "n", data: [1] }] };
    expect(JSON.stringify(barOption(input, "light"))).toBe(JSON.stringify(barOption(input, aurora)));
  });

  it("keeps chart builders free of hard-coded colours", () => {
    const src = readFileSync(join(__dirname, "..", "lib", "charts.ts"), "utf8");
    const builders = src.slice(src.indexOf("/** Hex (#rrggbb) + alpha"));
    expect(builders.match(/#[0-9a-fA-F]{3,6}\b/g) ?? []).toEqual([]);
  });
});

describe("design persistence", () => {
  it("reads the design cookie", () => {
    expect(designFromCookie("a=1; nom-design=meridian; b=2")).toBe("meridian");
    expect(designFromCookie("nom-design=bogus")).toBeNull();
    expect(designFromCookie(undefined)).toBeNull();
  });

  it("applies the stored design before paint (localStorage, then cookie, then default)", () => {
    const run = () => new Function(DESIGN_INIT_SCRIPT)();
    window.localStorage.clear();
    document.cookie = "nom-design=; max-age=0; path=/";
    run();
    expect(document.documentElement.getAttribute("data-design")).toBe("aurora");
    document.cookie = "nom-design=meridian; path=/";
    run();
    expect(document.documentElement.getAttribute("data-design")).toBe("meridian");
    window.localStorage.setItem("nom.design", "aurora");
    run();
    expect(document.documentElement.getAttribute("data-design")).toBe("aurora");
    window.localStorage.setItem("nom.design", "nonsense");
    run();
    expect(document.documentElement.getAttribute("data-design")).toBe("meridian");
    window.localStorage.clear();
    document.cookie = "nom-design=; max-age=0; path=/";
  });
});
