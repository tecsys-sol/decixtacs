"use client";

import Link from "next/link";
import type { TooltipContentProps } from "recharts";

/** Shared chart styling tokens (see --series-* / --chart-* in globals.css). */
export const CHART = {
  series1: "var(--series-1)",
  series2: "var(--series-2)",
  series3: "var(--series-3)",
  series4: "var(--series-4)",
  grid: "var(--chart-grid)",
  axis: "var(--chart-axis)",
  tick: { fill: "var(--chart-axis)", fontSize: 11 },
} as const;

type Formatter = (value: number, name: string) => string;

/** Tooltip body in the app's popover style; values in text ink, the swatch carries identity. */
export function ChartTooltip({
  active,
  payload,
  label,
  labelFormatter,
  valueFormatter,
}: Partial<TooltipContentProps<number, string>> & {
  labelFormatter?: (label: unknown) => string;
  valueFormatter?: Formatter;
}) {
  if (!active || !payload?.length) return null;
  return (
    <div className="rounded-md border bg-popover px-2.5 py-1.5 text-xs text-popover-foreground shadow-lg">
      {label !== undefined ? (
        <p className="mb-1 font-medium">{labelFormatter ? labelFormatter(label) : String(label)}</p>
      ) : null}
      {payload.map((p) => (
        <p key={String(p.dataKey ?? p.name)} className="flex items-center gap-2">
          <span className="h-2 w-2 rounded-sm" style={{ background: p.color ?? CHART.series1 }} aria-hidden />
          <span className="text-muted-foreground">{p.name}</span>
          <span className="ml-auto font-medium tabular">
            {valueFormatter ? valueFormatter(Number(p.value), String(p.name)) : String(p.value)}
          </span>
        </p>
      ))}
    </div>
  );
}

/** Ranked horizontal bars in plain HTML (top-N lists): cheap, accessible, labelled. */
export function RankedBars({
  items,
  valueLabel,
  hrefFor,
  empty = "No data",
}: {
  items: { label: string; value: number }[];
  valueLabel?: string;
  hrefFor?: (label: string) => string;
  empty?: string;
}) {
  if (!items.length) return <p className="py-6 text-center text-xs text-muted-foreground">{empty}</p>;
  const max = Math.max(...items.map((i) => i.value), 1);
  return (
    <ul className="grid gap-2">
      {items.map((i) => {
        const content = (
          <>
            <div className="flex items-baseline justify-between gap-2 text-xs">
              <span className="truncate font-medium">{i.label}</span>
              <span className="shrink-0 text-muted-foreground tabular">
                {i.value.toLocaleString()} {valueLabel}
              </span>
            </div>
            <div className="mt-1 h-1.5 rounded-full bg-muted">
              <div
                className="h-full rounded-full"
                style={{ width: `${Math.max(2, (i.value / max) * 100)}%`, background: CHART.series1 }}
              />
            </div>
          </>
        );
        return (
          <li key={i.label}>
            {hrefFor ? (
              <Link href={hrefFor(i.label)} className="block rounded hover:bg-accent/40">
                {content}
              </Link>
            ) : (
              content
            )}
          </li>
        );
      })}
    </ul>
  );
}
