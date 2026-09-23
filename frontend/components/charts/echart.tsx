"use client";

import { BarChart, FunnelChart, GaugeChart, GraphChart, HeatmapChart, LineChart, LinesChart, PieChart } from "echarts/charts";
import {
  AriaComponent,
  DataZoomInsideComponent,
  GridComponent,
  LegendComponent,
  LegendScrollComponent,
  MarkPointComponent,
  TooltipComponent,
  VisualMapContinuousComponent,
} from "echarts/components";
import * as echarts from "echarts/core";
import { LabelLayout } from "echarts/features";
import { CanvasRenderer } from "echarts/renderers";
import type { EChartsOption } from "echarts";
import * as React from "react";

echarts.use([
  BarChart,
  FunnelChart,
  GaugeChart,
  GraphChart,
  HeatmapChart,
  LineChart,
  LinesChart,
  PieChart,
  AriaComponent,
  DataZoomInsideComponent,
  GridComponent,
  LegendComponent,
  LegendScrollComponent,
  MarkPointComponent,
  TooltipComponent,
  VisualMapContinuousComponent,
  LabelLayout,
  CanvasRenderer,
]);

export type ChartEvents = Record<string, (params: unknown) => void>;

export interface EChartProps {
  option: EChartsOption;
  onEvents?: ChartEvents;
  ariaLabel?: string;
}

/** Stable signature of an option (functions by source) so identical re-renders do not replay animations. */
function signature(option: EChartsOption): string {
  try {
    return JSON.stringify(option, (_k, v: unknown) => (typeof v === "function" ? v.toString() : v));
  } catch {
    return String(Math.random());
  }
}

function prefersReducedMotion(): boolean {
  return typeof window !== "undefined" && !!window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
}

/** Stripped-down, typed ECharts host: init on mount, resize with its box, dispose on unmount. */
export default function EChart({ option, onEvents, ariaLabel }: EChartProps) {
  const ref = React.useRef<HTMLDivElement>(null);
  const chart = React.useRef<echarts.ECharts | null>(null);
  const lastSig = React.useRef<string>("");
  const events = React.useRef<ChartEvents | undefined>(onEvents);
  React.useEffect(() => {
    events.current = onEvents;
  });

  React.useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const instance = echarts.init(el, null, { renderer: "canvas" });
    chart.current = instance;
    const ro = new ResizeObserver(() => instance.resize());
    ro.observe(el);
    const handler = (name: string) => (params: unknown) => events.current?.[name]?.(params);
    const bound = ["click", "dblclick"].map((name) => {
      const h = handler(name);
      instance.on(name, h);
      return [name, h] as const;
    });
    return () => {
      ro.disconnect();
      bound.forEach(([name, h]) => instance.off(name, h));
      instance.dispose();
      chart.current = null;
      lastSig.current = "";
    };
  }, []);

  React.useEffect(() => {
    const instance = chart.current;
    if (!instance) return;
    const sig = signature(option);
    if (sig === lastSig.current) return;
    lastSig.current = sig;
    const reduce = prefersReducedMotion();
    instance.setOption(reduce ? { ...option, animation: false } : option, { notMerge: true, lazyUpdate: false });
  }, [option]);

  return <div ref={ref} role="img" aria-label={ariaLabel} className="h-full w-full" />;
}
