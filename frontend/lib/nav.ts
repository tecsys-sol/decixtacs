import {
  Activity,
  Bell,
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

export interface NavItem {
  title: string;
  href: string;
  icon: LucideIcon;
  /** permission required to see the item */
  permission?: string;
  /** keyboard shortcut (shown in the palette / help) */
  shortcut?: string;
  keywords?: string[];
}

export interface NavGroup {
  title: string;
  items: NavItem[];
}

export const NAV: NavGroup[] = [
  {
    title: "Overview",
    items: [
      { title: "Dashboard", href: "/dashboard", icon: LayoutDashboard, permission: "devices:read", shortcut: "g d" },
      { title: "Network map", href: "/map", icon: Waypoints, permission: "devices:read", keywords: ["topology"] },
    ],
  },
  {
    title: "Configuration",
    items: [
      { title: "Devices", href: "/devices", icon: Server, permission: "devices:read", shortcut: "g v", keywords: ["inventory"] },
      { title: "Backups", href: "/backups", icon: GitCompare, permission: "configs:read", shortcut: "g b", keywords: ["git", "diff"] },
      { title: "Compliance", href: "/compliance", icon: ClipboardCheck, permission: "compliance:read", keywords: ["rules"] },
      { title: "Changes", href: "/changes", icon: Workflow, permission: "changes:read", shortcut: "g c", keywords: ["change request", "CHG"] },
    ],
  },
  {
    title: "Access",
    items: [
      { title: "TACACS+", href: "/tacacs", icon: ShieldCheck, permission: "tacacs:read", keywords: ["aaa", "policies", "nas"] },
      { title: "Accounting", href: "/accounting", icon: ScrollText, permission: "accounting:read", keywords: ["commands"] },
      { title: "Sessions", href: "/sessions", icon: SquareTerminal, permission: "sessions:read", keywords: ["replay", "recording"] },
      { title: "Audit log", href: "/audit", icon: History, permission: "audit:read", shortcut: "g a" },
    ],
  },
  {
    title: "Peering",
    items: [{ title: "IXP", href: "/ixp", icon: Network, permission: "devices:read", keywords: ["members", "route server", "rpki"] }],
  },
  {
    title: "Operations",
    items: [
      { title: "Alerts", href: "/alerts", icon: Bell, permission: "devices:read" },
      { title: "Reports", href: "/reports", icon: FileBarChart, permission: "reports:read" },
      { title: "Integrations", href: "/integrations", icon: PlugZap, permission: "devices:read", keywords: ["netbox", "ixp manager", "birdseye"] },
    ],
  },
  {
    title: "Administration",
    items: [
      { title: "Users & roles", href: "/users", icon: Users, permission: "users:read", keywords: ["groups", "rbac"] },
      { title: "Login history", href: "/users?tab=logins", icon: FileClock, permission: "users:read" },
      { title: "Settings", href: "/settings", icon: Settings, keywords: ["mfa", "password", "api tokens"] },
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
  { keys: ["?"], description: "Show keyboard shortcuts" },
];
