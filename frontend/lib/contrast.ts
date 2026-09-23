/**
 * WCAG 2.x contrast helpers and a parser for the design tokens in app/globals.css. Used by
 * tests/theme-contrast.test.ts to prove every text pair meets 4.5:1 in all four
 * design × mode combinations.
 */

export type Rgb = [number, number, number];

/** "245 75.2% 60.4%" -> [r, g, b] (0..255) */
export function hslTripletToRgb(triplet: string): Rgb {
  const [h, s, l] = triplet
    .trim()
    .split(/\s+/)
    .map((p) => parseFloat(p));
  const S = s / 100;
  const L = l / 100;
  const k = (n: number) => (n + h / 30) % 12;
  const a = S * Math.min(L, 1 - L);
  const f = (n: number) => L - a * Math.max(-1, Math.min(k(n) - 3, Math.min(9 - k(n), 1)));
  return [f(0), f(8), f(4)].map((v) => Math.round(v * 255)) as Rgb;
}

export function hexToRgb(hex: string): Rgb {
  const h = hex.replace("#", "");
  return [0, 2, 4].map((i) => parseInt(h.slice(i, i + 2), 16)) as Rgb;
}

export function relativeLuminance([r, g, b]: Rgb): number {
  const lin = (c: number) => {
    const v = c / 255;
    return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4;
  };
  return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b);
}

export function contrastRatio(a: Rgb, b: Rgb): number {
  const la = relativeLuminance(a);
  const lb = relativeLuminance(b);
  return (Math.max(la, lb) + 0.05) / (Math.min(la, lb) + 0.05);
}

/** Custom properties declared in the first `selector { ... }` block of a stylesheet. */
export function parseBlock(css: string, selector: string): Record<string, string> {
  const start = css.indexOf(`${selector} {`);
  if (start < 0) throw new Error(`selector not found: ${selector}`);
  const open = css.indexOf("{", start);
  const close = css.indexOf("}", open);
  const body = css.slice(open + 1, close).replace(/\/\*[\s\S]*?\*\//g, "");
  const out: Record<string, string> = {};
  for (const m of body.matchAll(/--([\w-]+)\s*:\s*([^;]+);/g)) out[m[1]] = m[2].trim();
  return out;
}

export type ThemeKey = "aurora-light" | "aurora-dark" | "meridian-light" | "meridian-dark";

/** Resolved token maps per design × mode, following the cascade order of globals.css. */
export function themeTokens(css: string): Record<ThemeKey, Record<string, string>> {
  const root = parseBlock(css, ":root");
  const dark = parseBlock(css, ".dark");
  const meridian = parseBlock(css, '[data-design="meridian"]');
  const meridianDark = parseBlock(css, '[data-design="meridian"].dark');
  return {
    "aurora-light": { ...root },
    "aurora-dark": { ...root, ...dark },
    "meridian-light": { ...root, ...meridian },
    "meridian-dark": { ...root, ...dark, ...meridian, ...meridianDark },
  };
}

/** Text colour / background token pairs the UI actually renders. */
export const TEXT_PAIRS: [fg: string, bg: string][] = [
  ["foreground", "background"],
  ["foreground", "card"],
  ["foreground", "row-hover"],
  ["card-foreground", "card"],
  ["popover-foreground", "popover"],
  ["muted-foreground", "background"],
  ["muted-foreground", "card"],
  ["muted-foreground", "secondary"],
  ["muted-foreground", "muted"],
  ["secondary-foreground", "secondary"],
  ["ink-2", "card"],
  ["ink-2", "background"],
  ["ink-3", "card"],
  ["ink-3", "background"],
  ["label", "card"],
  ["label", "background"],
  ["primary", "card"],
  ["primary", "background"],
  ["primary-foreground", "primary"],
  ["accent-foreground", "accent"],
  ["accent-foreground", "card"],
  ["accent-foreground", "nav-hover"],
  ["destructive-foreground", "destructive"],
  ["success-foreground", "success"],
  ["warning-foreground", "warning"],
  ["info-foreground", "info"],
  ["success", "success-soft"],
  ["warning", "warning-soft"],
  ["danger", "danger-soft"],
  ["info", "info-soft"],
  ["success", "card"],
  ["warning", "card"],
  ["danger", "card"],
  ["info", "card"],
  ["diff-add-fg", "diff-add-bg"],
  ["diff-del-fg", "diff-del-bg"],
  ["diff-mod-fg", "diff-mod-bg"],
  ["sidebar-foreground", "sidebar"],
  ["pill-active-foreground", "pill-active"],
  ["avatar-foreground", "avatar"],
  ["sev-critical", "card"],
  ["sev-high", "card"],
  ["sev-medium", "card"],
  ["sev-low", "card"],
];

export function pairContrast(tokens: Record<string, string>, fg: string, bg: string): number {
  const f = tokens[fg];
  const b = tokens[bg];
  if (!f || !b) throw new Error(`missing token --${!f ? fg : bg}`);
  return contrastRatio(hslTripletToRgb(f), hslTripletToRgb(b));
}
