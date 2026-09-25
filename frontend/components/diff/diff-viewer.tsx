"use client";

import { ArrowRight, Columns2, FileDiff, Rows3, Terminal, UserRound } from "lucide-react";
import * as React from "react";

import { Segmented } from "@/components/ui/tabs";
import type { Attribution, DiffAuthor, DiffOut, DiffRow } from "@/lib/types";
import { cn, formatDateTime, shortSha } from "@/lib/utils";

import { classifyUnifiedLine, initials, intraline, staffColorMap, toInlineRows, type InlineRowType } from "./diff-utils";
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

/** How rows are coloured by engineer; ``colors`` is empty when colouring is off. */
interface Staff {
  colors: Map<string, string>;
  focus: string | null;
}

const NO_STAFF: Staff = { colors: new Map(), focus: null };

function staffStyle(by: Attribution | null | undefined, staff: Staff): React.CSSProperties | undefined {
  const c = by ? staff.colors.get(by.user) : undefined;
  if (!by || !c) return undefined;
  const dim = staff.focus !== null && staff.focus !== by.user;
  const tint = `color-mix(in srgb, ${c} ${dim ? 5 : 16}%, transparent)`;
  return {
    background:
      by.confidence === "inferred"
        ? `repeating-linear-gradient(135deg, ${tint} 0 7px, color-mix(in srgb, ${c} ${dim ? 2 : 7}%, transparent) 7px 14px)`
        : tint,
    boxShadow: `inset 3px 0 0 ${dim ? "transparent" : c}`,
    opacity: dim ? 0.55 : undefined,
  };
}

function byTitle(by: Attribution): string {
  return `${by.user} · ${formatDateTime(by.at)}\n${by.command}${by.confidence === "inferred" ? "\n(inferred: only engineer configuring this device in the window)" : ""}`;
}

function AuthorChip({ by, staff }: { by: Attribution | null | undefined; staff: Staff }) {
  const c = by ? staff.colors.get(by.user) : undefined;
  if (!by || !c) return null;
  return (
    <span
      className={cn(
        "inline-flex h-[18px] min-w-[18px] items-center justify-center rounded-full px-1 font-sans text-[9.5px] font-bold leading-none text-white",
        by.confidence === "inferred" && "ring-1 ring-inset ring-white/70",
      )}
      style={{ backgroundColor: c, opacity: staff.focus !== null && staff.focus !== by.user ? 0.4 : 1 }}
      title={byTitle(by)}
      aria-label={`Changed by ${by.user}${by.confidence === "inferred" ? " (inferred)" : ""}`}
      data-testid="diff-author-chip"
    >
      {initials(by.user)}
    </span>
  );
}

function LineNo({ n, className, style }: { n: number | null | undefined; className?: string; style?: React.CSSProperties }) {
  return (
    <td
      className={cn(
        "w-[1%] select-none whitespace-nowrap pl-3 pr-2.5 text-right align-top text-label",
        className,
      )}
      style={style}
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

function SplitView({ rows, wrap, staff }: { rows: DiffRow[]; wrap: boolean; staff: Staff }) {
  const attributed = staff.colors.size > 0;
  const ws = wrap ? "whitespace-pre-wrap break-all" : "whitespace-pre";
  return (
    <table className="w-full min-w-[720px] table-fixed border-collapse font-mono text-[12.5px] leading-[1.75]" data-testid="diff-split">
      <colgroup>
        <col className="w-[52px]" />
        <col />
        <col className="w-[52px]" />
        <col />
        {attributed ? <col className="w-[34px]" /> : null}
      </colgroup>
      <tbody>
        {rows.map((r, i) => {
          if (r.type === "skip") return <SkipRow key={i} count={r.count ?? 0} colSpan={attributed ? 5 : 4} />;
          const lStyle = staffStyle(r.left_by, staff);
          const rStyle = staffStyle(r.right_by, staff);
          const who = r.right_by ?? r.left_by;
          const parts = r.type === "modified" ? intraline(r.left ?? "", r.right ?? "") : null;
          const leftCls =
            r.type === "removed" || r.type === "modified" ? cn(ROW_BG[r.type], ROW_FG[r.type]) : r.type === "added" ? "bg-secondary/60" : "";
          const rightCls =
            r.type === "added" || r.type === "modified" ? cn(ROW_BG[r.type], ROW_FG[r.type]) : r.type === "removed" ? "bg-secondary/60" : "";
          return (
            <tr key={i} data-type={r.type} className="slide-line" style={lineDelay(i)}>
              <LineNo n={r.left_no} className={leftCls} style={lStyle} />
              <td className={cn("overflow-hidden border-r border-border/70 pr-3 align-top", ws, leftCls)} style={lStyle && { ...lStyle, boxShadow: undefined }}>
                {r.left === null || r.left === undefined ? (
                  " "
                ) : (
                  <>
                    <span className="mr-1.5 inline-block w-3 select-none">{r.type === "removed" ? "−" : r.type === "modified" ? "~" : " "}</span>
                    {parts ? <Highlighted parts={parts.a} /> : r.left}
                  </>
                )}
              </td>
              <LineNo n={r.right_no} className={rightCls} style={rStyle} />
              <td className={cn("overflow-hidden pr-3 align-top", ws, rightCls)} style={rStyle && { ...rStyle, boxShadow: undefined }}>
                {r.right === null || r.right === undefined ? (
                  " "
                ) : (
                  <>
                    <span className="mr-1.5 inline-block w-3 select-none">{r.type === "added" ? "+" : r.type === "modified" ? "~" : " "}</span>
                    {parts ? <Highlighted parts={parts.b} /> : r.right}
                  </>
                )}
              </td>
              {attributed ? (
                <td className="px-1 text-center align-top">
                  <AuthorChip by={who} staff={staff} />
                  {r.left_by && r.right_by && r.left_by.user !== r.right_by.user ? <AuthorChip by={r.left_by} staff={staff} /> : null}
                </td>
              ) : null}
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

function InlineView({ rows, wrap, staff }: { rows: DiffRow[]; wrap: boolean; staff: Staff }) {
  const attributed = staff.colors.size > 0;
  const inline = React.useMemo(() => toInlineRows(rows), [rows]);
  const ws = wrap ? "whitespace-pre-wrap break-all" : "whitespace-pre";
  return (
    <table className="w-full border-collapse font-mono text-[12.5px] leading-[1.75]" data-testid="diff-inline">
      <tbody>
        {inline.map((r, i) => {
          if (r.type === "skip") return <SkipRow key={i} count={r.count ?? 0} colSpan={attributed ? 4 : 3} />;
          const cls = cn(ROW_BG[r.type], ROW_FG[r.type]);
          const st = staffStyle(r.by, staff);
          return (
            <tr key={i} data-type={r.type} className={cn("slide-line", cls)} style={{ ...lineDelay(i), ...st }}>
              <LineNo n={r.oldNo} />
              <LineNo n={r.newNo} />
              <td className={cn("w-full pr-3 align-top", ws)}>
                <span className="mr-1.5 inline-block w-3 select-none">{INLINE_SIGN[r.type]}</span>
                {r.text || " "}
              </td>
              {attributed ? (
                <td className="w-[34px] px-1 text-center align-top">
                  <AuthorChip by={r.by} staff={staff} />
                </td>
              ) : null}
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
  const authors = React.useMemo(() => diff.authors ?? [], [diff.authors]);
  const [byStaff, setByStaff] = React.useState(true);
  const [focus, setFocus] = React.useState<string | null>(null);
  const colors = React.useMemo(() => staffColorMap(authors.map((a) => a.username)), [authors]);
  const staff: Staff = React.useMemo(
    () => (byStaff && authors.length ? { colors, focus: focus && colors.has(focus) ? focus : null } : NO_STAFF),
    [byStaff, authors.length, colors, focus],
  );
  const unattributed = React.useMemo(
    () =>
      diff.side_by_side.reduce(
        (n, r) => n + (r.type === "added" || r.type === "removed" || r.type === "modified" ? (r.right_by || r.left_by ? 0 : 1) : 0),
        0,
      ),
    [diff.side_by_side],
  );

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
        {diff.attributed && !noChanges ? (
          <AuthorLegend
            authors={authors}
            colors={colors}
            on={byStaff}
            onToggle={setByStaff}
            focus={staff.focus}
            onFocus={(u) => setFocus((f) => (f === u ? null : u))}
            unattributed={unattributed}
            commands={diff.commands ?? []}
            unifiedMode={mode === "unified"}
          />
        ) : null}
        <div className="overflow-auto scrollbar-thin" style={{ maxHeight }}>
          {noChanges ? (
            <p className="px-4 py-10 text-center text-sm text-ink-3">The two revisions are identical.</p>
          ) : mode === "split" ? (
            <SplitView rows={diff.side_by_side} wrap={wrap} staff={staff} />
          ) : mode === "inline" ? (
            <InlineView rows={diff.side_by_side} wrap={wrap} staff={staff} />
          ) : (
            <UnifiedView unified={diff.unified} wrap={wrap} />
          )}
        </div>
      </div>
    </div>
  );
}

function AuthorLegend({
  authors,
  colors,
  on,
  onToggle,
  focus,
  onFocus,
  unattributed,
  commands,
  unifiedMode,
}: {
  authors: DiffAuthor[];
  colors: Map<string, string>;
  on: boolean;
  onToggle: (v: boolean) => void;
  focus: string | null;
  onFocus: (u: string) => void;
  unattributed: number;
  commands: { user: string; at: string; command: string }[];
  unifiedMode: boolean;
}) {
  return (
    <div className="grid gap-2 border-b border-border/70 bg-secondary/40 px-4 py-2.5 sm:px-[18px]" data-testid="diff-authors">
      <div className="flex flex-wrap items-center gap-2 text-xs">
        <span className="inline-flex items-center gap-1 font-semibold text-ink-3">
          <UserRound className="h-3.5 w-3.5" /> Changed by
        </span>
        {authors.length === 0 ? (
          <span className="text-ink-3">no logged command explains these lines (changed outside TACACS+ accounting, e.g. a local account or NETCONF)</span>
        ) : (
          authors.map((a) => {
            const c = colors.get(a.username);
            const active = focus === a.username;
            return (
              <button
                key={a.username}
                type="button"
                onClick={() => onFocus(a.username)}
                aria-pressed={active}
                disabled={!on}
                title={`${formatDateTime(a.first_at)} - ${formatDateTime(a.last_at)}${a.inferred ? ` · ${a.inferred} line(s) inferred` : ""}. Click to highlight only this engineer.`}
                className={cn(
                  "inline-flex items-center gap-1.5 rounded-full border bg-card px-2 py-0.5 font-medium transition-colors hover:bg-row-hover focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-60",
                  active && "ring-2",
                )}
                style={active && c ? ({ ["--tw-ring-color" as string]: c } as React.CSSProperties) : undefined}
              >
                <span className="h-2.5 w-2.5 rounded-full" style={{ backgroundColor: c }} aria-hidden />
                {a.username}
                <span className="font-mono text-diff-add-fg">+{a.added}</span>
                <span className="font-mono text-diff-del-fg">−{a.removed}</span>
              </button>
            );
          })
        )}
        {unattributed ? (
          <span className="inline-flex items-center gap-1.5 rounded-full border border-dashed px-2 py-0.5 text-ink-3" title="Changed lines no logged command explains">
            <span className="h-2.5 w-2.5 rounded-full bg-diff-add-fg/40" aria-hidden />
            unattributed {unattributed}
          </span>
        ) : null}
        {authors.length ? (
          <label className="ml-auto flex cursor-pointer items-center gap-1.5 font-semibold text-ink-3">
            <input type="checkbox" checked={on} onChange={(e) => onToggle(e.target.checked)} className="h-3.5 w-3.5 accent-[hsl(var(--primary))]" />
            Colour by engineer
          </label>
        ) : null}
      </div>
      {authors.length && on ? (
        <p className="text-[11px] text-ink-3">
          Solid tint: a logged command produced the line · striped: inferred (only engineer configuring the device then) · hover a badge for the command.
          {unifiedMode ? " Engineer colours show in the side-by-side and inline views." : ""}
        </p>
      ) : null}
      {commands.length ? (
        <details className="text-xs">
          <summary className="inline-flex cursor-pointer items-center gap-1 font-semibold text-ink-3">
            <Terminal className="h-3.5 w-3.5" /> {commands.length} logged command{commands.length === 1 ? "" : "s"} between these revisions
          </summary>
          <ol className="mt-1.5 max-h-56 overflow-y-auto rounded-md border bg-card font-mono text-[11.5px] scrollbar-thin" data-testid="diff-commands">
            {commands.map((c, i) => (
              <li key={i} className="flex gap-2 border-b border-border/50 px-2 py-1 last:border-0">
                <span className="shrink-0 text-ink-3">{formatDateTime(c.at)}</span>
                <span className="shrink-0 font-sans font-semibold" style={{ color: colors.get(c.user) }}>
                  {c.user}
                </span>
                <span className="min-w-0 break-all">{c.command}</span>
              </li>
            ))}
          </ol>
        </details>
      ) : null}
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
