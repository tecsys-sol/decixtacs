"use client";

import dynamic from "next/dynamic";
import { useTheme } from "next-themes";
import * as React from "react";

import type { ChartMode } from "@/lib/charts";
import { cn } from "@/lib/utils";

import type { EChartProps } from "./echart";

const LazyEChart = dynamic(() => import("./echart"), {
  ssr: false,
  loading: () => <div className="shimmer h-full w-full rounded-lg bg-muted" aria-hidden />,
});

/** Current chart colour mode, following the app theme. */
export function useChartMode(): ChartMode {
  const { resolvedTheme } = useTheme();
  return resolvedTheme === "dark" ? "dark" : "light";
}

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
