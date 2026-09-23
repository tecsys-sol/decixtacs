import { AlertTriangle, ShieldAlert, ShieldCheck } from "lucide-react";

import { Badge, type BadgeVariant } from "@/components/ui/badge";
import type { RiskReport } from "@/lib/types";
import { cn } from "@/lib/utils";

const LEVEL_VARIANT: Record<string, BadgeVariant> = {
  low: "success",
  medium: "warning",
  high: "danger",
  critical: "danger",
};

export function RiskBadge({ score, level, className }: { score: number | null | undefined; level?: string; className?: string }) {
  if (score === null || score === undefined) return <Badge variant="muted">No risk score</Badge>;
  const lvl = level ?? (score >= 70 ? "critical" : score >= 40 ? "high" : score >= 15 ? "medium" : "low");
  const Icon = lvl === "low" ? ShieldCheck : lvl === "medium" ? AlertTriangle : ShieldAlert;
  return (
    <Badge variant={LEVEL_VARIANT[lvl] ?? "secondary"} className={cn(lvl === "critical" && "ring-1 ring-destructive/50", className)}>
      <Icon /> Risk {score} · {lvl}
    </Badge>
  );
}

export function RiskPanel({ risk, className }: { risk: RiskReport; className?: string }) {
  return (
    <div className={cn("rounded-lg border bg-card p-3", className)} data-testid="risk-panel">
      <div className="flex flex-wrap items-center gap-2">
        <RiskBadge score={risk.score} level={risk.level} />
        <p className="text-sm text-muted-foreground">{risk.summary}</p>
      </div>
      {risk.findings.length ? (
        <ul className="mt-2 grid gap-1">
          {risk.findings.map((f, i) => {
            const idx = f.indexOf(":");
            const head = idx > 0 ? f.slice(0, idx) : f;
            const tail = idx > 0 ? f.slice(idx + 1).trim() : "";
            return (
              <li key={i} className="flex items-start gap-2 text-xs">
                <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-warning" aria-hidden />
                <span>
                  <span className="font-medium">{head}</span>
                  {tail ? <code className="ml-1.5 break-all rounded bg-muted px-1 py-0.5 font-mono text-[11px]">{tail}</code> : null}
                </span>
              </li>
            );
          })}
        </ul>
      ) : (
        <p className="mt-2 text-xs text-muted-foreground">No risky patterns detected.</p>
      )}
    </div>
  );
}
