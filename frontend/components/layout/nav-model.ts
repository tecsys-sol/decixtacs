"use client";

import { usePathname, useSearchParams } from "next/navigation";

import { useAuth } from "@/hooks/use-auth";
import { useDashboard } from "@/hooks/use-dashboard";
import { NAV, type NavBadge, type NavItem } from "@/lib/nav";
import type { Dashboard } from "@/lib/types";
import { formatNumber } from "@/lib/utils";

/*
 * Navigation model shared by every shell variant (Aurora sidebar, Meridian top navigation, the
 * mobile drawer): permission filtering, active-route matching and live badges are computed once
 * from the single NAV definition in lib/nav.ts.
 */

export type BadgeTone = "plain" | "warning" | "danger" | "brand";

export interface NavBadgeValue {
  text: string;
  tone: BadgeTone;
  label: string;
}

export interface NavEntry {
  item: NavItem;
  active: boolean;
  badge: NavBadgeValue | null;
}

export interface NavGroupEntry {
  title: string;
  items: NavEntry[];
  active: boolean;
}

export function isActive(item: NavItem, pathname: string, tab: string | null): boolean {
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

export function badgeFor(kind: NavBadge | undefined, d: Dashboard | undefined): NavBadgeValue | null {
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

export const BADGE_CLS: Record<BadgeTone, string> = {
  plain: "text-muted-foreground font-semibold",
  warning: "rounded-full bg-warning-soft px-[7px] py-0.5 font-bold text-warning",
  danger: "rounded-full bg-danger-soft px-[7px] py-0.5 font-bold text-danger",
  brand: "rounded-full bg-accent px-[7px] py-0.5 font-bold text-accent-foreground",
};

/** Visible navigation groups for the signed-in user (empty groups dropped). */
export function useNavGroups(): NavGroupEntry[] {
  const pathname = usePathname();
  const params = useSearchParams();
  const tab = params.get("tab");
  const { can, me } = useAuth();
  const dashboard = useDashboard();
  if (!me) return [];
  return NAV.map((group) => {
    const items = group.items
      .filter((i) => !i.permission || can(i.permission))
      .map((item) => ({ item, active: isActive(item, pathname, tab), badge: badgeFor(item.badge, dashboard.data) }));
    return { title: group.title, items, active: items.some((i) => i.active) };
  }).filter((g) => g.items.length > 0);
}
