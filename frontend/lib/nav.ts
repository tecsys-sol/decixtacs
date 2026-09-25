import {
  Activity,
  ArchiveRestore,
  Binary,
  Bell,
  Building2,
  KeyRound,
  ClipboardCheck,
  FileBarChart,
  FileClock,
  GitCompare,
  History,
  LayoutDashboard,
  Network,
  PlugZap,
  ScrollText,
  Server,
  Settings,
  ShieldCheck,
  SquareTerminal,
  Users,
  Waypoints,
  Workflow,
  type LucideIcon,
} from "lucide-react";

export type NavBadge = "devices" | "backups" | "changes" | "alerts";

export interface NavItem {
  title: string;
  href: string;
  icon: LucideIcon;
  /** permission required to see the item */
  permission?: string;
  /** keyboard shortcut (shown in the palette / help) */
  shortcut?: string;
  keywords?: string[];
  /** live counter shown next to the item (from the dashboard summary) */
  badge?: NavBadge;
}

export interface NavGroup {
  title: string;
  items: NavItem[];
}

export const NAV: NavGroup[] = [
  {
    title: "Overview",
    items: [
      {
        title: "Dashboard",
        href: "/dashboard",
        icon: LayoutDashboard,
        permission: "devices:read",
        shortcut: "g d",
      },
      {
        title: "Devices",
        href: "/devices",
        icon: Server,
        permission: "devices:read",
        shortcut: "g v",
        keywords: ["inventory"],
        badge: "devices",
      },
      {
        title: "Sites & racks",
        href: "/sites",
        icon: Building2,
        permission: "devices:read",
        keywords: ["pop", "datacenter", "rack", "netbox"],
      },
      {
        title: "IPAM",
        href: "/ipam",
        icon: Binary,
        permission: "devices:read",
        keywords: ["prefix", "vlan", "ip address", "vrf", "netbox"],
      },
      {
        title: "Network map",
        href: "/map",
        icon: Waypoints,
        permission: "devices:read",
        keywords: ["topology"],
      },
      {
        title: "Alerts",
        href: "/alerts",
        icon: Bell,
        permission: "devices:read",
        badge: "alerts",
      },
    ],
  },
  {
    title: "Configuration",
    items: [
      {
        title: "Backups",
        href: "/backups",
        icon: GitCompare,
        permission: "configs:read",
        shortcut: "g b",
        keywords: ["git", "diff"],
        badge: "backups",
      },
      {
        title: "Credentials",
        href: "/credentials",
        icon: KeyRound,
        permission: "devices:read",
        keywords: ["ssh", "password", "rancid", "backup login"],
      },
      {
        title: "RANCID migration",
        href: "/rancid",
        icon: ArchiveRestore,
        permission: "configs:read",
        keywords: ["rancid", "cloginrc", "router.db", "compare", "migrate"],
      },
      {
        title: "Compliance",
        href: "/compliance",
        icon: ClipboardCheck,
        permission: "compliance:read",
        keywords: ["rules"],
      },
      {
        title: "Changes",
        href: "/changes",
        icon: Workflow,
        permission: "changes:read",
        shortcut: "g c",
        keywords: ["change request", "CHG"],
        badge: "changes",
      },
      {
        title: "Reports",
        href: "/reports",
        icon: FileBarChart,
        permission: "reports:read",
      },
    ],
  },
  {
    title: "Access",
    items: [
      {
        title: "TACACS+",
        href: "/tacacs",
        icon: ShieldCheck,
        permission: "tacacs:read",
        keywords: ["aaa", "policies", "nas"],
      },
      {
        title: "Accounting",
        href: "/accounting",
        icon: ScrollText,
        permission: "accounting:read",
        keywords: ["commands"],
      },
      {
        title: "Sessions",
        href: "/sessions",
        icon: SquareTerminal,
        permission: "sessions:read",
        keywords: ["replay", "recording"],
      },
      {
        title: "Audit log",
        href: "/audit",
        icon: History,
        permission: "audit:read",
        shortcut: "g a",
      },
    ],
  },
  {
    title: "Integrations",
    items: [
      {
        title: "IXP",
        href: "/ixp",
        icon: Network,
        permission: "devices:read",
        keywords: ["members", "route server", "rpki"],
      },
      {
        title: "Integrations",
        href: "/integrations",
        icon: PlugZap,
        permission: "devices:read",
        keywords: ["netbox", "ixp manager", "birdseye"],
      },
    ],
  },
  {
    title: "Admin",
    items: [
      {
        title: "Users & roles",
        href: "/users",
        icon: Users,
        permission: "users:read",
        keywords: ["groups", "rbac"],
      },
      {
        title: "Login history",
        href: "/users?tab=logins",
        icon: FileClock,
        permission: "users:read",
      },
      {
        title: "Settings",
        href: "/settings",
        icon: Settings,
        keywords: ["mfa", "password", "api tokens"],
      },
    ],
  },
];

export const ACTIVITY_ICON = Activity;

/** "g <key>" navigation shortcuts */
export const GOTO_SHORTCUTS: Record<string, string> = {
  d: "/dashboard",
  v: "/devices",
  b: "/backups",
  c: "/changes",
  a: "/audit",
};

export const SHORTCUT_HELP: { keys: string[]; description: string }[] = [
  { keys: ["⌘/Ctrl", "K"], description: "Open search / command palette" },
  { keys: ["g", "d"], description: "Go to dashboard" },
  { keys: ["g", "v"], description: "Go to devices" },
  { keys: ["g", "b"], description: "Go to backups" },
  { keys: ["g", "c"], description: "Go to changes" },
  { keys: ["g", "a"], description: "Go to audit log" },
  { keys: ["t", "t"], description: "Toggle design theme (Aurora / Meridian)" },
  { keys: ["?"], description: "Show keyboard shortcuts" },
];
