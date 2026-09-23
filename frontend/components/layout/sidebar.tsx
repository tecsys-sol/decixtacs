"use client";

import Link from "next/link";
import { usePathname, useSearchParams } from "next/navigation";
import { ChevronsLeft, ChevronsRight } from "lucide-react";

import { useAuth } from "@/hooks/use-auth";
import { NAV, type NavItem } from "@/lib/nav";
import { cn } from "@/lib/utils";

import { Logo } from "./logo";

function isActive(item: NavItem, pathname: string, tab: string | null): boolean {
  const [path, query] = item.href.split("?");
  if (query) {
    const want = new URLSearchParams(query);
    return pathname === path && [...want.entries()].every(([k, v]) => (k === "tab" ? tab === v : true));
  }
  if (pathname === path || pathname.startsWith(`${path}/`)) {
    // "/users" must not be highlighted when a "/users?tab=..." sibling is active
    return !(path === "/users" && tab === "logins");
  }
  return false;
}

export function SidebarNav({ collapsed, onNavigate }: { collapsed?: boolean; onNavigate?: () => void }) {
  const pathname = usePathname();
  const params = useSearchParams();
  const tab = params.get("tab");
  const { can, me } = useAuth();

  return (
    <nav className="flex-1 overflow-y-auto px-2 py-3 scrollbar-thin" aria-label="Main">
      {NAV.map((group) => {
        const items = group.items.filter((i) => !i.permission || can(i.permission));
        if (!items.length || !me) return null;
        return (
          <div key={group.title} className="mb-4">
            {collapsed ? (
              <div className="mx-2 mb-2 h-px bg-sidebar-border" />
            ) : (
              <p className="mb-1 px-2 text-[10px] font-semibold uppercase tracking-widest text-muted-foreground/80">
                {group.title}
              </p>
            )}
            <ul className="grid gap-0.5">
              {items.map((item) => {
                const active = isActive(item, pathname, tab);
                return (
                  <li key={item.href}>
                    <Link
                      href={item.href}
                      onClick={onNavigate}
                      title={collapsed ? item.title : undefined}
                      aria-current={active ? "page" : undefined}
                      className={cn(
                        "group flex h-8 items-center gap-2.5 rounded-md px-2 text-sm text-sidebar-foreground transition-colors hover:bg-accent hover:text-foreground",
                        active && "bg-primary/10 font-medium text-primary hover:bg-primary/15 hover:text-primary",
                        collapsed && "justify-center px-0",
                      )}
                    >
                      <item.icon className="h-4 w-4 shrink-0" aria-hidden />
                      {collapsed ? <span className="sr-only">{item.title}</span> : <span className="truncate">{item.title}</span>}
                    </Link>
                  </li>
                );
              })}
            </ul>
          </div>
        );
      })}
    </nav>
  );
}

export function Sidebar({ collapsed, onToggle }: { collapsed: boolean; onToggle: () => void }) {
  return (
    <aside
      className={cn(
        "sticky top-0 hidden h-screen shrink-0 flex-col border-r border-sidebar-border bg-sidebar transition-[width] duration-200 lg:flex",
        collapsed ? "w-[60px]" : "w-60",
      )}
    >
      <div className={cn("flex h-14 items-center border-b border-sidebar-border px-3", collapsed && "justify-center px-0")}>
        <Link href="/dashboard" aria-label="NetworkOps Manager home">
          <Logo collapsed={collapsed} />
        </Link>
      </div>
      <SidebarNav collapsed={collapsed} />
      <div className="border-t border-sidebar-border p-2">
        <button
          type="button"
          onClick={onToggle}
          className={cn(
            "flex h-8 w-full items-center gap-2 rounded-md px-2 text-xs text-muted-foreground hover:bg-accent hover:text-foreground",
            collapsed && "justify-center px-0",
          )}
          aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
        >
          {collapsed ? <ChevronsRight className="h-4 w-4" /> : <ChevronsLeft className="h-4 w-4" />}
          {collapsed ? null : "Collapse"}
        </button>
      </div>
    </aside>
  );
}
