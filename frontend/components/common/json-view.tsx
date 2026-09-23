import { cn } from "@/lib/utils";

export function JsonView({ value, className }: { value: unknown; className?: string }) {
  if (value === null || value === undefined) return <span className="text-xs text-muted-foreground">—</span>;
  return (
    <pre className={cn("max-h-80 overflow-auto rounded-md border bg-muted/40 p-2 font-mono text-[11px] leading-4 scrollbar-thin", className)}>
      {JSON.stringify(value, null, 2)}
    </pre>
  );
}
