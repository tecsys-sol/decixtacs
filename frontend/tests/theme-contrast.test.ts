import { readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

import { CHART_THEMES } from "@/lib/charts";
import { contrastRatio, hexToRgb, hslTripletToRgb, pairContrast, TEXT_PAIRS, themeTokens, type ThemeKey } from "@/lib/contrast";

const css = readFileSync(join(__dirname, "..", "app", "globals.css"), "utf8");
const themes = themeTokens(css);
const KEYS = Object.keys(themes) as ThemeKey[];

describe("WCAG contrast of design tokens (app/globals.css)", () => {
  it("parses all four design × mode combinations", () => {
    expect(KEYS).toEqual(["aurora-light", "aurora-dark", "meridian-light", "meridian-dark"]);
    // Meridian tokens really are different from Aurora's
    expect(themes["meridian-light"].background).not.toBe(themes["aurora-light"].background);
    expect(themes["meridian-dark"].background).not.toBe(themes["aurora-dark"].background);
    expect(hslTripletToRgb(themes["meridian-light"].background)).toEqual(hexToRgb("#f6f2ea"));
    expect(hslTripletToRgb(themes["meridian-light"].primary)).toEqual(hexToRgb("#0b5f59"));
  });

  it("computes WCAG ratios correctly", () => {
    expect(contrastRatio(hexToRgb("#000000"), hexToRgb("#ffffff"))).toBeCloseTo(21, 5);
    expect(contrastRatio(hexToRgb("#777777"), hexToRgb("#ffffff"))).toBeCloseTo(4.48, 2);
  });

  for (const key of KEYS) {
    it(`every text pair is at least 4.5:1 in ${key}`, () => {
      const failures = TEXT_PAIRS.map(([fg, bg]) => ({ pair: `${fg} on ${bg}`, ratio: pairContrast(themes[key], fg, bg) })).filter((p) => p.ratio < 4.5);
      expect(failures).toEqual([]);
    });
  }

  it("chart text (axis labels, legends, tooltips) is at least 4.5:1 on the chart surface", () => {
    for (const design of Object.values(CHART_THEMES)) {
      for (const t of Object.values(design)) {
        const surface = hexToRgb(t.tokens.surface);
        for (const ink of [t.tokens.ink, t.tokens.ink2, t.tokens.label]) {
          expect(contrastRatio(hexToRgb(ink), surface), `${t.design}/${t.mode} ${ink}`).toBeGreaterThanOrEqual(4.5);
        }
      }
    }
  });

  it("categorical chart colours reach 3:1 against their card surface (graphical objects)", () => {
    for (const design of Object.values(CHART_THEMES)) {
      for (const t of Object.values(design)) {
        const surface = hexToRgb(t.tokens.surface);
        for (const c of t.categorical) expect(contrastRatio(hexToRgb(c), surface), `${t.design}/${t.mode} ${c}`).toBeGreaterThanOrEqual(3);
      }
    }
  });
});
