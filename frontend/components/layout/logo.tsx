import { cn } from "@/lib/utils";

/**
 * Brand mark. Aurora: white network glyph on the brand tile. Meridian: a line-drawn globe with a
 * meridian. Both are rendered and the design variant hides one, so server-rendered pages
 * (login) show the right mark before hydration.
 */
export function LogoMark({ className }: { className?: string }) {
  return (
    <>
      <span
        className={cn("flex h-[34px] w-[34px] shrink-0 items-center justify-center rounded-[10px] bg-[#5b4ee6] meridian:hidden", className)}
        aria-hidden
      >
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#ffffff" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <circle cx="5" cy="12" r="2.5" />
          <circle cx="19" cy="5" r="2.5" />
          <circle cx="19" cy="19" r="2.5" />
          <path d="M7.3 11 16.7 6M7.3 13l9.4 5" />
        </svg>
      </span>
      <span className={cn("hidden h-[34px] w-[34px] shrink-0 items-center justify-center meridian:flex", className)} aria-hidden>
        <svg width="30" height="30" viewBox="0 0 32 32" fill="none" className="stroke-primary">
          <circle cx="16" cy="16" r="14" strokeWidth="2.4" />
          <path d="M2 16h28M16 2c5 5 5 23 0 28M16 2c-5 5-5 23 0 28" strokeWidth="2" />
        </svg>
      </span>
    </>
  );
}

export function Logo({ collapsed, className, subtitle = "Manager" }: { collapsed?: boolean; className?: string; subtitle?: string }) {
  return (
    <div className={cn("flex items-center gap-2.5", className)}>
      <LogoMark />
      {collapsed ? null : (
        <div className="flex min-w-0 flex-col leading-tight">
          <span className="font-display text-[15px] font-bold text-foreground meridian:text-[19px] meridian:font-semibold meridian:tracking-[-0.01em]">NetworkOps</span>
          <span className="truncate text-[11.5px] text-muted-foreground">{subtitle}</span>
        </div>
      )}
    </div>
  );
}
