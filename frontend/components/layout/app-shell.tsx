"use client";

import { usePathname } from "next/navigation";
import * as React from "react";

import { Dialog, DialogDescription, DialogTitle, SheetContent } from "@/components/ui/dialog";
import { useOnChange } from "@/hooks/use-reset";
import { useGlobalShortcuts } from "@/hooks/use-shortcuts";

import { CommandPalette } from "./command-palette";
import { Logo } from "./logo";
import { ShortcutsDialog } from "./shortcuts-dialog";
import { Sidebar, SidebarNav } from "./sidebar";
import { Topbar } from "./topbar";

const COLLAPSE_KEY = "nom.sidebar.collapsed";

export function AppShell({ children }: { children: React.ReactNode }) {
  const [collapsed, setCollapsed] = React.useState(() => {
    try {
      return window.localStorage.getItem(COLLAPSE_KEY) === "1";
    } catch {
      return false;
    }
  });
  const [mobileOpen, setMobileOpen] = React.useState(false);
  const [searchOpen, setSearchOpen] = React.useState(false);
  const [helpOpen, setHelpOpen] = React.useState(false);
  const pathname = usePathname();
  useOnChange(pathname, () => setMobileOpen(false));

  const toggle = () =>
    setCollapsed((c) => {
      try {
        window.localStorage.setItem(COLLAPSE_KEY, c ? "0" : "1");
      } catch {
        /* storage unavailable */
      }
      return !c;
    });

  const openSearch = React.useCallback(() => setSearchOpen(true), []);
  const openHelp = React.useCallback(() => setHelpOpen(true), []);
  useGlobalShortcuts({ onSearch: openSearch, onHelp: openHelp });

  return (
    <div className="flex min-h-screen">
      <Sidebar collapsed={collapsed} onToggle={toggle} />
      <Dialog open={mobileOpen} onOpenChange={setMobileOpen}>
        <SheetContent>
          <DialogTitle className="sr-only">Navigation</DialogTitle>
          <DialogDescription className="sr-only">Main navigation</DialogDescription>
          <div className="flex h-14 items-center border-b border-sidebar-border px-3">
            <Logo />
          </div>
          <SidebarNav onNavigate={() => setMobileOpen(false)} />
        </SheetContent>
      </Dialog>
      <div className="flex min-w-0 flex-1 flex-col">
        <Topbar onOpenSearch={openSearch} onOpenNav={() => setMobileOpen(true)} onShowShortcuts={openHelp} />
        <main className="mx-auto w-full max-w-[1600px] flex-1 px-3 py-5 sm:px-6">{children}</main>
      </div>
      <CommandPalette open={searchOpen} onOpenChange={setSearchOpen} />
      <ShortcutsDialog open={helpOpen} onOpenChange={setHelpOpen} />
    </div>
  );
}
