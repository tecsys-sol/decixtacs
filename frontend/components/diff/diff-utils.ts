import type { Attribution, DiffRow } from "@/lib/types";

export type InlineRowType = "equal" | "added" | "removed" | "modified-old" | "modified-new" | "skip";

export interface InlineRow {
  type: InlineRowType;
  oldNo: number | null;
  newNo: number | null;
  text: string;
  count?: number;
  by?: Attribution | null;
}

/** Flatten side-by-side rows into a single-column (inline) diff. Modified rows become an old/new pair. */
export function toInlineRows(rows: DiffRow[]): InlineRow[] {
  const out: InlineRow[] = [];
  for (const r of rows) {
    switch (r.type) {
      case "equal":
        out.push({ type: "equal", oldNo: r.left_no ?? null, newNo: r.right_no ?? null, text: r.right ?? r.left ?? "" });
        break;
      case "removed":
        out.push({ type: "removed", oldNo: r.left_no ?? null, newNo: null, text: r.left ?? "", by: r.left_by });
        break;
      case "added":
        out.push({ type: "added", oldNo: null, newNo: r.right_no ?? null, text: r.right ?? "", by: r.right_by });
        break;
      case "modified":
        out.push({ type: "modified-old", oldNo: r.left_no ?? null, newNo: null, text: r.left ?? "", by: r.left_by });
        out.push({ type: "modified-new", oldNo: null, newNo: r.right_no ?? null, text: r.right ?? "", by: r.right_by });
        break;
      case "skip":
        out.push({ type: "skip", oldNo: null, newNo: null, text: "", count: r.count ?? 0 });
        break;
    }
  }
  return out;
}

/**
 * Split two strings into [common prefix, changed middle, common suffix] so that the changed
 * part of a modified line can be emphasised.
 */
export function intraline(a: string, b: string): { a: [string, string, string]; b: [string, string, string] } {
  let p = 0;
  const max = Math.min(a.length, b.length);
  while (p < max && a[p] === b[p]) p++;
  let s = 0;
  while (s < max - p && a[a.length - 1 - s] === b[b.length - 1 - s]) s++;
  return {
    a: [a.slice(0, p), a.slice(p, a.length - s), a.slice(a.length - s)],
    b: [b.slice(0, p), b.slice(p, b.length - s), b.slice(b.length - s)],
  };
}

export type UnifiedLineType = "meta" | "hunk" | "added" | "removed" | "context";

export function classifyUnifiedLine(line: string): UnifiedLineType {
  if (line.startsWith("+++") || line.startsWith("---")) return "meta";
  if (line.startsWith("@@")) return "hunk";
  if (line.startsWith("+")) return "added";
  if (line.startsWith("-")) return "removed";
  return "context";
}

/** Distinct colours for engineers - deliberately not green/red so they never read as added/removed. */
export const STAFF_COLORS = ["#7c3aed", "#0284c7", "#d97706", "#db2777", "#0d9488", "#4f46e5", "#c2410c", "#65a30d"];

export function staffColorMap(usernames: string[]): Map<string, string> {
  const m = new Map<string, string>();
  usernames.forEach((u, i) => m.set(u, STAFF_COLORS[i % STAFF_COLORS.length]));
  return m;
}

export function initials(name: string): string {
  const parts = name.split(/[\s._-]+/).filter(Boolean);
  return ((parts[0]?.[0] ?? "") + (parts[1]?.[0] ?? parts[0]?.[1] ?? "")).toUpperCase() || "?";
}
