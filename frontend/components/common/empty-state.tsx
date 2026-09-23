import { Inbox, type LucideIcon } from "lucide-react";

import { EmptyScene, type EmptyArt } from "@/components/illustrations";
import { cn } from "@/lib/utils";

/** Illustrated empty state: an animated line-art scene with the context icon, a title and a hint. */
export function EmptyState({
  title,
  description,
  icon = Inbox,
  art = "default",
  action,
  compact,
  className,
}: {
  title: string;
  description?: React.ReactNode;
  icon?: LucideIcon;
  art?: EmptyArt;
  action?: React.ReactNode;
  /** tighter spacing for use inside chart cards */
  compact?: boolean;
  className?: string;
}) {
  return (
    <div
      className={cn("flex flex-col items-center justify-center gap-2 px-4 text-center", compact ? "py-4" : "py-10", className)}
      data-testid="empty-state"
    >
      <EmptyScene art={art} icon={icon} className={compact ? "scale-90" : undefined} />
      <p className="font-display text-[15px] font-semibold text-foreground">{title}</p>
      {description ? <p className="max-w-sm text-[13px] leading-relaxed text-muted-foreground">{description}</p> : null}
      {action ? <div className="mt-2">{action}</div> : null}
    </div>
  );
}
