import type { LucideIcon } from "lucide-react";
import * as React from "react";

import { EmptyState } from "@/components/common/empty-state";
import { ErrorState } from "@/components/common/error-state";
import { Skeleton } from "@/components/ui/skeleton";
import type { EmptyArt } from "@/components/illustrations";
import { cn } from "@/lib/utils";

/** Aurora card for a chart or list: Sora title, caption, optional actions; rises in with a delay. */
export function ChartCard({
  title,
  description,
  actions,
  delay = 0,
  className,
  bodyClassName,
  children,
}: {
  title: React.ReactNode;
  description?: React.ReactNode;
  actions?: React.ReactNode;
  /** stagger index; each step adds 60ms to the rise animation */
  delay?: number;
  className?: string;
  bodyClassName?: string;
  children: React.ReactNode;
}) {
  return (
    <section
      className={cn("rise flex min-w-0 flex-col gap-1.5 rounded-xl border bg-card p-5 text-card-foreground", className)}
      style={{ animationDelay: `${0.08 + delay * 0.06}s` }}
    >
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="flex min-w-0 flex-col gap-0.5">
          <h2 className="font-display text-base font-semibold leading-snug">{title}</h2>
          {description ? <p className="text-[12.5px] text-muted-foreground">{description}</p> : null}
        </div>
        {actions ? <div className="flex shrink-0 items-center gap-2">{actions}</div> : null}
      </div>
      <div className={cn("min-w-0 flex-1", bodyClassName)}>{children}</div>
    </section>
  );
}

/** Loading / error / empty handling for a chart body. */
export function ChartBody({
  loading,
  error,
  empty,
  emptyTitle = "No data yet",
  emptyDescription,
  emptyIcon,
  emptyArt = "chart",
  height = 240,
  onRetry,
  children,
}: {
  loading?: boolean;
  error?: unknown;
  empty?: boolean;
  emptyTitle?: string;
  emptyDescription?: React.ReactNode;
  emptyIcon?: LucideIcon;
  emptyArt?: EmptyArt;
  height?: number;
  onRetry?: () => void;
  children: React.ReactNode;
}) {
  if (loading) return <Skeleton className="w-full" style={{ height }} />;
  if (error) return <ErrorState error={error} onRetry={onRetry} className="py-6" />;
  if (empty) {
    return (
      <div className="flex items-center justify-center" style={{ minHeight: height }}>
        <EmptyState compact title={emptyTitle} description={emptyDescription} icon={emptyIcon} art={emptyArt} />
      </div>
    );
  }
  return <>{children}</>;
}
