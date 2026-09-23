"use client";

import { Check, Laptop, Moon, Palette, Sun } from "lucide-react";
import { useTheme } from "next-themes";

import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuLabel,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { useDesign } from "@/hooks/use-design";
import { DESIGN_META, DESIGNS, type ColorMode, type Design } from "@/lib/theme";
import { cn } from "@/lib/utils";

export const COLOR_MODES = [
  { value: "light", label: "Light", icon: Sun },
  { value: "dark", label: "Dark", icon: Moon },
  { value: "system", label: "System", icon: Laptop },
] as const;

/**
 * Miniature of a design in one colour mode, drawn with that design's fixed preview colours (not
 * the active theme's), so both designs can be compared side by side.
 */
export function DesignPreview({ design, mode, className }: { design: Design; mode: ColorMode; className?: string }) {
  const c = DESIGN_META[design].preview[mode];
  const meridian = design === "meridian";
  const r = meridian ? 7 : 4;
  return (
    <svg viewBox="0 0 120 72" className={className} aria-hidden focusable="false">
      <rect width="120" height="72" fill={c.page} />
      {meridian ? (
        <>
          {/* top pill navigation */}
          <circle cx="10" cy="9" r="4" fill="none" stroke={c.primary} strokeWidth="1.4" />
          <rect x="19" y="5" width="18" height="8" rx="4" fill={c.ink} />
          <rect x="40" y="6.5" width="14" height="5" rx="2.5" fill={c.border} />
          <rect x="57" y="6.5" width="14" height="5" rx="2.5" fill={c.border} />
          <text x="8" y="30" fontFamily="Georgia, serif" fontSize="11" fontWeight="600" fill={c.ink}>
            Aa <tspan fontStyle="italic" fill={c.primary}>steady</tspan>
          </text>
          <rect x="8" y="36" width="44" height="3" rx="1.5" fill={c.muted} opacity=".55" />
          <rect x="8" y="44" width="22" height="7" rx="3.5" fill={c.primary} />
          <rect x="66" y="20" width="46" height="31" rx={r} fill={c.surface} stroke={c.border} />
          <circle cx="89" cy="35" r="9" fill="none" stroke={c.primary} strokeWidth="1.3" />
          <circle cx="89" cy="26" r="2.2" fill={c.accent} />
          <rect x="8" y="57" width="104" height="11" rx={r} fill={c.surface} stroke={c.border} />
        </>
      ) : (
        <>
          {/* left sidebar */}
          <rect width="28" height="72" fill={c.surface} />
          <rect x="28" width="0.8" height="72" fill={c.border} />
          <rect x="5" y="5" width="8" height="8" rx="2.5" fill={c.primary} />
          <rect x="5" y="18" width="18" height="4" rx="2" fill={c.primary} opacity=".25" />
          <rect x="5" y="26" width="15" height="3" rx="1.5" fill={c.muted} opacity=".45" />
          <rect x="5" y="32" width="17" height="3" rx="1.5" fill={c.muted} opacity=".45" />
          <rect x="5" y="38" width="13" height="3" rx="1.5" fill={c.muted} opacity=".45" />
          <rect x="34" y="6" width="80" height="24" rx={r} fill={c.surface} stroke={c.border} />
          <text x="39" y="20" fontFamily="system-ui, sans-serif" fontSize="9" fontWeight="700" fill={c.ink}>
            Aa
          </text>
          <rect x="54" y="14" width="30" height="3" rx="1.5" fill={c.muted} opacity=".55" />
          <path d="M92 22 100 14 108 19" fill="none" stroke={c.primary} strokeWidth="1.6" />
          <rect x="34" y="35" width="38" height="31" rx={r} fill={c.surface} stroke={c.border} />
          <rect x="76" y="35" width="38" height="31" rx={r} fill={c.surface} stroke={c.border} />
          <rect x="40" y="52" width="5" height="9" rx="1" fill={c.primary} />
          <rect x="48" y="46" width="5" height="15" rx="1" fill={c.accent} />
          <rect x="56" y="49" width="5" height="12" rx="1" fill={c.primary} opacity=".6" />
        </>
      )}
    </svg>
  );
}

/** Split light / dark swatch used in menus. */
export function DesignSwatch({ design, className }: { design: Design; className?: string }) {
  return (
    <span className={cn("relative inline-flex h-9 w-14 shrink-0 overflow-hidden rounded-md border", className)} aria-hidden>
      <DesignPreview design={design} mode="light" className="absolute inset-0 h-full w-full" />
      <span className="absolute inset-0 [clip-path:polygon(100%_0,100%_100%,0_100%)]">
        <DesignPreview design={design} mode="dark" className="h-full w-full" />
      </span>
    </span>
  );
}

/** Top-bar palette menu: design theme (with previews) + colour mode. */
export function ThemeMenu({ className }: { className?: string }) {
  const { design, setDesign } = useDesign();
  const { theme, setTheme } = useTheme();
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="ghost" size="icon" className={cn("h-[38px] w-[38px]", className)} aria-label={`Appearance: ${DESIGN_META[design].label} theme`}>
          <Palette />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-72">
        <DropdownMenuLabel className="section-label">Design theme</DropdownMenuLabel>
        <DropdownMenuRadioGroup value={design} onValueChange={(v) => setDesign(v as Design)}>
          {DESIGNS.map((d) => (
            <DropdownMenuRadioItem key={d} value={d} className="gap-3 py-2 pl-2 pr-2 [&>span:first-child]:hidden" onSelect={(e) => e.preventDefault()}>
              <DesignSwatch design={d} />
              <span className="flex min-w-0 flex-1 flex-col">
                <span className="font-semibold">{DESIGN_META[d].label}</span>
                <span className="text-xs font-normal leading-snug text-muted-foreground">{DESIGN_META[d].tagline}</span>
              </span>
              <Check className={cn("h-4 w-4 shrink-0", design === d ? "opacity-100" : "opacity-0")} aria-hidden />
            </DropdownMenuRadioItem>
          ))}
        </DropdownMenuRadioGroup>
        <DropdownMenuSeparator />
        <DropdownMenuLabel className="section-label">Colour mode</DropdownMenuLabel>
        <DropdownMenuRadioGroup value={theme ?? "light"} onValueChange={setTheme}>
          {COLOR_MODES.map((m) => (
            <DropdownMenuRadioItem key={m.value} value={m.value} className="gap-2">
              <m.icon className="h-4 w-4 text-muted-foreground" aria-hidden />
              {m.label}
            </DropdownMenuRadioItem>
          ))}
        </DropdownMenuRadioGroup>
        <DropdownMenuSeparator />
        <p className="px-2.5 py-1.5 text-[11.5px] text-muted-foreground">
          Press <kbd className="rounded-[5px] border bg-secondary px-1 font-mono text-[10.5px]">t</kbd>{" "}
          <kbd className="rounded-[5px] border bg-secondary px-1 font-mono text-[10.5px]">t</kbd> to switch design.
        </p>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
