export const DEVICE_STATUSES = ["active", "planned", "offline", "decommissioning"] as const;
export const BACKUP_STATUSES = ["success", "unchanged", "failed"] as const;
export const DEVICE_ROLES = ["core", "edge", "peering", "route-server", "access", "firewall", "management", "switch"] as const;
export const SEVERITIES = ["low", "medium", "high", "critical"] as const;
export const CHANGE_STATES = [
  "draft",
  "pending_approval",
  "approved",
  "rejected",
  "implemented",
  "closed",
  "cancelled",
] as const;
export const CHANGE_RISKS = ["low", "medium", "high", "critical"] as const;

export const PAGE_SIZE = 50;
