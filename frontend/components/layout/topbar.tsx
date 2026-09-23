"use client";

import { Menu, Search } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Kbd } from "@/components/ui/command";

import { TenantSwitcher } from "./tenant-switcher";
import { ThemeToggle } from "./theme-toggle";
import { UserMenu } from "./user-menu";

export function Topbar({
  onOpenSearch,
  onOpenNav,
  onShowShortcuts,
}: {
  onOpenSearch: () => void;
  onOpenNav: () => void;
  onShowShortcuts: () => void;
}) {
  return (
    <header className="sticky top-0 z-30 flex h-14 items-center gap-2 border-b bg-background/85 px-3 backdrop-blur supports-[backdrop-filter]:bg-background/70 sm:px-4">
      <Button variant="ghost" size="icon" className="lg:hidden" onClick={onOpenNav} aria-label="Open navigation">
        <Menu />
      </Button>
      <button
        type="button"
        onClick={onOpenSearch}
        className="flex h-9 min-w-0 flex-1 items-center gap-2 sm:max-w-md rounded-md border bg-muted/40 px-3 text-sm text-muted-foreground transition-colors hover:bg-muted"
        aria-label="Search"
      >
        <Search className="h-4 w-4" />
        <span className="truncate">Search devices, users, changes…</span>
        <span className="ml-auto hidden items-center gap-0.5 sm:flex">
          <Kbd>⌘</Kbd>
          <Kbd>K</Kbd>
        </span>
      </button>
      <div className="ml-auto flex shrink-0 items-center gap-1">
        <TenantSwitcher />
        <ThemeToggle />
        <UserMenu onShowShortcuts={onShowShortcuts} />
      </div>
    </header>
  );
}
