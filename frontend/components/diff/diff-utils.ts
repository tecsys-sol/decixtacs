import type { DiffRow } from "@/lib/types";

export type InlineRowType = "equal" | "added" | "removed" | "modified-old" | "modified-new" | "skip";

export interface InlineRow {
  type: InlineRowType;
  oldNo: number | null;
  newNo: number | null;
  text: string;
  count?: number;
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
        out.push({ type: "removed", oldNo: r.left_no ?? null, newNo: null, text: r.left ?? "" });
        break;
      case "added":
        out.push({ type: "added", oldNo: null, newNo: r.right_no ?? null, text: r.right ?? "" });
        break;
      case "modified":
        out.push({ type: "modified-old", oldNo: r.left_no ?? null, newNo: null, text: r.left ?? "" });
        out.push({ type: "modified-new", oldNo: null, newNo: r.right_no ?? null, text: r.right ?? "" });
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
