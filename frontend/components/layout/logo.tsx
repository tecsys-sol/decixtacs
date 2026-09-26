import Image from "next/image";

import { cn } from "@/lib/utils";

/** DE-CIX mark on a white tile, so the navy half stays legible on dark sidebars and in dark mode. */
export function LogoMark({ className }: { className?: string }) {
  return (
    <span
      className={cn("flex h-[34px] w-[34px] shrink-0 items-center justify-center rounded-[10px] bg-white ring-1 ring-black/5 dark:ring-white/10", className)}
      aria-hidden
    >
      <Image src="/brand/decix-mark.png" alt="" width={24} height={24} priority />
    </span>
  );
}

/** Full DE-CIX logo (mark + wordmark), e.g. on the sign-in page. */
export function BrandLogo({ className, height = 88 }: { className?: string; height?: number }) {
  return (
    <span className={cn("inline-flex rounded-2xl bg-white p-3 ring-1 ring-black/5 dark:ring-white/10", className)}>
      <Image src="/brand/decix-logo.png" alt="DE-CIX" width={Math.round((height * 482) / 441)} height={height} priority />
    </span>
  );
}

export function Logo({ collapsed, className, subtitle = "NetworkOps Manager" }: { collapsed?: boolean; className?: string; subtitle?: string }) {
  return (
    <div className={cn("flex items-center gap-2.5", className)}>
      <LogoMark />
      {collapsed ? null : (
        <div className="flex min-w-0 flex-col leading-tight">
          <span className="font-display text-[15px] font-bold text-foreground meridian:text-[19px] meridian:font-semibold meridian:tracking-[-0.01em]">DE-CIX</span>
          <span className="truncate text-[11.5px] text-muted-foreground">{subtitle}</span>
        </div>
      )}
    </div>
  );
}
