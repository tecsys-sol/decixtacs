import { Check, Circle, X } from "lucide-react";

import type { ChangeDetail } from "@/lib/types";
import { cn, formatDateTime, humanize } from "@/lib/utils";

const HAPPY_PATH = ["draft", "pending_approval", "approved", "implemented", "closed"] as const;

/** Horizontal lifecycle indicator: draft -> pending approval -> approved -> implemented -> closed. */
export function StateTimeline({ detail }: { detail: ChangeDetail }) {
  const { change, comments } = detail;
  const terminalOff = change.state === "rejected" || change.state === "cancelled";
  // Where did the change leave the happy path? Use the last transition comment "from->to".
  const lastFrom = [...comments].reverse().find((c) => c.transition?.endsWith(`->${change.state}`))?.transition?.split("->")[0];
  const reachedIdx = terminalOff
    ? Math.max(0, HAPPY_PATH.indexOf((lastFrom as (typeof HAPPY_PATH)[number]) ?? "draft"))
    : HAPPY_PATH.indexOf(change.state as (typeof HAPPY_PATH)[number]);

  const when: Record<string, string | null> = {
    draft: change.created_at,
    pending_approval: comments.find((c) => c.transition?.endsWith("->pending_approval"))?.created_at ?? null,
    approved: change.approved_at,
    implemented: change.implemented_at,
    closed: change.closed_at,
  };

  return (
    <ol className="flex flex-wrap items-start gap-y-3" aria-label="Change lifecycle">
      {HAPPY_PATH.map((s, i) => {
        const done = i < reachedIdx || (!terminalOff && i === reachedIdx);
        const current = !terminalOff && i === reachedIdx;
        return (
          <li key={s} className="flex min-w-[120px] flex-1 items-start">
            <div className="flex flex-col items-center gap-1 text-center">
              <span
                className={cn(
                  "flex h-7 w-7 items-center justify-center rounded-full border-2",
                  done ? "border-primary bg-primary text-primary-foreground" : "border-border text-muted-foreground",
                  current && "ring-4 ring-primary/20",
                )}
              >
                {done && !current ? <Check className="h-3.5 w-3.5" /> : <Circle className="h-2.5 w-2.5 fill-current" />}
              </span>
              <span className={cn("text-xs font-medium", !done && "text-muted-foreground")}>{humanize(s)}</span>
              <span className="text-[10px] text-muted-foreground">{when[s] && done ? formatDateTime(when[s]) : ""}</span>
            </div>
            {i < HAPPY_PATH.length - 1 ? <div className={cn("mt-3.5 h-0.5 flex-1", i < reachedIdx ? "bg-primary" : "bg-border")} /> : null}
          </li>
        );
      })}
      {terminalOff ? (
        <li className="flex min-w-[120px] flex-col items-center gap-1 text-center">
          <span className="flex h-7 w-7 items-center justify-center rounded-full border-2 border-destructive bg-destructive text-destructive-foreground ring-4 ring-destructive/20">
            <X className="h-3.5 w-3.5" />
          </span>
          <span className="text-xs font-medium text-destructive">{humanize(change.state)}</span>
        </li>
      ) : null}
    </ol>
  );
}
