import { cn } from "@/lib/utils";

export function Logo({ collapsed, className }: { collapsed?: boolean; className?: string }) {
  return (
    <div className={cn("flex items-center gap-2", className)}>
      <svg viewBox="0 0 32 32" className="h-7 w-7 shrink-0" aria-hidden>
        <rect width="32" height="32" rx="7" className="fill-primary" />
        <path d="M9 10L16 23L23 10Z" fill="none" stroke="white" strokeWidth="2" strokeLinejoin="round" />
        <circle cx="9" cy="10" r="3" fill="white" />
        <circle cx="23" cy="10" r="3" fill="white" />
        <circle cx="16" cy="23" r="3" fill="white" />
      </svg>
      {collapsed ? null : (
        <div className="leading-tight">
          <p className="text-sm font-semibold tracking-tight">NetworkOps</p>
          <p className="text-[10px] uppercase tracking-widest text-muted-foreground">Manager</p>
        </div>
      )}
    </div>
  );
}
