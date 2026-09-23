"use client";

import dynamic from "next/dynamic";
import * as React from "react";

import { useChartTheme } from "@/hooks/use-design";
import { cn } from "@/lib/utils";

import type { EChartProps } from "./echart";

const LazyEChart = dynamic(() => import("./echart"), {
  ssr: false,
  loading: () => <div className="shimmer h-full w-full rounded-lg bg-muted" aria-hidden />,
});

/** Chart token object for the active design theme × colour mode (re-exported for chart callers). */
export { useChartTheme };

/** Client-only ECharts chart in a fixed-height box. */
export function Chart({
  height = 240,
  className,
  ...props
}: EChartProps & { height?: number | string; className?: string }) {
  return (
    <div className={cn("w-full min-w-0", className)} style={{ height }}>
      <LazyEChart {...props} />
    </div>
  );
}
