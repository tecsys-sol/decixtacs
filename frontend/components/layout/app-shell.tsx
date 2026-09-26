"use client";

import { usePathname } from "next/navigation";
import * as React from "react";

import { Dialog, DialogDescription, DialogTitle, SheetContent } from "@/components/ui/dialog";
import { useDesign } from "@/hooks/use-design";
import { useOnChange } from "@/hooks/use-reset";
import { useGlobalShortcuts } from "@/hooks/use-shortcuts";
import { TimeRangeProvider } from "@/hooks/use-time-range";

import { AppFooter } from "./app-footer";
import { CommandPalette } from "./command-palette";
import { Logo } from "./logo";
import { MeridianHeader } from "./meridian-header";
import { ShortcutsDialog } from "./shortcuts-dialog";
import { Sidebar, SidebarNav, TacacsHealthCard } from "./sidebar";
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

  const { design, toggleDesign } = useDesign();
  const openSearch = React.useCallback(() => setSearchOpen(true), []);
  const openHelp = React.useCallback(() => setHelpOpen(true), []);
  useGlobalShortcuts({ onSearch: openSearch, onHelp: openHelp, onToggleDesign: toggleDesign });

  // Shell variant follows the design theme; both share nav data (lib/nav.ts + nav-model.ts), the
  // drawer, the command palette and the shortcuts.
  const meridian = design === "meridian";
  const drawer = (
        <Dialog open={mobileOpen} onOpenChange={setMobileOpen}>
          <SheetContent className="gap-5 px-4 py-5">
            <DialogTitle className="sr-only">Navigation</DialogTitle>
            <DialogDescription className="sr-only">Main navigation</DialogDescription>
            <div className="px-2">
              <Logo />
            </div>
            <div className="-mx-1 flex-1 overflow-y-auto px-1 scrollbar-thin">
              <SidebarNav onNavigate={() => setMobileOpen(false)} />
            </div>
            <TacacsHealthCard />
          </SheetContent>
        </Dialog>
  );
  const overlays = (
    <>
      <CommandPalette open={searchOpen} onOpenChange={setSearchOpen} />
      <ShortcutsDialog open={helpOpen} onOpenChange={setHelpOpen} />
    </>
  );

  if (meridian) {
    return (
      <TimeRangeProvider>
        <div className="flex min-h-screen flex-col bg-background">
          <MeridianHeader onOpenSearch={openSearch} onOpenNav={() => setMobileOpen(true)} onShowShortcuts={openHelp} />
          {drawer}
          <main className="mx-auto w-full max-w-[1600px] flex-1 px-4 pb-10 pt-6 sm:px-8 sm:pt-[30px] xl:px-11">{children}</main>
          <AppFooter className="xl:px-11" />
          {overlays}
        </div>
      </TimeRangeProvider>
    );
  }

  return (
    <TimeRangeProvider>
      <div className="flex min-h-screen bg-background">
        <Sidebar collapsed={collapsed} onToggle={toggle} />
        {drawer}
        <div className="flex min-w-0 flex-1 flex-col">
          <Topbar onOpenSearch={openSearch} onOpenNav={() => setMobileOpen(true)} onShowShortcuts={openHelp} />
          <main className="mx-auto w-full max-w-[1600px] flex-1 px-4 pb-8 pt-6 sm:px-8 sm:pt-[26px]">{children}</main>
          <AppFooter />
        </div>
        {overlays}
      </div>
    </TimeRangeProvider>
  );
}
