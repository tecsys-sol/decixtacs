import type { ReportJson } from "@/lib/types";
import { humanize } from "@/lib/utils";

/**
 * Pick a chartable view of a report: the first text column as category and the first numeric column
 * as value (summed per category); without a numeric column, rows are counted per category.
 */
export function reportPreview(data: ReportJson): { categoryLabel: string; valueLabel: string; items: { name: string; value: number }[]; folded: boolean } | null {
  if (!data.rows.length || !data.columns.length) return null;
  const isNum = (j: number) => data.rows.every((r) => r[j] === null || typeof r[j] === "number") && data.rows.some((r) => typeof r[j] === "number");
  const isText = (j: number) => data.rows.some((r) => typeof r[j] === "string" && r[j] !== "");
  const cat = data.columns.findIndex((_, j) => isText(j) && !/time|date|at$|timestamp|start|end/i.test(data.columns[j]));
  if (cat < 0) return null;
  const val = data.columns.findIndex((_, j) => j !== cat && isNum(j));
  const sums = new Map<string, number>();
  for (const r of data.rows) {
    const k = String(r[cat] ?? "—");
    sums.set(k, (sums.get(k) ?? 0) + (val >= 0 ? Number(r[val] ?? 0) : 1));
  }
  const sorted = [...sums.entries()].map(([name, value]) => ({ name, value })).sort((a, b) => b.value - a.value);
  if (sorted.length < 1) return null;
  return {
    categoryLabel: data.columns[cat].toLowerCase(),
    valueLabel: val >= 0 ? humanize(data.columns[val]) : "Rows",
    items: sorted.slice(0, 12),
    folded: sorted.length > 12,
  };
}
