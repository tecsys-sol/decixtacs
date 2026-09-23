"use client";

import { ArrowRight, Columns2, FileDiff, Rows3 } from "lucide-react";
import * as React from "react";

import { Segmented } from "@/components/ui/tabs";
import type { DiffOut, DiffRow } from "@/lib/types";
import { cn, shortSha } from "@/lib/utils";

import { classifyUnifiedLine, intraline, toInlineRows, type InlineRowType } from "./diff-utils";
import { RiskPanel } from "./risk-panel";

export type DiffMode = "split" | "inline" | "unified";

const MODE_KEY = "nom.diff.mode";

const ROW_BG: Record<string, string> = {
  added: "bg-diff-add-bg",
  removed: "bg-diff-del-bg",
  modified: "bg-diff-mod-bg",
  "modified-old": "bg-diff-mod-bg",
  "modified-new": "bg-diff-mod-bg",
};

const ROW_FG: Record<string, string> = {
  added: "text-diff-add-fg",
  removed: "text-diff-del-fg",
  modified: "text-diff-mod-fg",
  "modified-old": "text-diff-mod-fg",
  "modified-new": "text-diff-mod-fg",
};

const MARK = "rounded-sm px-px [background:color-mix(in_srgb,currentColor_20%,transparent)]";

/** staggered slide-in for the first rows only, so long diffs do not keep animating */
function lineDelay(i: number): React.CSSProperties | undefined {
  return i < 40 ? { animationDelay: `${(i * 0.035).toFixed(3)}s` } : undefined;
}

function LineNo({ n, className }: { n: number | null | undefined; className?: string }) {
  return (
    <td
      className={cn(
        "w-[1%] select-none whitespace-nowrap pl-3 pr-2.5 text-right align-top text-label",
        className,
      )}
    >
      {n ?? ""}
    </td>
  );
}

function Highlighted({ parts }: { parts: [string, string, string] }) {
  return (
    <>
      {parts[0]}
      {parts[1] ? <mark className={cn("text-inherit", MARK)}>{parts[1]}</mark> : null}
      {parts[2]}
    </>
  );
}

function SkipRow({ count, colSpan }: { count: number; colSpan: number }) {
  return (
    <tr data-type="skip" className="bg-secondary text-ink-3">
      <td colSpan={colSpan} className="px-3 py-1 text-center font-sans text-[11.5px] font-semibold">
        ⋯ {count} unchanged line{count === 1 ? "" : "s"} ⋯
      </td>
    </tr>
  );
}

function SplitView({ rows, wrap }: { rows: DiffRow[]; wrap: boolean }) {
  const ws = wrap ? "whitespace-pre-wrap break-all" : "whitespace-pre";
  return (
    <table className="w-full min-w-[720px] table-fixed border-collapse font-mono text-[12.5px] leading-[1.75]" data-testid="diff-split">
      <colgroup>
        <col className="w-[52px]" />
        <col />
        <col className="w-[52px]" />
        <col />
      </colgroup>
      <tbody>
        {rows.map((r, i) => {
          if (r.type === "skip") return <SkipRow key={i} count={r.count ?? 0} colSpan={4} />;
          const parts = r.type === "modified" ? intraline(r.left ?? "", r.right ?? "") : null;
          const leftCls =
            r.type === "removed" || r.type === "modified" ? cn(ROW_BG[r.type], ROW_FG[r.type]) : r.type === "added" ? "bg-secondary/60" : "";
          const rightCls =
            r.type === "added" || r.type === "modified" ? cn(ROW_BG[r.type], ROW_FG[r.type]) : r.type === "removed" ? "bg-secondary/60" : "";
          return (
            <tr key={i} data-type={r.type} className="slide-line" style={lineDelay(i)}>
              <LineNo n={r.left_no} className={leftCls} />
              <td className={cn("overflow-hidden border-r border-border/70 pr-3 align-top", ws, leftCls)}>
                {r.left === null || r.left === undefined ? (
                  " "
                ) : (
                  <>
                    <span className="mr-1.5 inline-block w-3 select-none">{r.type === "removed" ? "−" : r.type === "modified" ? "~" : " "}</span>
                    {parts ? <Highlighted parts={parts.a} /> : r.left}
                  </>
                )}
              </td>
              <LineNo n={r.right_no} className={rightCls} />
              <td className={cn("overflow-hidden pr-3 align-top", ws, rightCls)}>
                {r.right === null || r.right === undefined ? (
                  " "
                ) : (
                  <>
                    <span className="mr-1.5 inline-block w-3 select-none">{r.type === "added" ? "+" : r.type === "modified" ? "~" : " "}</span>
                    {parts ? <Highlighted parts={parts.b} /> : r.right}
                  </>
                )}
              </td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

const INLINE_SIGN: Record<InlineRowType, string> = {
  equal: " ",
  added: "+",
  removed: "-",
  "modified-old": "-",
  "modified-new": "+",
  skip: "",
};

function InlineView({ rows, wrap }: { rows: DiffRow[]; wrap: boolean }) {
  const inline = React.useMemo(() => toInlineRows(rows), [rows]);
  const ws = wrap ? "whitespace-pre-wrap break-all" : "whitespace-pre";
  return (
    <table className="w-full border-collapse font-mono text-[12.5px] leading-[1.75]" data-testid="diff-inline">
      <tbody>
        {inline.map((r, i) => {
          if (r.type === "skip") return <SkipRow key={i} count={r.count ?? 0} colSpan={3} />;
          const cls = cn(ROW_BG[r.type], ROW_FG[r.type]);
          return (
            <tr key={i} data-type={r.type} className={cn("slide-line", cls)} style={lineDelay(i)}>
              <LineNo n={r.oldNo} />
              <LineNo n={r.newNo} />
              <td className={cn("w-full pr-3 align-top", ws)}>
                <span className="mr-1.5 inline-block w-3 select-none">{INLINE_SIGN[r.type]}</span>
                {r.text || " "}
              </td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

function UnifiedView({ unified, wrap }: { unified: string; wrap: boolean }) {
  const lines = React.useMemo(() => unified.replace(/\n$/, "").split("\n"), [unified]);
  const cls: Record<string, string> = {
    meta: "text-muted-foreground font-semibold",
    hunk: "bg-accent text-accent-foreground",
    added: "bg-diff-add-bg text-diff-add-fg",
    removed: "bg-diff-del-bg text-diff-del-fg",
    context: "",
  };
  return (
    <pre
      className={cn("font-mono text-[12.5px] leading-[1.75]", wrap ? "whitespace-pre-wrap break-all" : "whitespace-pre")}
      data-testid="diff-unified"
    >
      {lines.map((l, i) => {
        const t = classifyUnifiedLine(l);
        return (
          <div key={i} data-type={t} className={cn("slide-line px-4", cls[t])} style={lineDelay(i)}>
            {l || " "}
          </div>
        );
      })}
    </pre>
  );
}

function readSavedMode(): DiffMode {
  try {
    const saved = typeof window !== "undefined" ? window.localStorage.getItem(MODE_KEY) : null;
    if (saved === "split" || saved === "inline" || saved === "unified") return saved;
  } catch {
    /* storage unavailable */
  }
  return "split";
}

export interface DiffViewerProps {
  diff: DiffOut;
  mode?: DiffMode;
  onModeChange?: (m: DiffMode) => void;
  showRisk?: boolean;
  className?: string;
  maxHeight?: string;
  oldLabel?: string;
  newLabel?: string;
  /** commit message / context shown in the header */
  title?: string;
}

export function DiffViewer({
  diff,
  mode: controlledMode,
  onModeChange,
  showRisk = true,
  className,
  maxHeight = "70vh",
  oldLabel,
  newLabel,
  title,
}: DiffViewerProps) {
  const [localMode, setLocalMode] = React.useState<DiffMode>(readSavedMode);
  const [wrap, setWrap] = React.useState(false);
  const mode = controlledMode ?? localMode;

  const setMode = (m: DiffMode) => {
    if (onModeChange) onModeChange(m);
    else setLocalMode(m);
    try {
      window.localStorage.setItem(MODE_KEY, m);
    } catch {
      /* storage unavailable */
    }
  };

  const noChanges = diff.added === 0 && diff.removed === 0;

  return (
    <div className={cn("grid gap-3", className)}>
      {showRisk ? <RiskPanel risk={diff.risk} /> : null}
      <div className="overflow-hidden rounded-xl border bg-card">
        <div className="flex flex-wrap items-center gap-3 border-b border-border/70 px-4 py-3.5 sm:px-[18px]">
          <span className="rounded-sm bg-secondary px-2 py-1 font-mono text-[12.5px] text-ink-2">{oldLabel ?? shortSha(diff.old_rev)}</span>
          <ArrowRight className="h-4 w-4 text-muted-foreground" aria-label="to" />
          <span className="rounded-sm bg-accent px-2 py-1 font-mono text-[12.5px] text-accent-foreground">{newLabel ?? shortSha(diff.new_rev)}</span>
          <span className="font-mono text-xs font-bold text-diff-add-fg tabular" data-testid="diff-added">
            +{diff.added}
          </span>
          <span className="font-mono text-xs font-bold text-diff-del-fg tabular" data-testid="diff-removed">
            −{diff.removed}
          </span>
          {title ? <span className="min-w-0 truncate text-[13px] text-ink-3">{title}</span> : null}
          <div className="ml-auto flex flex-wrap items-center gap-3">
            <label className="flex cursor-pointer items-center gap-1.5 text-xs font-semibold text-ink-3">
              <input type="checkbox" checked={wrap} onChange={(e) => setWrap(e.target.checked)} className="h-3.5 w-3.5 accent-[hsl(var(--primary))]" />
              Wrap
            </label>
            <Segmented<DiffMode>
              aria-label="Diff view mode"
              value={mode}
              onChange={setMode}
              options={[
                { value: "split", label: <><Columns2 /> Side by side</> },
                { value: "inline", label: <><Rows3 /> Inline</> },
                { value: "unified", label: <><FileDiff /> Unified</> },
              ]}
            />
          </div>
        </div>
        <div className="overflow-auto scrollbar-thin" style={{ maxHeight }}>
          {noChanges ? (
            <p className="px-4 py-10 text-center text-sm text-ink-3">The two revisions are identical.</p>
          ) : mode === "split" ? (
            <SplitView rows={diff.side_by_side} wrap={wrap} />
          ) : mode === "inline" ? (
            <InlineView rows={diff.side_by_side} wrap={wrap} />
          ) : (
            <UnifiedView unified={diff.unified} wrap={wrap} />
          )}
        </div>
      </div>
    </div>
  );
}

/** Colourised plain unified diff (e.g. restore dry-run output from the device). */
export function UnifiedDiffBlock({ text, className, maxHeight = "50vh" }: { text: string; className?: string; maxHeight?: string }) {
  return (
    <div className={cn("overflow-auto rounded-xl border bg-card scrollbar-thin", className)} style={{ maxHeight }}>
      <UnifiedView unified={text} wrap={false} />
    </div>
  );
}
