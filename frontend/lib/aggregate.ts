/**
 * Pure helpers that turn API rows into chart-ready series. Everything here is computed from
 * data the API returned - nothing is sampled or invented.
 */
import { parseDate } from "@/lib/utils";

export type TimeRange = "24h" | "7d" | "30d";

export const TIME_RANGES: { value: TimeRange; label: string; long: string }[] = [
  { value: "24h", label: "24h", long: "Last 24 hours" },
  { value: "7d", label: "7d", long: "Last 7 days" },
  { value: "30d", label: "30d", long: "Last 30 days" },
];

const HOUR = 3_600_000;
const DAY = 24 * HOUR;

/** bucket width and count for a range: 24 x 1h, 28 x 6h, 30 x 1d */
export function rangeSpec(range: TimeRange): { step: number; count: number; span: number } {
  switch (range) {
    case "24h":
      return { step: HOUR, count: 24, span: DAY };
    case "7d":
      return { step: 6 * HOUR, count: 28, span: 7 * DAY };
    case "30d":
      return { step: DAY, count: 30, span: 30 * DAY };
  }
}

export function rangeStart(range: TimeRange, now: number): number {
  return now - rangeSpec(range).span;
}

function pad(n: number) {
  return String(n).padStart(2, "0");
}

const WEEKDAY = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
const MONTH = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

export function bucketLabel(start: number, range: TimeRange): string {
  const d = new Date(start);
  if (range === "24h") return `${pad(d.getHours())}:00`;
  if (range === "7d") return `${WEEKDAY[d.getDay()]} ${pad(d.getHours())}:00`;
  return `${pad(d.getDate())} ${MONTH[d.getMonth()]}`;
}

/** Bucket boundaries aligned to the step so labels read naturally (full hours / 6h / local days). */
export function buckets(range: TimeRange, now: number): number[] {
  const { step, count } = rangeSpec(range);
  let end: number;
  if (step === DAY) {
    const d = new Date(now);
    d.setHours(0, 0, 0, 0);
    end = d.getTime() + DAY;
  } else {
    const d = new Date(now);
    d.setMinutes(0, 0, 0);
    if (step === 6 * HOUR) d.setHours(Math.floor(d.getHours() / 6) * 6);
    end = d.getTime() + step;
  }
  return Array.from({ length: count }, (_, i) => end - (count - i) * step);
}

export interface TimeSeries {
  labels: string[];
  starts: number[];
  series: { name: string; data: number[] }[];
  /** rows that fell inside the window */
  counted: number;
}

/**
 * Count rows per time bucket, optionally split into groups (e.g. by result). Groups keep the
 * order in which `groupOrder` lists them, then by first appearance.
 */
export function bucketSeries<T>(
  rows: T[],
  getTime: (row: T) => string | null | undefined,
  range: TimeRange,
  now: number,
  opts: { group?: (row: T) => string; groupOrder?: string[]; value?: (row: T) => number } = {},
): TimeSeries {
  const starts = buckets(range, now);
  const { step } = rangeSpec(range);
  const first = starts[0];
  const end = starts[starts.length - 1] + step;
  const groups = new Map<string, number[]>();
  for (const g of opts.groupOrder ?? []) groups.set(g, new Array(starts.length).fill(0));
  let counted = 0;
  for (const r of rows) {
    const d = parseDate(getTime(r));
    if (!d) continue;
    const t = d.getTime();
    if (t < first || t >= end) continue;
    const idx = Math.min(starts.length - 1, Math.floor((t - first) / step));
    const key = opts.group ? opts.group(r) : "count";
    let arr = groups.get(key);
    if (!arr) {
      arr = new Array(starts.length).fill(0);
      groups.set(key, arr);
    }
    arr[idx] += opts.value ? opts.value(r) : 1;
    counted++;
  }
  return {
    labels: starts.map((s) => bucketLabel(s, range)),
    starts,
    series: [...groups.entries()].map(([name, data]) => ({ name, data })),
    counted,
  };
}

/** Daily totals for the last `days` local days (oldest first). */
export function dailySeries<T>(
  rows: T[],
  getTime: (row: T) => string | null | undefined,
  days: number,
  now: number,
  value?: (row: T) => number,
): { labels: string[]; data: number[]; starts: number[] } {
  const today = new Date(now);
  today.setHours(0, 0, 0, 0);
  const starts = Array.from({ length: days }, (_, i) => today.getTime() - (days - 1 - i) * DAY);
  const data = new Array(days).fill(0);
  for (const r of rows) {
    const d = parseDate(getTime(r));
    if (!d) continue;
    const idx = Math.floor((d.getTime() - starts[0]) / DAY);
    if (idx < 0 || idx >= days) continue;
    data[idx] += value ? value(r) : 1;
  }
  return { labels: starts.map((s) => bucketLabel(s, "30d")), data, starts };
}

export const DAY_LABELS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

/**
 * Weekday x hour-of-day matrix as [hour, dayIndex(Mon=0), count] triples - every cell present so
 * the heatmap has no holes. Only timestamps within `days` of `now` count.
 */
export function dayHourMatrix(timestamps: (string | null | undefined)[], now: number, days = 7): { cells: [number, number, number][]; max: number; counted: number } {
  const grid = Array.from({ length: 7 }, () => new Array(24).fill(0));
  const since = now - days * DAY;
  let counted = 0;
  for (const ts of timestamps) {
    const d = parseDate(ts);
    if (!d || d.getTime() < since || d.getTime() > now) continue;
    const day = (d.getDay() + 6) % 7;
    grid[day][d.getHours()]++;
    counted++;
  }
  const cells: [number, number, number][] = [];
  let max = 0;
  for (let day = 0; day < 7; day++) {
    for (let h = 0; h < 24; h++) {
      cells.push([h, day, grid[day][h]]);
      max = Math.max(max, grid[day][h]);
    }
  }
  return { cells, max, counted };
}

/** Count occurrences by key, largest first; everything past `top` folds into "Other". */
export function countBy<T>(rows: T[], key: (row: T) => string | null | undefined, top = Infinity, other = "Other"): { name: string; value: number }[] {
  const m = new Map<string, number>();
  for (const r of rows) {
    const k = key(r) || "Unknown";
    m.set(k, (m.get(k) ?? 0) + 1);
  }
  return foldTop([...m.entries()].map(([name, value]) => ({ name, value })), top, other);
}

export function foldTop(items: { name: string; value: number }[], top = Infinity, other = "Other"): { name: string; value: number }[] {
  const sorted = [...items].sort((a, b) => b.value - a.value || a.name.localeCompare(b.name));
  if (sorted.length <= top) return sorted;
  const head = sorted.slice(0, top - 1);
  const rest = sorted.slice(top - 1).reduce((a, b) => a + b.value, 0);
  return [...head, { name: other, value: rest }];
}

/** Histogram of 0-100 scores in fixed-width bins; the last bin includes the upper bound. */
export function histogram(values: number[], binSize = 10, min = 0, max = 100): { labels: string[]; data: number[] } {
  const n = Math.ceil((max - min) / binSize);
  const data = new Array(n).fill(0);
  for (const v of values) {
    if (!Number.isFinite(v)) continue;
    const idx = Math.min(n - 1, Math.max(0, Math.floor((v - min) / binSize)));
    data[idx]++;
  }
  const labels = data.map((_, i) => `${min + i * binSize}–${Math.min(max, min + (i + 1) * binSize)}`);
  return { labels, data };
}

/** Largest bucket total across stacked series (for "peak x/h" style captions). */
export function peak(series: { data: number[] }[]): number {
  if (!series.length) return 0;
  const len = series[0].data.length;
  let best = 0;
  for (let i = 0; i < len; i++) best = Math.max(best, series.reduce((a, s) => a + (s.data[i] ?? 0), 0));
  return best;
}

export function compactNumber(n: number): string {
  if (Math.abs(n) >= 1_000_000) return `${(n / 1_000_000).toFixed(n >= 10_000_000 ? 0 : 1)}M`;
  if (Math.abs(n) >= 1000) return `${(n / 1000).toFixed(n >= 10_000 ? 0 : 1)}k`;
  return String(n);
}
