import type { BadgeVariant } from "@/components/ui/badge";

const MAP: Record<string, BadgeVariant> = {
  // generic success
  success: "success",
  ok: "success",
  up: "success",
  reachable: "success",
  active: "success",
  pass: "success",
  passed: "success",
  permit: "success",
  accepted: "success",
  established: "success",
  valid: "success",
  approved: "success",
  implemented: "info",
  closed: "muted",
  pushed: "success",
  diffed: "info",
  unchanged: "muted",
  // warnings
  warning: "warning",
  degraded: "warning",
  pending: "warning",
  pending_approval: "warning",
  running: "info",
  queued: "info",
  draft: "muted",
  partial: "warning",
  planned: "info",
  staged: "info",
  maintenance: "warning",
  not_found: "warning",
  unknown: "muted",
  // failures
  failed: "danger",
  failure: "danger",
  error: "danger",
  down: "danger",
  unreachable: "danger",
  deny: "danger",
  denied: "danger",
  reject: "danger",
  rejected: "danger",
  fail: "danger",
  invalid: "danger",
  cancelled: "muted",
  offline: "danger",
  decommissioned: "muted",
  inventory: "muted",
  // severities
  info: "info",
  low: "info",
  medium: "warning",
  high: "danger",
  critical: "danger",
};

export function statusVariant(status: string | null | undefined): BadgeVariant {
  if (!status) return "muted";
  return MAP[status.toLowerCase()] ?? "secondary";
}

export function riskLevel(score: number | null | undefined): "low" | "medium" | "high" | "critical" {
  const s = score ?? 0;
  return s >= 70 ? "critical" : s >= 40 ? "high" : s >= 15 ? "medium" : "low";
}

export function scoreColor(score: number | null | undefined): string {
  if (score === null || score === undefined) return "text-muted-foreground";
  if (score >= 90) return "text-success";
  if (score >= 70) return "text-warning";
  return "text-destructive";
}
