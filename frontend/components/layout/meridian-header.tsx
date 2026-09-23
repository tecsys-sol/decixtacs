"use client";

import Link from "next/link";
import { ChevronDown, Menu, Plus, Search } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { useAuth } from "@/hooks/use-auth";
import { cn } from "@/lib/utils";

import { Logo } from "./logo";
import { BADGE_CLS, useNavGroups, type NavGroupEntry } from "./nav-model";
import { TenantSwitcher } from "./tenant-switcher";
import { ThemeMenu } from "./theme-menu";
import { TimeRangePill } from "./topbar";
import { UserMenu } from "./user-menu";

const PILL =
  "inline-flex h-9 items-center gap-1.5 whitespace-nowrap rounded-full px-3.5 text-sm font-semibold text-ink-2 transition-colors hover:bg-nav-hover hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring data-[state=open]:bg-nav-hover";
const PILL_ACTIVE = "bg-pill-active text-pill-active-foreground hover:bg-pill-active hover:text-pill-active-foreground data-[state=open]:bg-pill-active";

/** One nav group as a pill: a plain link when it holds a single page, otherwise a dropdown. */
function GroupPill({ group }: { group: NavGroupEntry }) {
  if (group.items.length === 1) {
    const { item, active } = group.items[0];
    return (
      <Link href={item.href} aria-current={active ? "page" : undefined} className={cn(PILL, active && PILL_ACTIVE)}>
        {item.title}
      </Link>
    );
  }
  const current = group.items.find((i) => i.active);
  const alerting = group.items.some((i) => i.badge && i.badge.tone !== "plain" && i.badge.tone !== "brand");
  return (
    <DropdownMenu>
      <DropdownMenuTrigger className={cn(PILL, group.active && PILL_ACTIVE)} aria-label={`${group.title} menu${current ? `, current page ${current.item.title}` : ""}`}>
        {group.title}
        {alerting && !group.active ? <span className="h-1.5 w-1.5 rounded-full bg-[var(--ill-orange)]" aria-hidden /> : null}
        <ChevronDown className="h-3.5 w-3.5 opacity-70" aria-hidden />
      </DropdownMenuTrigger>
      <DropdownMenuContent align="start" className="w-64 rounded-xl p-2">
        <DropdownMenuLabel className="section-label">{group.title}</DropdownMenuLabel>
        <DropdownMenuSeparator />
        {group.items.map(({ item, active, badge }) => (
          <DropdownMenuItem key={item.href} asChild className={cn("rounded-full px-3", active && "bg-accent font-bold text-accent-foreground")}>
            <Link href={item.href} aria-current={active ? "page" : undefined}>
              <item.icon className="text-muted-foreground" aria-hidden />
              <span className="truncate">{item.title}</span>
              {badge ? (
                <span className={cn("ml-auto text-[11px] tabular", BADGE_CLS[badge.tone])} aria-label={badge.label}>
                  {badge.text}
                </span>
              ) : null}
            </Link>
          </DropdownMenuItem>
        ))}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

/**
 * Meridian shell header: logo, horizontal pill navigation (one pill per nav group, ≥1280px) and
 * round utility buttons. Below 1280px the pills collapse into the shared mobile drawer.
 */
export function MeridianHeader({
  onOpenSearch,
  onOpenNav,
  onShowShortcuts,
}: {
  onOpenSearch: () => void;
  onOpenNav: () => void;
  onShowShortcuts: () => void;
}) {
  const { can } = useAuth();
  const groups = useNavGroups();
  return (
    <header className="sticky top-0 z-30 border-b bg-background/85 backdrop-blur-md">
      <div className="mx-auto flex h-[72px] w-full max-w-[1600px] items-center gap-2 px-3 sm:gap-3 sm:px-6 xl:gap-5 xl:px-11">
        <Button variant="ghost" size="icon" className="xl:hidden" onClick={onOpenNav} aria-label="Open navigation">
          <Menu />
        </Button>
        <Link href="/dashboard" aria-label="NetworkOps Manager home" className="shrink-0 rounded-full focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
          <Logo subtitle="Manager" className="[&_.truncate]:hidden sm:[&_.truncate]:block xl:[&_.truncate]:hidden 2xl:[&_.truncate]:block" />
        </Link>
        <nav aria-label="Main" className="hidden min-w-0 items-center gap-1 xl:flex">
          {groups.map((g) => (
            <GroupPill key={g.title} group={g} />
          ))}
        </nav>
        <div className="ml-auto flex shrink-0 items-center gap-1.5 sm:gap-2.5">
          <button
            type="button"
            onClick={onOpenSearch}
            className="flex h-10 w-10 items-center justify-center rounded-full border border-input bg-card text-foreground transition-colors hover:border-primary/40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            aria-label="Search devices, ASNs, changes and users (Ctrl+K)"
            title="Search (⌘K)"
          >
            <Search className="h-[17px] w-[17px]" aria-hidden />
          </button>
          <TenantSwitcher labelClassName="hidden 2xl:inline" />
          <TimeRangePill className="md:hidden 2xl:inline-flex" />
          <ThemeMenu className="rounded-full border border-input bg-card" />
          {can("changes:write") ? (
            <Button asChild className="h-10 px-3 2xl:px-4">
              <Link href="/changes?new=1" aria-label="New change">
                <Plus className="!size-[15px]" strokeWidth={2.4} aria-hidden />
                <span className="hidden 2xl:inline">New change</span>
              </Link>
            </Button>
          ) : null}
          <UserMenu onShowShortcuts={onShowShortcuts} />
        </div>
      </div>
    </header>
  );
}
