"use client";

import Link from "next/link";
import type { LucideIcon } from "lucide-react";
import * as React from "react";

import { Chart, useChartTheme } from "@/components/charts/chart";
import { Skeleton } from "@/components/ui/skeleton";
import { sparklineOption, type SparklineInput } from "@/lib/charts";
import { cn } from "@/lib/utils";

const TONE_TEXT = {
  default: "text-ink-3",
  success: "text-success",
  warning: "text-warning",
  danger: "text-danger",
} as const;

const TONE_ICON = {
  default: "text-accent-foreground bg-accent",
  success: "text-success bg-success-soft",
  warning: "text-warning bg-warning-soft",
  danger: "text-danger bg-danger-soft",
} as const;

/** KPI card: label, big Sora number, a toned delta caption and an optional sparkline. */
export function KpiTile({
  label,
  value,
  sub,
  icon: Icon,
  tone = "default",
  href,
  loading,
  spark,
  delay = 0,
}: {
  label: string;
  value: React.ReactNode;
  sub?: React.ReactNode;
  icon?: LucideIcon;
  /** colours the caption (and icon) - status is always spelled out in the caption text too */
  tone?: keyof typeof TONE_TEXT;
  href?: string;
  loading?: boolean;
  spark?: SparklineInput | null;
  delay?: number;
}) {
  const theme = useChartTheme();
  const option = React.useMemo(() => (spark ? sparklineOption(spark, theme) : null), [spark, theme]);
  const body = (
    <article
      className={cn(
        "rise flex h-full min-w-0 flex-col gap-1 rounded-xl border bg-card px-[18px] pb-2 pt-[18px] transition-colors",
        href && "hover:border-primary/40",
      )}
      style={{ animationDelay: `${0.08 + delay * 0.06}s` }}
    >
      <div className="flex items-center justify-between gap-2">
        <span className="text-[13px] font-semibold text-ink-3">{label}</span>
        {Icon ? (
          <span className={cn("rounded-lg p-1.5", TONE_ICON[tone])}>
            <Icon className="h-3.5 w-3.5" aria-hidden />
          </span>
        ) : null}
      </div>
      {loading ? (
        <Skeleton className="mt-1 h-9 w-28" />
      ) : (
        <div className="flex min-w-0 flex-wrap items-baseline gap-x-2.5 gap-y-0.5">
          <span className="font-display text-[28px] font-bold leading-tight tracking-tight tabular sm:text-[30px]">{value}</span>
          {sub ? <span className={cn("text-[12.5px] font-bold", TONE_TEXT[tone])}>{sub}</span> : null}
        </div>
      )}
      {spark === undefined ? <div className="h-2" /> : option ? <Chart option={option} height={54} ariaLabel={`${label} trend`} /> : <div className="h-[54px]" />}
    </article>
  );
  return href ? (
    <Link href={href} className="block rounded-xl focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
      {body}
    </Link>
  ) : (
    body
  );
}
