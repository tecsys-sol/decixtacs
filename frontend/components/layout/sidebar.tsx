"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { usePathname, useSearchParams } from "next/navigation";
import { ChevronsLeft, ChevronsRight } from "lucide-react";

import { RelativeTime } from "@/components/common/relative-time";
import { MiniNetwork } from "@/components/illustrations";
import { useAuth } from "@/hooks/use-auth";
import { useDashboard } from "@/hooks/use-dashboard";
import { useNow } from "@/hooks/use-now";
import { api } from "@/lib/api";
import { NAV, type NavBadge, type NavItem } from "@/lib/nav";
import type { Dashboard, TacacsServer } from "@/lib/types";
import { cn, formatNumber, parseDate } from "@/lib/utils";

import { Logo } from "./logo";

/** a TACACS+ agent that has not checked in for this long counts as unhealthy */
export const HEARTBEAT_STALE_MS = 5 * 60_000;

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

function badgeFor(kind: NavBadge | undefined, d: Dashboard | undefined): { text: string; tone: "plain" | "warning" | "danger" | "brand"; label: string } | null {
  if (!kind || !d) return null;
  switch (kind) {
    case "devices":
      return { text: formatNumber(d.devices.total), tone: "plain", label: `${d.devices.total} devices` };
    case "backups":
      return d.backups.devices_failing ? { text: String(d.backups.devices_failing), tone: "danger", label: `${d.backups.devices_failing} devices failing backup` } : null;
    case "changes":
      return d.open_changes ? { text: String(d.open_changes), tone: "brand", label: `${d.open_changes} open changes` } : null;
    case "alerts":
      return d.open_alerts ? { text: String(d.open_alerts), tone: "warning", label: `${d.open_alerts} open alerts` } : null;
  }
}

const BADGE_CLS = {
  plain: "text-muted-foreground font-semibold",
  warning: "rounded-full bg-warning-soft px-[7px] py-0.5 font-bold text-warning",
  danger: "rounded-full bg-danger-soft px-[7px] py-0.5 font-bold text-danger",
  brand: "rounded-full bg-accent px-[7px] py-0.5 font-bold text-accent-foreground",
} as const;

export function SidebarNav({ collapsed, onNavigate }: { collapsed?: boolean; onNavigate?: () => void }) {
  const pathname = usePathname();
  const params = useSearchParams();
  const tab = params.get("tab");
  const { can, me } = useAuth();
  const dashboard = useDashboard();

  return (
    <nav className="flex flex-col gap-0.5" aria-label="Main">
      {NAV.map((group, gi) => {
        const items = group.items.filter((i) => !i.permission || can(i.permission));
        if (!items.length || !me) return null;
        return (
          <div key={group.title} className="flex flex-col gap-0.5">
            {collapsed ? (
              <div className={cn("mx-2 h-px bg-sidebar-border", gi === 0 ? "mb-2" : "my-2")} />
            ) : (
              <span className={cn("section-label px-2.5 pb-1.5", gi === 0 ? "pt-1.5" : "pt-3.5")}>{group.title}</span>
            )}
            <ul className="flex flex-col gap-0.5">
              {items.map((item) => {
                const active = isActive(item, pathname, tab);
                const badge = badgeFor(item.badge, dashboard.data);
                return (
                  <li key={item.href}>
                    <Link
                      href={item.href}
                      onClick={onNavigate}
                      title={collapsed ? item.title : undefined}
                      aria-current={active ? "page" : undefined}
                      className={cn(
                        "group flex items-center gap-2.5 rounded-[9px] px-2.5 py-[9px] text-sm font-semibold text-sidebar-foreground transition-colors hover:bg-nav-hover hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                        active && "bg-accent font-bold text-accent-foreground hover:bg-accent hover:text-accent-foreground",
                        collapsed && "justify-center px-0",
                      )}
                    >
                      <item.icon className="h-[17px] w-[17px] shrink-0" strokeWidth={2} aria-hidden />
                      {collapsed ? (
                        <span className="sr-only">{item.title}</span>
                      ) : (
                        <>
                          <span className="truncate">{item.title}</span>
                          {badge ? (
                            <span className={cn("ml-auto text-[11px] tabular", BADGE_CLS[badge.tone])} aria-label={badge.label}>
                              {badge.text}
                            </span>
                          ) : null}
                        </>
                      )}
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

/** Bottom card: TACACS+ agent health from the servers' heartbeats. */
export function TacacsHealthCard() {
  const { can } = useAuth();
  const now = useNow();
  const servers = useQuery({
    queryKey: ["tacacs", "servers"],
    queryFn: () => api.get<TacacsServer[]>("/tacacs/servers"),
    enabled: can("tacacs:read"),
    refetchInterval: 60_000,
  });
  if (!can("tacacs:read") || !servers.data) return null;
  const list = servers.data.filter((s) => s.enabled);
  const healthy = list.filter((s) => {
    const d = parseDate(s.last_heartbeat_at);
    return d && now - d.getTime() <= HEARTBEAT_STALE_MS;
  }).length;
  const latest = [...list].sort((a, b) => (parseDate(b.last_deployed_at)?.getTime() ?? 0) - (parseDate(a.last_deployed_at)?.getTime() ?? 0))[0];
  const degraded = list.length > 0 && healthy < list.length;
  const title = !list.length
    ? "No TACACS+ servers yet"
    : healthy === list.length
      ? `All ${list.length} TACACS+ server${list.length === 1 ? "" : "s"} healthy`
      : `${healthy} of ${list.length} TACACS+ servers healthy`;

  return (
    <Link
      href="/tacacs?tab=servers"
      className="flex flex-col gap-2.5 rounded-[14px] bg-[var(--ill-softer)] p-4 transition-colors hover:bg-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
    >
      <MiniNetwork className="h-[70px] w-full" degraded={degraded} />
      <span className="flex items-center gap-2 text-[13px] font-bold text-foreground">
        <span
          className={cn("h-2 w-2 shrink-0 rounded-full", degraded ? "bg-[var(--ill-orange)]" : list.length ? "live bg-[var(--ill-green)]" : "bg-[var(--ill-lilac)]")}
          aria-hidden
        />
        {title}
      </span>
      <span className="text-xs leading-relaxed text-ink-3">
        {latest?.last_deployed_at ? (
          <>
            Config v{latest.config_version} deployed <RelativeTime value={latest.last_deployed_at} />.
          </>
        ) : list.length ? (
          "No configuration deployed yet."
        ) : (
          "Add a server to centralise device AAA."
        )}
      </span>
    </Link>
  );
}

export function Sidebar({ collapsed, onToggle }: { collapsed: boolean; onToggle: () => void }) {
  return (
    <aside
      className={cn(
        "hidden shrink-0 border-r border-sidebar-border bg-sidebar transition-[width] duration-200 lg:block",
        collapsed ? "w-[68px]" : "w-[244px]",
      )}
    >
      <div className={cn("sticky top-0 flex h-screen flex-col gap-5 py-[22px]", collapsed ? "px-2" : "px-4")}>
      <Link href="/dashboard" aria-label="NetworkOps Manager home" className={cn("rounded-lg focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring", collapsed ? "mx-auto" : "px-2")}>
        <Logo collapsed={collapsed} />
      </Link>
      <div className="-mx-1 flex-1 overflow-y-auto px-1 scrollbar-thin">
        <SidebarNav collapsed={collapsed} />
      </div>
      {collapsed ? null : <TacacsHealthCard />}
      <button
        type="button"
        onClick={onToggle}
        className={cn(
          "flex h-8 items-center gap-2 rounded-md px-2.5 text-xs font-semibold text-muted-foreground hover:bg-nav-hover hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
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
