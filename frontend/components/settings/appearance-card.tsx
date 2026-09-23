"use client";

import { Check } from "lucide-react";
import { useTheme } from "next-themes";

import { COLOR_MODES, DesignPreview } from "@/components/layout/theme-menu";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Segmented } from "@/components/ui/tabs";
import { useColorMode, useDesign } from "@/hooks/use-design";
import { DESIGN_META, DESIGNS } from "@/lib/theme";
import { cn } from "@/lib/utils";

/** Settings → Appearance: pick the design theme from live previews, and the colour mode. */
export function AppearanceCard() {
  const { design, setDesign } = useDesign();
  const { theme, setTheme } = useTheme();
  const mode = useColorMode();
  return (
    <Card>
      <CardHeader className="flex-row flex-wrap items-start justify-between gap-3">
        <div className="flex flex-col gap-1">
          <CardTitle>Appearance</CardTitle>
          <CardDescription>Design theme and colour mode are stored in this browser. Press t t anywhere to switch design.</CardDescription>
        </div>
        <Segmented
          aria-label="Colour mode"
          value={(theme ?? "light") as "light" | "dark" | "system"}
          onChange={setTheme}
          options={COLOR_MODES.map((m) => ({
            value: m.value,
            label: (
              <>
                <m.icon aria-hidden /> {m.label}
              </>
            ),
          }))}
        />
      </CardHeader>
      <CardContent>
        <div role="radiogroup" aria-label="Design theme" className="grid gap-4 sm:grid-cols-2">
          {DESIGNS.map((d) => {
            const selected = design === d;
            return (
              <button
                key={d}
                type="button"
                role="radio"
                aria-checked={selected}
                onClick={() => setDesign(d)}
                className={cn(
                  "group flex flex-col gap-3 rounded-xl border-2 bg-card p-3 text-left transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2",
                  selected ? "border-primary" : "border-border hover:border-primary/40",
                )}
              >
                <span className="grid grid-cols-2 gap-2">
                  {(["light", "dark"] as const).map((m) => (
                    <span key={m} className={cn("overflow-hidden rounded-lg border", m === mode && "ring-1 ring-primary/40")}>
                      <DesignPreview design={d} mode={m} className="block h-auto w-full" />
                    </span>
                  ))}
                </span>
                <span className="flex items-start gap-2">
                  <span className="flex min-w-0 flex-1 flex-col gap-0.5">
                    <span className="font-display text-base font-semibold">{DESIGN_META[d].label}</span>
                    <span className="text-[12.5px] leading-snug text-muted-foreground">{DESIGN_META[d].tagline}</span>
                  </span>
                  <span
                    className={cn(
                      "mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full border-2",
                      selected ? "border-primary bg-primary text-primary-foreground" : "border-input",
                    )}
                    aria-hidden
                  >
                    {selected ? <Check className="h-3 w-3" strokeWidth={3} /> : null}
                  </span>
                </span>
              </button>
            );
          })}
        </div>
      </CardContent>
    </Card>
  );
}
