"use client";

import Link from "next/link";
import { ChevronDown, Menu, Plus, Search } from "lucide-react";

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
import { useAuth } from "@/hooks/use-auth";
import { useTimeRange } from "@/hooks/use-time-range";
import { TIME_RANGES, type TimeRange } from "@/lib/aggregate";
import { cn } from "@/lib/utils";

import { TenantSwitcher } from "./tenant-switcher";
import { ThemeMenu } from "./theme-menu";
import { UserMenu } from "./user-menu";

export function TimeRangePill({ className }: { className?: string }) {
  const { range, setRange } = useTimeRange();
  const current = TIME_RANGES.find((r) => r.value === range) ?? TIME_RANGES[0];
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="outline" className={cn("hidden h-[38px] gap-2 px-3.5 font-semibold md:inline-flex", className)} aria-label={`Time range: ${current.long}`}>
          {current.long}
          <ChevronDown className="h-3.5 w-3.5" aria-hidden />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-48">
        <DropdownMenuLabel className="section-label">Activity window</DropdownMenuLabel>
        <DropdownMenuSeparator />
        <DropdownMenuRadioGroup value={range} onValueChange={(v) => setRange(v as TimeRange)}>
          {TIME_RANGES.map((r) => (
            <DropdownMenuRadioItem key={r.value} value={r.value}>
              {r.long}
            </DropdownMenuRadioItem>
          ))}
        </DropdownMenuRadioGroup>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

export function Topbar({
  onOpenSearch,
  onOpenNav,
  onShowShortcuts,
}: {
  onOpenSearch: () => void;
  onOpenNav: () => void;
  onShowShortcuts: () => void;
}) {
  const { can } = useAuth();
  return (
    <header className="sticky top-0 z-30 flex h-[68px] shrink-0 items-center gap-2 border-b bg-card/75 px-3 backdrop-blur-md sm:gap-3 sm:px-6 lg:px-8">
      <Button variant="ghost" size="icon" className="lg:hidden" onClick={onOpenNav} aria-label="Open navigation">
        <Menu />
      </Button>
      <button
        type="button"
        onClick={onOpenSearch}
        className="flex h-10 min-w-0 flex-1 items-center gap-2.5 rounded-[11px] border bg-secondary px-3.5 text-sm text-muted-foreground transition-colors hover:border-primary/30 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring sm:max-w-[420px]"
        aria-label="Search devices, ASNs, changes and users (Ctrl+K)"
      >
        <Search className="h-4 w-4 shrink-0" aria-hidden />
        <span className="truncate">Search devices, ASNs, changes, users…</span>
        <kbd className="ml-auto hidden rounded-[6px] border border-[hsl(var(--input))] bg-card px-1.5 py-0.5 font-mono text-[11px] sm:inline">⌘K</kbd>
      </button>
      <div className="ml-auto flex shrink-0 items-center gap-1.5 sm:gap-2.5">
        <TenantSwitcher />
        <TimeRangePill />
        <ThemeMenu />
        {can("changes:write") ? (
          <Button asChild className="h-[38px] px-3 sm:px-4">
            <Link href="/changes?new=1" aria-label="New change">
              <Plus className="!size-[15px]" strokeWidth={2.4} aria-hidden />
              <span className="hidden sm:inline">New change</span>
            </Link>
          </Button>
        ) : null}
        <UserMenu onShowShortcuts={onShowShortcuts} />
      </div>
    </header>
  );
}
