"use client";

import { Check, Copy, Download, Search, WrapText } from "lucide-react";
import * as React from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { toast } from "@/hooks/use-toast";
import { cn, copyToClipboard } from "@/lib/utils";

/** Monospace text viewer with line numbers, in-text filter highlight, copy and download. */
export function CodeViewer({
  content,
  filename,
  className,
  maxHeight = "70vh",
  highlightLines,
  toolbar = true,
}: {
  content: string;
  filename?: string;
  className?: string;
  maxHeight?: string;
  highlightLines?: Set<number>;
  toolbar?: boolean;
}) {
  const [wrap, setWrap] = React.useState(false);
  const [query, setQuery] = React.useState("");
  const [copied, setCopied] = React.useState(false);
  const lines = React.useMemo(() => content.replace(/\n$/, "").split("\n"), [content]);
  const q = query.trim().toLowerCase();
  const matches = React.useMemo(
    () => (q ? lines.reduce((n, l) => n + (l.toLowerCase().includes(q) ? 1 : 0), 0) : 0),
    [lines, q],
  );
  const width = String(lines.length).length;

  const copy = async () => {
    try {
      await copyToClipboard(content);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch (e) {
      toast.error("Copy failed", e);
    }
  };

  const download = () => {
    const url = URL.createObjectURL(new Blob([content], { type: "text/plain" }));
    const a = document.createElement("a");
    a.href = url;
    a.download = filename ?? "config.txt";
    a.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  };

  return (
    <div className={cn("overflow-hidden rounded-xl border bg-card", className)}>
      {toolbar ? (
        <div className="flex flex-wrap items-center gap-2 border-b border-border/70 px-3 py-2">
          <div className="relative w-full max-w-xs">
            <Search className="pointer-events-none absolute left-2 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
            <Input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Find in file"
              className="h-8 pl-7 text-xs"
              aria-label="Find in file"
            />
          </div>
          {q ? <span className="text-xs font-semibold text-ink-3">{matches} matching line(s)</span> : null}
          <span className="ml-auto text-xs text-muted-foreground tabular">{lines.length} lines</span>
          <Button variant="ghost" size="icon-sm" onClick={() => setWrap((w) => !w)} aria-pressed={wrap} aria-label="Toggle line wrap">
            <WrapText />
          </Button>
          <Button variant="ghost" size="icon-sm" onClick={copy} aria-label="Copy to clipboard">
            {copied ? <Check /> : <Copy />}
          </Button>
          <Button variant="ghost" size="icon-sm" onClick={download} aria-label="Download">
            <Download />
          </Button>
        </div>
      ) : null}
      <div className="overflow-auto scrollbar-thin" style={{ maxHeight }}>
        <table className="w-full border-collapse font-mono text-[12.5px] leading-[1.75]">
          <tbody>
            {lines.map((line, i) => {
              const hit = q && line.toLowerCase().includes(q);
              return (
                <tr
                  key={i}
                  className={cn(hit && "bg-diff-mod-bg", highlightLines?.has(i + 1) && "bg-accent")}
                >
                  <td
                    className="select-none pl-3 pr-2.5 text-right align-top text-label"
                    style={{ width: `${width + 2}ch` }}
                  >
                    {i + 1}
                  </td>
                  <td className={cn("px-3 align-top", wrap ? "whitespace-pre-wrap break-all" : "whitespace-pre")}>
                    {line || " "}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
