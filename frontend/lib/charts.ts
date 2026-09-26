/**
 * Chart themes and ECharts option builders.
 *
 * Builders are pure functions (data in, option out) so they can be unit-tested without a canvas.
 * Every colour, font and tooltip style comes from a `ChartTheme` token object — one per design
 * (Aurora / Meridian) × colour mode (light / dark). Colours are literal hex values because the
 * canvas renderer cannot read CSS variables; keep them in sync with app/globals.css.
 *
 * Colour rules: categorical hues are assigned in the FIXED order of `categorical` (validated for
 * colour-vision deficiency against each theme's card surface); magnitude uses the single-hue
 * sequential ramp; polarity (lines added / removed) uses the diverging pair; status and severity
 * colours are reserved for state and always paired with a text label in the legend / tooltip.
 *
 * Builders accept either a `ChartTheme` or a bare mode ("light" | "dark"), which means Aurora.
 */
import type { EChartsOption } from "echarts";

import type { Design } from "@/lib/theme";

export type ChartMode = "light" | "dark";

export interface StatusColors {
  success: string;
  warning: string;
  danger: string;
  neutral: string;
  info: string;
}

export interface SeverityColors {
  critical: string;
  high: string;
  medium: string;
  low: string;
}

export interface ChartTokens {
  ink: string;
  ink2: string;
  label: string;
  axisLine: string;
  /** stronger baseline (diverging zero line) */
  axisStrong: string;
  split: string;
  surface: string;
  track: string;
  brand: string;
  brand2: string;
  /** healthy topology link */
  link: string;
  /** text on a filled brand mark */
  onBrand: string;
  tooltipBorder: string;
  tooltipRadius: number;
  tooltipShadow: string;
  pointer: string;
  shadowFill: string;
}

export interface ChartFonts {
  body: string;
  display: string;
  mono: string;
}

export interface ChartTheme {
  design: Design;
  mode: ChartMode;
  /** categorical palette, fixed order — never cycled or re-sorted */
  categorical: string[];
  /** single-hue sequential ramp, low -> high magnitude */
  sequential: string[];
  diverging: { added: string; removed: string };
  status: StatusColors;
  severity: SeverityColors;
  tokens: ChartTokens;
  fonts: ChartFonts;
}

/** @fontsource family names; canvas fonts cannot use CSS variables. */
const AURORA_FONTS: ChartFonts = {
  body: "'Manrope Variable', system-ui, sans-serif",
  display: "'Sora Variable', 'Manrope Variable', sans-serif",
  mono: "'JetBrains Mono Variable', ui-monospace, monospace",
};
const MERIDIAN_FONTS: ChartFonts = {
  body: "'IBM Plex Sans Variable', system-ui, sans-serif",
  display: "'Fraunces Variable', Georgia, serif",
  mono: "'IBM Plex Mono', ui-monospace, monospace",
};

const tooltipShadow = (shadow: string, radius: number) => `box-shadow:${shadow};border-radius:${radius}px;`;

const AURORA_LIGHT: ChartTheme = {
  design: "aurora",
  mode: "light",
  categorical: ["#5b4ee6", "#dc6a22", "#0e9f7e", "#b88400", "#d9467a"],
  sequential: ["#f1f0fd", "#c9c3fb", "#8f85f0", "#5b4ee6", "#3326b8"],
  diverging: { added: "#2a78d6", removed: "#e34948" },
  status: { success: "#0e9f7e", warning: "#d69a00", danger: "#e0452b", neutral: "#b4b6cc", info: "#2a78d6" },
  severity: { critical: "#e0452b", high: "#dc6a22", medium: "#d69a00", low: "#2a78d6" },
  tokens: {
    ink: "#14142b",
    ink2: "#34364f",
    label: "#5d5f7a",
    axisLine: "#e4e5f1",
    axisStrong: "#c7c9dc",
    split: "#eff0f6",
    surface: "#ffffff",
    track: "#eeedfb",
    brand: "#5b4ee6",
    brand2: "#8f85f0",
    link: "#c9c3fb",
    onBrand: "#ffffff",
    tooltipBorder: "#e4e5f1",
    tooltipRadius: 10,
    tooltipShadow: tooltipShadow("0 8px 24px rgba(20,20,43,.12)", 10),
    pointer: "#b9b2f5",
    shadowFill: "rgba(91,78,230,.06)",
  },
  fonts: AURORA_FONTS,
};

const AURORA_DARK: ChartTheme = {
  design: "aurora",
  mode: "dark",
  categorical: ["#7a6fee", "#d9732c", "#1aa283", "#bb8a12", "#d9548a"],
  sequential: ["#23233f", "#3a3670", "#5b54a8", "#8f85f0", "#c9c3fb"],
  diverging: { added: "#4f93e6", removed: "#f06a69" },
  status: { success: "#2fbf98", warning: "#e0b040", danger: "#f06a55", neutral: "#5a5c7a", info: "#4f93e6" },
  severity: { critical: "#f06a55", high: "#d9732c", medium: "#e0b040", low: "#4f93e6" },
  tokens: {
    ink: "#ebebf5",
    ink2: "#d6d6e8",
    label: "#a3a4bf",
    axisLine: "#2c2c4a",
    axisStrong: "#3a3a5e",
    split: "#26264a",
    surface: "#1d1d36",
    track: "#2a2750",
    brand: "#8f85f0",
    brand2: "#b9b2f5",
    link: "#4a4590",
    onBrand: "#ffffff",
    tooltipBorder: "#34345a",
    tooltipRadius: 10,
    tooltipShadow: tooltipShadow("0 8px 24px rgba(0,0,0,.45)", 10),
    pointer: "#5b54a8",
    shadowFill: "rgba(143,133,240,.08)",
  },
  fonts: AURORA_FONTS,
};

/*
 * Meridian. Light categorical set is the approved mockup palette; the dark set is re-stepped into
 * the dark lightness band for the #211d17 card surface. Both pass the CVD / normal-vision /
 * contrast checks of the dataviz palette validator (adjacent ΔE >= 8 protan/deutan, >= 3:1 vs
 * surface).
 */
const MERIDIAN_LIGHT: ChartTheme = {
  design: "meridian",
  mode: "light",
  categorical: ["#009683", "#e0673a", "#4f6bd8", "#b88400", "#b0527e"],
  sequential: ["#eef4ef", "#bfe0d6", "#7fc3b3", "#2e9c89", "#0b5f59"],
  diverging: { added: "#3a64c9", removed: "#c2502a" },
  status: { success: "#2e9c89", warning: "#c99a1a", danger: "#b3261e", neutral: "#cbc2b1", info: "#4f6bd8" },
  severity: { critical: "#b3261e", high: "#c2502a", medium: "#b88400", low: "#7c7a70" },
  tokens: {
    ink: "#1f1b16",
    ink2: "#3d372e",
    label: "#5f5545",
    axisLine: "#e6dfd0",
    axisStrong: "#cfc6b3",
    split: "#efe9dc",
    surface: "#fffdf8",
    track: "#f1ece1",
    brand: "#0b5f59",
    brand2: "#2e9c89",
    link: "#bfe0d6",
    onBrand: "#fbf8f1",
    tooltipBorder: "#e6dfd0",
    tooltipRadius: 12,
    tooltipShadow: tooltipShadow("0 10px 26px rgba(31,27,22,.12)", 12),
    pointer: "#8cbcb0",
    shadowFill: "rgba(11,95,89,.05)",
  },
  fonts: MERIDIAN_FONTS,
};

const MERIDIAN_DARK: ChartTheme = {
  design: "meridian",
  mode: "dark",
  categorical: ["#10a18b", "#e06f43", "#6f86e6", "#b58a00", "#c7689a"],
  sequential: ["#26221b", "#1d3f39", "#1f6e62", "#3fb8a8", "#a3e6d9"],
  diverging: { added: "#7f95ec", removed: "#ec8a62" },
  status: { success: "#3fb8a8", warning: "#e0b040", danger: "#f07560", neutral: "#5a5145", info: "#8397ee" },
  severity: { critical: "#f07560", high: "#ec8a62", medium: "#d9a932", low: "#9d978a" },
  tokens: {
    ink: "#f1ebdf",
    ink2: "#e2d9c8",
    label: "#b5aa96",
    axisLine: "#3a332a",
    axisStrong: "#4d4539",
    split: "#2e2821",
    surface: "#211d17",
    track: "#2e2821",
    brand: "#3fb8a8",
    brand2: "#7fd3c4",
    link: "#2d5a53",
    onBrand: "#10201d",
    tooltipBorder: "#3a332a",
    tooltipRadius: 12,
    tooltipShadow: tooltipShadow("0 10px 26px rgba(0,0,0,.5)", 12),
    pointer: "#4c6d66",
    shadowFill: "rgba(63,184,168,.08)",
  },
  fonts: MERIDIAN_FONTS,
};

export const CHART_THEMES: Record<Design, Record<ChartMode, ChartTheme>> = {
  aurora: { light: AURORA_LIGHT, dark: AURORA_DARK },
  meridian: { light: MERIDIAN_LIGHT, dark: MERIDIAN_DARK },
};

export function chartTheme(design: Design, mode: ChartMode): ChartTheme {
  return CHART_THEMES[design][mode];
}

/** A theme object, or a bare mode (= Aurora in that mode). */
export type ThemeArg = ChartTheme | ChartMode;

export function resolveTheme(theme: ThemeArg): ChartTheme {
  return typeof theme === "string" ? CHART_THEMES.aurora[theme] : theme;
}

// Aurora aliases (kept for callers / tests that address colours by mode)
export const CATEGORICAL: Record<ChartMode, string[]> = { light: AURORA_LIGHT.categorical, dark: AURORA_DARK.categorical };
export const SEQUENTIAL: Record<ChartMode, string[]> = { light: AURORA_LIGHT.sequential, dark: AURORA_DARK.sequential };
export const DIVERGING: Record<ChartMode, { added: string; removed: string }> = { light: AURORA_LIGHT.diverging, dark: AURORA_DARK.diverging };
export const STATUS: Record<ChartMode, StatusColors> = { light: AURORA_LIGHT.status, dark: AURORA_DARK.status };
export const TOKENS: Record<ChartMode, ChartTokens> = { light: AURORA_LIGHT.tokens, dark: AURORA_DARK.tokens };

export function palette(theme: ThemeArg): string[] {
  return resolveTheme(theme).categorical;
}

export function statusColors(theme: ThemeArg): StatusColors {
  return resolveTheme(theme).status;
}

export function severityColor(severity: string, theme: ThemeArg): string {
  const s = resolveTheme(theme).severity;
  const k = severity.toLowerCase();
  return k === "critical" ? s.critical : k === "high" ? s.high : k === "medium" ? s.medium : s.low;
}

/** Hex (#rrggbb) + alpha (0..1) -> rgba() */
export function alpha(hex: string, a: number): string {
  const h = hex.replace("#", "");
  const r = parseInt(h.slice(0, 2), 16);
  const g = parseInt(h.slice(2, 4), 16);
  const b = parseInt(h.slice(4, 6), 16);
  return `rgba(${r},${g},${b},${a})`;
}

/** Vertical gradient fading to transparent (area fills). Plain object so no echarts import is needed. */
export function fade(color: string, from = 0.25) {
  return {
    type: "linear" as const,
    x: 0,
    y: 0,
    x2: 0,
    y2: 1,
    colorStops: [
      { offset: 0, color: alpha(color, from) },
      { offset: 1, color: alpha(color, 0) },
    ],
  };
}

export type ValueFormatter = (v: number) => string;
const plain: ValueFormatter = (v) => (Number.isFinite(v) ? v.toLocaleString("en") : "—");

export function compact(v: number): string {
  const a = Math.abs(v);
  if (a >= 1_000_000) return `${+(v / 1_000_000).toFixed(1)}M`;
  if (a >= 1000) return `${+(v / 1000).toFixed(1)}k`;
  return String(v);
}

function tooltipBase(th: ChartTheme) {
  const t = th.tokens;
  return {
    backgroundColor: t.surface,
    borderColor: t.tooltipBorder,
    borderWidth: 1,
    padding: [8, 12] as [number, number],
    textStyle: { color: t.ink, fontSize: 12, fontFamily: th.fonts.body },
    extraCssText: t.tooltipShadow,
    confine: true,
  };
}

function legendBase(th: ChartTheme) {
  return {
    icon: "roundRect",
    itemWidth: 10,
    itemHeight: 10,
    itemGap: 14,
    textStyle: { color: th.tokens.ink2, fontSize: 12, fontFamily: th.fonts.body },
  };
}

function axisLabel(th: ChartTheme, extra: Record<string, unknown> = {}) {
  return { color: th.tokens.label, fontSize: 11, fontFamily: th.fonts.body, ...extra };
}

/** Shared base: font, animation, tooltip look, aria description. */
export function baseOption(theme: ThemeArg): EChartsOption {
  const th = resolveTheme(theme);
  return {
    backgroundColor: "transparent",
    color: th.categorical,
    textStyle: { fontFamily: th.fonts.body, color: th.tokens.label },
    animationDuration: 1200,
    animationEasing: "cubicOut",
    animationDurationUpdate: 600,
    aria: { enabled: true },
    tooltip: tooltipBase(th),
  };
}

function swatch(color: string) {
  return `<span style="display:inline-block;width:8px;height:8px;border-radius:2px;margin-right:6px;background:${color}"></span>`;
}

interface AxisParam {
  axisValueLabel?: string;
  name?: string;
  seriesName?: string;
  value?: unknown;
  color?: unknown;
}

/** Axis tooltip: label line, then one row per series with the value in ink (swatch carries identity). */
function axisTooltip(th: ChartTheme, fmt: ValueFormatter, opts: { total?: boolean; abs?: boolean } = {}) {
  const t = th.tokens;
  return (raw: unknown) => {
    const params = (Array.isArray(raw) ? raw : [raw]) as AxisParam[];
    if (!params.length) return "";
    const head = `<div style="font-weight:700;margin-bottom:4px;color:${t.ink}">${params[0].axisValueLabel ?? params[0].name ?? ""}</div>`;
    let sum = 0;
    const rows = params
      .map((p) => {
        const v = Array.isArray(p.value) ? Number(p.value[p.value.length - 1]) : Number(p.value);
        sum += Number.isFinite(v) ? v : 0;
        const color = typeof p.color === "string" ? p.color : t.brand;
        return `<div style="display:flex;align-items:center;gap:10px;justify-content:space-between"><span style="color:${t.label}">${swatch(color)}${p.seriesName ?? ""}</span><b style="color:${t.ink}">${fmt(opts.abs ? Math.abs(v) : v)}</b></div>`;
      })
      .join("");
    const total =
      opts.total && params.length > 1
        ? `<div style="display:flex;justify-content:space-between;gap:10px;border-top:1px solid ${t.axisLine};margin-top:4px;padding-top:4px"><span style="color:${t.label}">Total</span><b>${fmt(sum)}</b></div>`
        : "";
    return head + rows + total;
  };
}

// --- sparkline -------------------------------------------------------------------------------

export interface SparklineInput {
  labels: string[];
  data: number[];
  name: string;
  color?: string;
  format?: ValueFormatter;
}

export function sparklineOption(input: SparklineInput, theme: ThemeArg): EChartsOption {
  const th = resolveTheme(theme);
  const color = input.color ?? th.categorical[0];
  const t = th.tokens;
  return {
    ...baseOption(th),
    grid: { left: 0, right: 0, top: 6, bottom: 2 },
    xAxis: { type: "category", show: false, boundaryGap: false, data: input.labels },
    yAxis: { type: "value", show: false, min: "dataMin" },
    tooltip: {
      ...tooltipBase(th),
      trigger: "axis",
      axisPointer: { type: "line", lineStyle: { color: t.pointer } },
      formatter: axisTooltip(th, input.format ?? plain),
    },
    series: [
      {
        type: "line",
        name: input.name,
        data: input.data,
        smooth: 0.4,
        symbol: "none",
        lineStyle: { width: 2, color },
        itemStyle: { color },
        areaStyle: { color: fade(color, 0.2) },
      },
    ],
  };
}

// --- gauge -----------------------------------------------------------------------------------

export interface GaugeInput {
  value: number | null;
  max?: number;
  label?: string;
  /** "arc" = 240° score gauge (dashboard); "ring" = full circle (risk) */
  variant?: "arc" | "ring";
  color?: string;
  /** light track colour; defaults to a tint of the colour */
  track?: string;
  format?: (v: number) => string;
  /** gradient progress (score gauges) */
  gradient?: boolean;
}

export function gaugeOption(input: GaugeInput, theme: ThemeArg): EChartsOption {
  const th = resolveTheme(theme);
  const t = th.tokens;
  const color = input.color ?? t.brand;
  const ring = input.variant === "ring";
  const width = ring ? 14 : 16;
  const progressColor = input.gradient
    ? { type: "linear" as const, x: 0, y: 0, x2: 1, y2: 0, colorStops: [{ offset: 0, color: t.brand2 }, { offset: 1, color: t.brand }] }
    : color;
  const value = input.value ?? 0;
  const fmt = input.format ?? ((v: number) => (Number.isInteger(v) ? String(v) : v.toFixed(1)));
  return {
    ...baseOption(th),
    tooltip: { show: false },
    series: [
      {
        type: "gauge",
        startAngle: ring ? 90 : 210,
        endAngle: ring ? -270 : -30,
        min: 0,
        max: input.max ?? 100,
        radius: ring ? "88%" : "96%",
        center: ring ? ["50%", "50%"] : ["50%", "58%"],
        progress: { show: value > 0, width, roundCap: true, itemStyle: { color: progressColor } },
        axisLine: { roundCap: true, lineStyle: { width, color: [[1, input.track ?? (ring ? alpha(color, th.mode === "light" ? 0.14 : 0.22) : t.track)]] } },
        pointer: { show: false },
        axisTick: { show: false },
        splitLine: { show: false },
        axisLabel: { show: false },
        anchor: { show: false },
        title: { offsetCenter: [0, ring ? "30%" : "34%"], color: t.label, fontSize: 12, fontFamily: th.fonts.body },
        detail: {
          valueAnimation: true,
          offsetCenter: [0, ring ? "-6%" : "0%"],
          fontSize: ring ? 30 : 38,
          fontWeight: 700,
          fontFamily: th.fonts.display,
          color: t.ink,
          formatter: input.value === null ? () => "—" : (v: number) => fmt(v),
        },
        data: [{ value, name: input.label ?? "" }],
      },
    ],
  };
}

// --- donut / pie / rose ----------------------------------------------------------------------

export interface PieItem {
  name: string;
  value: number;
  color?: string;
}

export interface DonutInput {
  items: PieItem[];
  centerValue?: string;
  centerLabel?: string;
  rose?: boolean;
  format?: ValueFormatter;
  legend?: "bottom" | "right" | false;
}

export function donutOption(input: DonutInput, theme: ThemeArg): EChartsOption {
  const th = resolveTheme(theme);
  const t = th.tokens;
  const fmt = input.format ?? plain;
  const colors = th.categorical;
  const legendPos = input.legend ?? "bottom";
  const center: [string, string] = legendPos === "right" ? ["36%", "50%"] : ["50%", "44%"];
  return {
    ...baseOption(th),
    color: colors,
    tooltip: {
      ...tooltipBase(th),
      trigger: "item",
      formatter: (p: unknown) => {
        const q = p as { name: string; value: number; percent: number; color: string };
        return `${swatch(q.color)}<span style="color:${t.label}">${q.name}</span> <b style="color:${t.ink};margin-left:8px">${fmt(q.value)}</b> <span style="color:${t.label}">(${q.percent}%)</span>`;
      },
    },
    legend:
      legendPos === false || input.items.length < 2
        ? { show: false }
        : {
            ...legendBase(th),
            icon: "circle",
            itemWidth: 8,
            itemHeight: 8,
            type: legendPos === "right" ? "scroll" : "plain",
            ...(legendPos === "right" ? { orient: "vertical", right: 0, top: "middle" } : { bottom: 0, left: "center" }),
          },
    series: [
      {
        type: "pie",
        radius: input.rose ? ["22%", "74%"] : ["52%", "78%"],
        roseType: input.rose ? "radius" : undefined,
        center,
        padAngle: input.rose ? 0 : 2,
        avoidLabelOverlap: true,
        itemStyle: { borderRadius: input.rose ? 4 : 6, borderColor: t.surface, borderWidth: 2 },
        label: input.rose
          ? { show: false }
          : {
              show: input.centerValue !== undefined,
              position: "center",
              formatter: () => `${input.centerValue ?? ""}\n{s|${input.centerLabel ?? ""}}`,
              fontFamily: th.fonts.display,
              fontSize: 22,
              fontWeight: 700,
              color: t.ink,
              lineHeight: 26,
              rich: { s: { fontSize: 12, fontWeight: 500, color: t.label, fontFamily: th.fonts.body } },
            },
        emphasis: { scale: true, scaleSize: 6, label: { show: input.centerValue !== undefined && !input.rose } },
        labelLine: { show: false },
        data: input.items.map((i, idx) => ({
          name: i.name,
          value: i.value,
          itemStyle: { color: i.color ?? colors[idx % colors.length] },
        })),
      },
    ],
  };
}

// --- bars ------------------------------------------------------------------------------------

export interface BarSeries {
  name: string;
  data: number[];
  color?: string;
  stack?: string;
}

export interface BarInput {
  categories: string[];
  series: BarSeries[];
  horizontal?: boolean;
  format?: ValueFormatter;
  /** truncate long category labels (horizontal bars) */
  labelWidth?: number;
  /** show the value at the end of each bar (single series, horizontal) */
  valueLabels?: boolean;
  barWidth?: number;
  axisLabelInterval?: number | "auto";
}

export function barOption(input: BarInput, theme: ThemeArg): EChartsOption {
  const th = resolveTheme(theme);
  const t = th.tokens;
  const colors = th.categorical;
  const fmt = input.format ?? plain;
  const stackedKeys = new Set(input.series.filter((s) => s.stack).map((s) => s.stack));
  const horizontal = !!input.horizontal;
  const catAxis = {
    type: "category" as const,
    data: input.categories,
    inverse: horizontal,
    axisTick: { show: false },
    axisLine: { show: !horizontal, lineStyle: { color: t.axisLine } },
    axisLabel: axisLabel(th, {
      interval: input.axisLabelInterval ?? "auto",
      ...(horizontal ? { width: input.labelWidth ?? 110, overflow: "truncate", color: t.ink2, fontSize: 12 } : { hideOverlap: true }),
    }),
  };
  const valAxis = {
    type: "value" as const,
    minInterval: 1,
    splitLine: { lineStyle: { color: t.split } },
    axisLabel: axisLabel(th, { formatter: (v: number) => compact(v) }),
  };
  const multi = input.series.length > 1;
  return {
    ...baseOption(th),
    grid: { left: 8, right: input.valueLabels ? 44 : 12, top: multi ? 34 : 12, bottom: 8, containLabel: true },
    legend: multi ? { ...legendBase(th), top: 0, right: 0 } : { show: false },
    tooltip: {
      ...tooltipBase(th),
      trigger: "axis",
      axisPointer: { type: "shadow", shadowStyle: { color: t.shadowFill } },
      formatter: axisTooltip(th, fmt, { total: stackedKeys.size > 0 }),
    },
    xAxis: horizontal ? valAxis : catAxis,
    yAxis: horizontal ? catAxis : valAxis,
    series: input.series.map((s, i) => {
      const color = s.color ?? colors[i % colors.length];
      // stacked segments: only the outermost segment gets the rounded end
      const isLastInStack = s.stack ? input.series.filter((x) => x.stack === s.stack).slice(-1)[0] === s : true;
      const radius = isLastInStack ? (horizontal ? [0, 4, 4, 0] : [4, 4, 0, 0]) : 0;
      return {
        type: "bar" as const,
        name: s.name,
        data: s.data,
        stack: s.stack,
        barMaxWidth: input.barWidth ?? (horizontal ? 16 : 22),
        barGap: "20%",
        itemStyle: {
          color,
          borderRadius: radius,
          // 2px surface gap between stacked segments
          borderColor: s.stack ? t.surface : undefined,
          borderWidth: s.stack ? 1 : 0,
        },
        emphasis: { focus: "series" as const },
        label: input.valueLabels
          ? { show: true, position: horizontal ? ("right" as const) : ("top" as const), color: t.ink2, fontSize: 11, formatter: (p: { value: unknown }) => fmt(Number(p.value)) }
          : { show: false },
      };
    }),
  };
}

// --- diverging bars (added above / removed below) ---------------------------------------------

export interface DivergingInput {
  categories: string[];
  added: number[];
  removed: number[];
  /** tooltip header per category (e.g. commit message) */
  details?: string[];
  showCategoryLabels?: boolean;
}

export function divergingBarOption(input: DivergingInput, theme: ThemeArg): EChartsOption {
  const th = resolveTheme(theme);
  const t = th.tokens;
  const d = th.diverging;
  return {
    ...baseOption(th),
    legend: { ...legendBase(th), top: 0, right: 0, data: ["Added", "Removed"] },
    grid: { left: 8, right: 8, top: 30, bottom: 6, containLabel: true },
    tooltip: {
      ...tooltipBase(th),
      trigger: "axis",
      axisPointer: { type: "shadow", shadowStyle: { color: t.shadowFill } },
      formatter: (raw: unknown) => {
        const params = raw as { dataIndex: number; seriesName: string; value: number; color: string; axisValueLabel: string }[];
        if (!params.length) return "";
        const i = params[0].dataIndex;
        const head = `<div style="font-weight:700;margin-bottom:4px;max-width:260px;white-space:normal">${input.details?.[i] ?? params[0].axisValueLabel}</div>`;
        return (
          head +
          params
            .map((p) => `<div style="display:flex;justify-content:space-between;gap:12px"><span style="color:${t.label}">${swatch(p.color)}${p.seriesName}</span><b>${Math.abs(p.value).toLocaleString("en")}</b></div>`)
            .join("")
        );
      },
    },
    xAxis: {
      type: "category",
      data: input.categories,
      axisTick: { show: false },
      axisLine: { lineStyle: { color: t.axisStrong } },
      axisLabel: input.showCategoryLabels ? axisLabel(th, { hideOverlap: true }) : { show: false },
    },
    yAxis: {
      type: "value",
      minInterval: 1,
      splitLine: { lineStyle: { color: t.split } },
      axisLabel: axisLabel(th, { formatter: (v: number) => compact(Math.abs(v)) }),
    },
    series: [
      { name: "Added", type: "bar", stack: "d", data: input.added, barMaxWidth: 12, itemStyle: { color: d.added, borderRadius: [4, 4, 0, 0] } },
      { name: "Removed", type: "bar", stack: "d", data: input.removed.map((v) => -Math.abs(v)), barMaxWidth: 12, itemStyle: { color: d.removed, borderRadius: [0, 0, 4, 4] } },
    ],
  };
}

// --- line / area -----------------------------------------------------------------------------

export interface LineInput {
  categories: string[];
  series: { name: string; data: (number | null)[]; color?: string }[];
  area?: boolean;
  stacked?: boolean;
  min?: number | "dataMin";
  max?: number;
  format?: ValueFormatter;
  axisFormat?: ValueFormatter;
  labelInterval?: number | "auto";
  markMax?: boolean;
  smooth?: boolean;
  showSymbols?: boolean;
}

export function lineOption(input: LineInput, theme: ThemeArg): EChartsOption {
  const th = resolveTheme(theme);
  const t = th.tokens;
  const colors = th.categorical;
  const fmt = input.format ?? plain;
  const multi = input.series.length > 1;
  return {
    ...baseOption(th),
    legend: multi ? { ...legendBase(th), top: 0, right: 0 } : { show: false },
    grid: { left: 8, right: 12, top: multi ? 34 : 14, bottom: 6, containLabel: true },
    tooltip: {
      ...tooltipBase(th),
      trigger: "axis",
      axisPointer: { type: "line", lineStyle: { color: t.pointer } },
      formatter: axisTooltip(th, fmt, { total: !!input.stacked }),
    },
    xAxis: {
      type: "category",
      boundaryGap: false,
      data: input.categories,
      axisLine: { lineStyle: { color: t.axisLine } },
      axisTick: { show: false },
      axisLabel: axisLabel(th, { interval: input.labelInterval ?? "auto", hideOverlap: true }),
    },
    yAxis: {
      type: "value",
      min: input.min,
      max: input.max,
      minInterval: input.max === 100 ? undefined : 1,
      splitLine: { lineStyle: { color: t.split } },
      axisLabel: axisLabel(th, { formatter: input.axisFormat ?? ((v: number) => compact(v)) }),
    },
    series: input.series.map((s, i) => {
      const color = s.color ?? colors[i % colors.length];
      return {
        type: "line" as const,
        name: s.name,
        data: s.data,
        stack: input.stacked ? "total" : undefined,
        smooth: input.smooth === false ? false : 0.35,
        symbol: "circle",
        symbolSize: 8,
        showSymbol: input.showSymbols ?? input.categories.length <= 12,
        connectNulls: true,
        lineStyle: { width: 2, color },
        itemStyle: { color, borderColor: t.surface, borderWidth: 2 },
        areaStyle: input.area ? { color: fade(color, input.stacked ? 0.22 : 0.25), opacity: 1 } : undefined,
        emphasis: { focus: multi ? ("series" as const) : ("none" as const) },
        markPoint: input.markMax
          ? {
              symbolSize: 34,
              itemStyle: { color },
              label: { fontSize: 10, fontWeight: 700, color: t.onBrand, formatter: (p: { value: unknown }) => compact(Number(p.value)) },
              data: [{ type: "max" as const, name: "Peak" }],
            }
          : undefined,
      };
    }),
  };
}

// --- heatmap ---------------------------------------------------------------------------------

export interface HeatmapInput {
  xLabels: string[];
  yLabels: string[];
  cells: [number, number, number][];
  max?: number;
  unit?: string;
  tooltip?: (x: string, y: string, v: number) => string;
}

export function heatmapOption(input: HeatmapInput, theme: ThemeArg): EChartsOption {
  const th = resolveTheme(theme);
  const t = th.tokens;
  const max = Math.max(1, input.max ?? input.cells.reduce((m, c) => Math.max(m, c[2]), 0));
  return {
    ...baseOption(th),
    tooltip: {
      ...tooltipBase(th),
      formatter: (p: unknown) => {
        const v = (p as { value: [number, number, number] }).value;
        const x = input.xLabels[v[0]];
        const y = input.yLabels[v[1]];
        return input.tooltip ? input.tooltip(x, y, v[2]) : `<b>${y} ${x}</b> — ${v[2].toLocaleString("en")} ${input.unit ?? ""}`;
      },
    },
    grid: { left: 6, right: 6, top: 6, bottom: 44, containLabel: true },
    xAxis: {
      type: "category",
      data: input.xLabels,
      splitArea: { show: false },
      axisLine: { show: false },
      axisTick: { show: false },
      axisLabel: axisLabel(th, { interval: 3 }),
    },
    yAxis: {
      type: "category",
      data: input.yLabels,
      axisLine: { show: false },
      axisTick: { show: false },
      axisLabel: axisLabel(th),
    },
    visualMap: {
      min: 0,
      max,
      calculable: false,
      orient: "horizontal",
      left: "center",
      bottom: 0,
      itemWidth: 10,
      itemHeight: 120,
      text: ["More", "Less"],
      textStyle: { color: t.label, fontSize: 11 },
      inRange: { color: th.sequential },
    },
    series: [
      {
        type: "heatmap",
        data: input.cells,
        itemStyle: { borderColor: t.surface, borderWidth: 2, borderRadius: 3 },
        emphasis: { itemStyle: { borderColor: t.ink, borderWidth: 1 } },
      },
    ],
  };
}

// --- funnel ----------------------------------------------------------------------------------

export function funnelOption(items: PieItem[], theme: ThemeArg, format: ValueFormatter = plain): EChartsOption {
  const th = resolveTheme(theme);
  const t = th.tokens;
  const ramp = th.sequential;
  // stages share one hue (magnitude of the same measure), darkest first
  const steps = [ramp[4], ramp[3], ramp[2], ramp[1]];
  return {
    ...baseOption(th),
    tooltip: {
      ...tooltipBase(th),
      trigger: "item",
      formatter: (p: unknown) => {
        const q = p as { name: string; value: number };
        return `<span style="color:${t.label}">${q.name}</span> <b style="margin-left:8px">${format(q.value)}</b>`;
      },
    },
    series: [
      {
        type: "funnel",
        left: "2%",
        right: "40%",
        top: 8,
        bottom: 8,
        minSize: "12%",
        sort: "none",
        gap: 2,
        label: {
          show: true,
          position: "right",
          color: t.ink2,
          fontSize: 12,
          formatter: (p: { name: string; value: unknown }) => `${p.name}  {v|${format(Number(p.value))}}`,
          rich: { v: { fontWeight: 700, color: t.ink, fontFamily: th.fonts.display } },
        },
        labelLine: { show: true, lineStyle: { color: t.axisLine } },
        itemStyle: { borderColor: t.surface, borderWidth: 2, borderRadius: 4 },
        data: items.map((i, idx) => ({
          name: i.name,
          value: i.value,
          itemStyle: { color: i.color ?? steps[Math.min(idx, steps.length - 1)] },
        })),
      },
    ],
  };
}

// --- network graph ---------------------------------------------------------------------------

export interface GraphInput {
  sites: { id: string; name: string }[];
  nodes: { id: string; label: string; site_id: string | null; role: string | null; platform: string | null; status: string; backup: string | null }[];
  edges: { id: string; source: string; target: string; label: string; speed_mbps: number | null; status: string }[];
}

export type GraphLayout = "clustered" | "force";

/** healthy nodes are hollow (surface fill, site-coloured ring); problems are filled */
function statusColor(status: string, th: ChartTheme) {
  const s = th.status;
  return status === "up" ? th.tokens.surface : status === "down" ? s.danger : s.neutral;
}

function hashSeed(s: string): number {
  let h = 2166136261;
  for (let i = 0; i < s.length; i++) {
    h ^= s.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return h >>> 0;
}

function rng(seed: number) {
  let s = seed || 1;
  return () => {
    s = (Math.imul(s, 1664525) + 1013904223) >>> 0;
    return s / 4294967296;
  };
}

/**
 * Deterministic force-directed layout with site clustering: nodes repel, links attract, and each
 * node is pulled towards its site's anchor (site anchors sit on a circle). Returns positions in an
 * abstract 0..1000 space.
 */
export function clusteredLayout(input: GraphInput, iterations = 220): Map<string, [number, number]> {
  const siteIds = [...new Set(input.nodes.map((n) => n.site_id ?? "__none__"))].sort();
  const anchors = new Map<string, [number, number]>();
  const R = siteIds.length > 1 ? 330 : 0;
  siteIds.forEach((s, i) => {
    const a = (i / siteIds.length) * Math.PI * 2 - Math.PI / 2;
    anchors.set(s, [500 + R * Math.cos(a), 500 + R * Math.sin(a)]);
  });
  const rand = rng(hashSeed(input.nodes.map((n) => n.id).join("|")));
  const pos = input.nodes.map((n) => {
    const [ax, ay] = anchors.get(n.site_id ?? "__none__")!;
    return [ax + (rand() - 0.5) * 120, ay + (rand() - 0.5) * 120];
  });
  const index = new Map(input.nodes.map((n, i) => [n.id, i]));
  const links = input.edges
    .map((e) => [index.get(e.source), index.get(e.target)] as const)
    .filter((l): l is readonly [number, number] => l[0] !== undefined && l[1] !== undefined);
  const n = pos.length;
  for (let it = 0; it < iterations; it++) {
    const cool = 1 - it / iterations;
    const disp = pos.map(() => [0, 0]);
    for (let i = 0; i < n; i++) {
      for (let j = i + 1; j < n; j++) {
        let dx = pos[i][0] - pos[j][0];
        let dy = pos[i][1] - pos[j][1];
        let d2 = dx * dx + dy * dy;
        if (d2 < 0.01) {
          dx = rand() - 0.5;
          dy = rand() - 0.5;
          d2 = 0.01;
        }
        const f = 2400 / d2;
        disp[i][0] += dx * f;
        disp[i][1] += dy * f;
        disp[j][0] -= dx * f;
        disp[j][1] -= dy * f;
      }
    }
    for (const [a, b] of links) {
      const dx = pos[b][0] - pos[a][0];
      const dy = pos[b][1] - pos[a][1];
      const d = Math.sqrt(dx * dx + dy * dy) || 1;
      const f = (d - 90) * 0.02;
      disp[a][0] += (dx / d) * f * d * 0.05;
      disp[a][1] += (dy / d) * f * d * 0.05;
      disp[b][0] -= (dx / d) * f * d * 0.05;
      disp[b][1] -= (dy / d) * f * d * 0.05;
    }
    input.nodes.forEach((node, i) => {
      const [ax, ay] = anchors.get(node.site_id ?? "__none__")!;
      disp[i][0] += (ax - pos[i][0]) * 0.06;
      disp[i][1] += (ay - pos[i][1]) * 0.06;
      const len = Math.sqrt(disp[i][0] ** 2 + disp[i][1] ** 2) || 1;
      const step = Math.min(len, 18 * cool + 1);
      pos[i][0] += (disp[i][0] / len) * step;
      pos[i][1] += (disp[i][1] / len) * step;
    });
  }
  return new Map(input.nodes.map((node, i) => [node.id, [Math.round(pos[i][0]), Math.round(pos[i][1])] as [number, number]]));
}

function speedLabel(mbps: number | null): string {
  if (!mbps) return "";
  return mbps >= 1000 ? `${mbps / 1000}G` : `${mbps}M`;
}

export function networkGraphOption(input: GraphInput, theme: ThemeArg, layout: GraphLayout = "clustered"): EChartsOption {
  const th = resolveTheme(theme);
  const t = th.tokens;
  const colors = th.categorical;
  const siteName = new Map(input.sites.map((s) => [s.id, s.name]));
  const siteKeys = [...new Set(input.nodes.map((n) => n.site_id ?? "__none__"))].sort((a, b) =>
    (siteName.get(a) ?? "~").localeCompare(siteName.get(b) ?? "~"),
  );
  // Site identity: categorical hue in fixed order; more than five sites fold into a neutral ring.
  const categories = siteKeys.map((k, i) => ({
    name: siteName.get(k) ?? "Unassigned",
    itemStyle: { color: i < colors.length ? colors[i] : t.label },
  }));
  const catIndex = new Map(siteKeys.map((k, i) => [k, i]));
  const degree = new Map<string, number>();
  for (const e of input.edges) {
    degree.set(e.source, (degree.get(e.source) ?? 0) + 1);
    degree.set(e.target, (degree.get(e.target) ?? 0) + 1);
  }
  const clustered = layout === "clustered";
  const positions = clustered ? clusteredLayout(input) : null;
  const showLabels = input.nodes.length <= 60;

  const nodes = input.nodes.map((n) => {
    const cat = catIndex.get(n.site_id ?? "__none__") ?? 0;
    const p = positions?.get(n.id);
    return {
      id: n.id,
      name: n.label,
      category: cat,
      value: p ? [p[0], p[1]] : undefined,
      x: p?.[0],
      y: p?.[1],
      symbolSize: 14 + Math.min(12, (degree.get(n.id) ?? 0) * 2),
      itemStyle: {
        color: statusColor(n.status, th),
        borderColor: categories[cat].itemStyle.color,
        borderWidth: 3,
        shadowBlur: n.status === "down" ? 10 : 0,
        shadowColor: n.status === "down" ? alpha(th.status.danger, 0.5) : "transparent",
      },
      label: { show: showLabels },
      // carried through to tooltips / click handlers
      deviceId: n.id,
      status: n.status,
      role: n.role,
      platform: n.platform,
      backup: n.backup,
      site: categories[cat].name,
    };
  });
  const nodeIds = new Set(input.nodes.map((n) => n.id));
  const links = input.edges
    .filter((e) => nodeIds.has(e.source) && nodeIds.has(e.target))
    .map((e) => ({
      source: e.source,
      target: e.target,
      value: e.speed_mbps ?? 0,
      linkLabel: e.label,
      speed: speedLabel(e.speed_mbps),
      status: e.status,
      lineStyle: {
        color: e.status === "up" ? t.link : th.status.danger,
        width: e.speed_mbps && e.speed_mbps >= 100_000 ? 3 : 2,
        type: e.status === "up" ? ("solid" as const) : ("dashed" as const),
        curveness: 0.08,
      },
    }));

  const tooltip = {
    ...tooltipBase(th),
    formatter: (raw: unknown) => {
      const p = raw as { dataType: string; data: Record<string, unknown> };
      if (p.dataType === "edge") {
        const d = p.data;
        return `<b>${String(d.linkLabel || "Link")}</b><br/><span style="color:${t.label}">Status</span> ${String(d.status)}${d.speed ? ` · ${String(d.speed)}` : ""}`;
      }
      const d = p.data;
      const meta = [d.role, d.platform].filter(Boolean).join(" · ");
      return `<b>${String(d.name)}</b><br/><span style="color:${t.label}">${String(d.site)}</span>${meta ? `<br/>${String(meta)}` : ""}<br/>Status: <b>${String(d.status)}</b>${d.backup ? `<br/>Last backup: ${String(d.backup)}` : ""}`;
    },
  };

  const graphSeries = {
    type: "graph" as const,
    name: "Topology",
    layout: clustered ? ("none" as const) : ("force" as const),
    coordinateSystem: clustered ? ("cartesian2d" as const) : undefined,
    roam: clustered ? false : true,
    draggable: !clustered,
    categories,
    data: nodes,
    links,
    edgeSymbol: ["none", "none"],
    label: {
      position: "bottom" as const,
      distance: 4,
      color: t.ink2,
      fontSize: 11,
      fontWeight: 600,
      fontFamily: th.fonts.body,
      backgroundColor: alpha(t.surface, 0.8),
      padding: [1, 3],
      borderRadius: 3,
    },
    edgeLabel: { show: false },
    emphasis: { focus: "adjacency" as const, lineStyle: { width: 3 } },
    force: clustered ? undefined : { repulsion: 260, edgeLength: [60, 140], gravity: 0.08, friction: 0.2, layoutAnimation: true },
    scaleLimit: { min: 0.3, max: 4 },
    zlevel: 1,
  };

  const option: EChartsOption = {
    ...baseOption(th),
    color: categories.map((c) => c.itemStyle.color),
    tooltip,
    legend: {
      ...legendBase(th),
      icon: "circle",
      type: "scroll",
      bottom: 0,
      left: "center",
      data: categories.map((c) => c.name),
    },
    animationDurationUpdate: 800,
    series: [graphSeries],
  };

  if (clustered && positions) {
    const coords = [...positions.values()];
    const xs = coords.map((c) => c[0]);
    const ys = coords.map((c) => c[1]);
    const pad = 60;
    option.grid = { left: 10, right: 10, top: 10, bottom: 40 };
    option.xAxis = { type: "value", show: false, min: Math.min(...xs) - pad, max: Math.max(...xs) + pad, scale: true };
    option.yAxis = { type: "value", show: false, min: Math.min(...ys) - pad, max: Math.max(...ys) + pad, scale: true, inverse: true };
    option.dataZoom = [
      { type: "inside", xAxisIndex: 0, filterMode: "none" },
      { type: "inside", yAxisIndex: 0, filterMode: "none" },
    ];
    // animated "packets" flowing along healthy links, like the mockup's dashed-flow strokes
    const flows = links
      .filter((l) => l.status === "up")
      .map((l) => ({ coords: [positions.get(l.source)!, positions.get(l.target)!] }));
    (option.series as unknown[]).push({
      type: "lines",
      coordinateSystem: "cartesian2d",
      // beneath the graph layer so particles never cover node labels
      zlevel: 0,
      silent: true,
      effect: { show: true, period: 3.2, trailLength: 0.25, symbol: "circle", symbolSize: 4, color: t.brand },
      lineStyle: { opacity: 0 },
      data: flows,
    });
  }
  return option;
}
