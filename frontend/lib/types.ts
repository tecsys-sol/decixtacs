/**
 * Types mirroring the NetworkOps Manager API (docs/api/openapi.json).
 * Timestamps are ISO-8601 strings; ids are UUID strings.
 */

export interface Page<T> {
  items: T[];
  total: number;
  limit: number;
  offset: number;
}

// --- auth --------------------------------------------------------------------------------

export interface LoginIn {
  username: string;
  password: string;
  tenant?: string | null;
  otp?: string | null;
}

export interface TokenOut {
  access_token: string;
  refresh_token: string;
  token_type?: string;
  expires_in: number;
}

export interface Me {
  id: string;
  tenant_id: string;
  username: string;
  email: string | null;
  full_name: string | null;
  is_superuser: boolean;
  mfa_enabled: boolean;
  auth_source: string;
  permissions: string[];
  groups: string[];
}

export interface MfaSetupOut {
  secret: string;
  otpauth_uri: string;
}

export interface ApiToken {
  id: string;
  name: string;
  token_prefix: string;
  scopes: string[];
  expires_at: string | null;
  last_used_at: string | null;
  revoked: boolean;
  created_at: string;
}

export interface ApiTokenCreated extends ApiToken {
  token: string;
}

export interface Tenant {
  id: string;
  name: string;
  slug: string;
  is_active: boolean;
  created_at: string;
}

// --- users & RBAC ------------------------------------------------------------------------

export interface Ref {
  id: string;
  name: string;
}

export interface User {
  id: string;
  username: string;
  email: string | null;
  full_name: string | null;
  auth_source: string;
  is_active: boolean;
  is_superuser: boolean;
  mfa_enabled: boolean;
  last_login_at: string | null;
  locked_until: string | null;
  created_at: string;
  groups: Ref[];
}

export interface UserIn {
  username: string;
  email?: string | null;
  full_name?: string | null;
  password?: string | null;
  auth_source?: string;
  is_active?: boolean;
  group_ids?: string[];
}

export interface UserPatch {
  email?: string | null;
  full_name?: string | null;
  password?: string | null;
  is_active?: boolean | null;
  group_ids?: string[] | null;
  reset_mfa?: boolean;
  unlock?: boolean;
}

export interface Group {
  id: string;
  name: string;
  description: string | null;
  source: string;
  external_dn: string | null;
  created_at: string;
}

export interface Permission {
  code: string;
  description: string | null;
}

export interface Role {
  id: string;
  name: string;
  description: string | null;
  builtin: boolean;
  permissions: Permission[];
}

export interface RoleBinding {
  id: string;
  role_id: string;
  user_id: string | null;
  group_id: string | null;
  scope_type: string | null;
  scope_id: string | null;
  conditions: Record<string, unknown>;
  role: Role;
}

export interface LoginRecord {
  id: string;
  username: string;
  timestamp: string;
  success: boolean;
  method: string;
  source_ip: string | null;
  reason: string | null;
}

// --- inventory ---------------------------------------------------------------------------

export interface Site {
  id: string;
  name: string;
  slug: string;
  kind?: string;
  region_id?: string | null;
  address?: string | null;
  latitude?: number | null;
  longitude?: number | null;
  netbox_id: number | null;
  device_count?: number;
}

export interface Vendor {
  id: string;
  name: string;
  slug: string;
}

export interface Platform {
  id: string;
  slug: string;
  name: string;
  scrapli_platform: string | null;
  netmiko_device_type: string | null;
  backup_commands: string[];
  tacacs_service: string;
  supports_tacacs: boolean;
  supports_config_replace: boolean;
}

export interface Credential {
  id: string;
  name: string;
  username: string;
  has_password?: boolean;
  has_ssh_key?: boolean;
  has_enable_secret?: boolean;
  rotated_at: string | null;
  is_default?: boolean;
  device_count?: number;
}

export interface Device {
  id: string;
  hostname: string;
  management_ip: string;
  site: Ref | null;
  platform: { id: string; slug: string; name: string } | null;
  vendor: Ref | null;
  serial: string | null;
  os_version: string | null;
  role: string | null;
  status: string;
  reachability: string;
  backup_enabled: boolean;
  ssh_port: number;
  tags: string[];
  netbox_id: number | null;
  credential_id: string | null;
  last_backup_at: string | null;
  last_backup_status: string | null;
  groups?: Ref[];
  created_at: string;
}

export interface DeviceIn {
  hostname: string;
  management_ip: string;
  site_id?: string | null;
  platform_id?: string | null;
  vendor_id?: string | null;
  credential_id?: string | null;
  serial?: string | null;
  os_version?: string | null;
  role?: string | null;
  status?: string;
  backup_enabled?: boolean;
  ssh_port?: number;
  tags?: string[];
  group_ids?: string[];
}

export interface DeviceGroup {
  id: string;
  name: string;
  kind: string;
  description: string | null;
  parent_id: string | null;
  dynamic_filter: Record<string, unknown> | null;
  device_count?: number;
}

export interface Topology {
  sites: {
    id: string;
    name: string;
    kind: string;
    lat: number | null;
    lon: number | null;
  }[];
  nodes: {
    id: string;
    label: string;
    site_id: string | null;
    role: string | null;
    platform: string | null;
    status: string;
    backup: string | null;
  }[];
  edges: {
    id: string;
    source: string;
    target: string;
    label: string;
    speed_mbps: number | null;
    status: string;
  }[];
}

// --- configs -----------------------------------------------------------------------------

export interface Backup {
  id: string;
  device_id: string;
  collected_at: string;
  status: string;
  changed: boolean;
  commit_sha: string | null;
  size_bytes: number | null;
  lines_added: number;
  lines_removed: number;
  author: string | null;
  reason: string | null;
  trigger: string;
  change_request_id: string | null;
  error: string | null;
  duration_ms: number | null;
  risk_score: number | null;
}

export interface BackupRunResult {
  task_id?: string;
  backups?: Backup[];
}

export interface CommitInfo {
  sha: string;
  author: string;
  email: string;
  timestamp: string;
  message: string;
}

export type DiffRowType = "equal" | "added" | "removed" | "modified" | "skip";

export interface DiffRow {
  type: DiffRowType;
  left_no?: number | null;
  left?: string | null;
  right_no?: number | null;
  right?: string | null;
  /** only on skip rows */
  count?: number;
  /** engineer whose logged command produced the new line / removed the old line */
  right_by?: Attribution | null;
  left_by?: Attribution | null;
}

export interface Attribution {
  user: string;
  at: string;
  command: string;
  /** exact: a logged command produces this line; inferred: the only engineer configuring in the window */
  confidence: "exact" | "inferred";
}

export interface DiffAuthor {
  username: string;
  added: number;
  removed: number;
  inferred: number;
  first_at: string;
  last_at: string;
}

export type RiskLevel = "low" | "medium" | "high" | "critical";

export interface RiskReport {
  score: number;
  level: RiskLevel | string;
  findings: string[];
  summary: string;
}

export interface DiffOut {
  old_rev: string;
  new_rev: string;
  unified: string;
  side_by_side: DiffRow[];
  inline?: { type: "equal" | "added" | "removed"; text: string }[] | null;
  added: number;
  removed: number;
  risk: RiskReport;
  authors?: DiffAuthor[];
  commands?: { user: string; at: string; command: string }[];
  attributed?: boolean;
}

export interface RestoreOut {
  id: string;
  device_id: string;
  backup_id: string;
  dry_run: boolean;
  status: string;
  device_diff: string | null;
  output: string | null;
  pre_restore_backup_id: string | null;
  created_at: string;
}

// --- compliance --------------------------------------------------------------------------

export type ComplianceRuleType =
  | "must_match"
  | "must_not_match"
  | "count_at_least"
  | "block_must_match";
export type Severity = "low" | "medium" | "high" | "critical";

export interface ComplianceRuleIn {
  name: string;
  description?: string | null;
  rule_type: ComplianceRuleType;
  pattern: string;
  block_start?: string | null;
  min_count?: number;
  platforms?: string[];
  device_group_id?: string | null;
  severity?: Severity;
  remediation?: string | null;
  enabled?: boolean;
}

export interface ComplianceRule extends ComplianceRuleIn {
  id: string;
}

export interface ComplianceRun {
  id: string;
  started_at: string;
  finished_at: string | null;
  devices_checked: number;
  score: number | null;
}

export interface ComplianceRunDetail {
  run: ComplianceRun;
  devices: {
    device_id: string;
    hostname: string;
    score: number;
    passed: number;
    failed: number;
  }[];
  failures: {
    device: string;
    rule: string;
    severity: string;
    detail: string;
  }[];
  failures_by_rule: Record<string, number>;
}

// --- TACACS ------------------------------------------------------------------------------

export interface TacacsServerIn {
  name: string;
  address: string;
  port?: number;
  enabled?: boolean;
  ldap_backend?: boolean;
}

export interface TacacsServer extends Required<TacacsServerIn> {
  id: string;
  config_version: number;
  config_sha256: string | null;
  last_deployed_at: string | null;
  last_heartbeat_at: string | null;
}

export interface TacacsServerCreated extends TacacsServer {
  agent_token: string;
}

export const TACACS_VENDORS = [
  "juniper",
  "cisco",
  "arista",
  "fortinet",
  "sophos",
  "mikrotik",
  "generic",
] as const;

export interface NasIn {
  name: string;
  address: string;
  key?: string | null;
  vendor: string;
  device_id?: string | null;
  device_group_id?: string | null;
  enabled?: boolean;
}

export interface Nas {
  id: string;
  name: string;
  address: string;
  vendor: string;
  device_id: string | null;
  device_group_id: string | null;
  enabled: boolean;
  key_rotated_at: string | null;
}

export interface CommandRule {
  id?: string;
  sequence: number;
  action: "permit" | "deny" | string;
  pattern: string;
  description?: string | null;
  alert_on_match?: boolean;
}

export interface PolicyIn {
  name: string;
  description?: string | null;
  priority?: number;
  group_id: string;
  device_group_id?: string | null;
  privilege_level?: number;
  junos_class?: string | null;
  fortigate_profile?: string | null;
  arista_role?: string | null;
  extra_attributes?: Record<string, unknown>;
  default_action?: string;
  time_window?: string | null;
  enabled?: boolean;
  command_rules?: CommandRule[];
}

export interface Policy {
  id: string;
  name: string;
  description: string | null;
  priority: number;
  group_id: string;
  device_group_id: string | null;
  privilege_level: number;
  junos_class: string | null;
  fortigate_profile: string | null;
  arista_role: string | null;
  extra_attributes: Record<string, unknown>;
  default_action: string;
  time_window: string | null;
  enabled: boolean;
  command_rules: (CommandRule & { id: string })[];
  updated_at: string;
}

export interface TacacsMappingIn {
  user_id: string;
  tacacs_username?: string | null;
  auth_method?: string;
  password?: string | null;
  enabled?: boolean;
  valid_until?: string | null;
}

export interface TacacsMapping {
  id: string;
  user_id: string;
  tacacs_username: string;
  auth_method: string;
  enabled: boolean;
  valid_until: string | null;
  has_password?: boolean;
}

export interface RenderOut {
  sha256: string;
  warnings: string[];
  content: string;
}

export interface Revision {
  id: string;
  server_id: string;
  version: number;
  sha256: string;
  created_at: string;
}

export interface AuthEvent {
  id: string;
  timestamp: string;
  username: string;
  device_address: string;
  source_address: string | null;
  kind: string;
  result: string;
  detail: string | null;
}

// --- activity ----------------------------------------------------------------------------

export interface CommandLog {
  id: string;
  timestamp: string;
  username: string;
  device_id: string | null;
  device_address: string;
  device_name: string | null;
  source_address: string | null;
  service: string | null;
  record_type: string;
  command: string;
  result: string;
  priv_lvl: number | null;
  dangerous?: string | null;
}

export interface SessionCommand {
  t: number;
  cmd: string;
}

export interface Recording {
  id: string;
  username: string;
  device_id: string | null;
  device_address: string;
  source_address: string | null;
  started_at: string;
  ended_at: string | null;
  duration_s: number | null;
  size_bytes: number;
  commands: SessionCommand[];
}

export interface AuditEvent {
  id: string;
  timestamp: string;
  actor_name: string;
  action: string;
  target_type: string | null;
  target_id: string | null;
  target_name: string | null;
  source_ip: string | null;
  before: Record<string, unknown> | null;
  after: Record<string, unknown> | null;
  outcome: string;
}

export interface AuditVerify {
  intact: boolean;
  events_verified: number;
}

export type ChangeState =
  | "draft"
  | "pending_approval"
  | "approved"
  | "rejected"
  | "implemented"
  | "closed"
  | "cancelled";

export interface ChangeIn {
  title: string;
  description?: string | null;
  risk?: string;
  device_ids?: string[];
  scheduled_start?: string | null;
  scheduled_end?: string | null;
  implementation_plan?: string | null;
  rollback_plan?: string | null;
  external_ticket?: string | null;
}

export interface Change {
  id: string;
  number: number;
  title: string;
  description: string | null;
  state: ChangeState | string;
  risk: string;
  requested_by: string;
  approved_by: string | null;
  approved_at: string | null;
  scheduled_start: string | null;
  scheduled_end: string | null;
  implemented_at: string | null;
  closed_at: string | null;
  device_ids: string[];
  implementation_plan: string | null;
  rollback_plan: string | null;
  pre_backup_ids: string[];
  post_backup_ids: string[];
  external_ticket: string | null;
  created_at: string;
}

export interface ChangeComment {
  id: string;
  author_id: string | null;
  created_at: string;
  body: string;
  transition: string | null;
}

export interface ChangeDetail {
  change: Change;
  comments: ChangeComment[];
  backups: {
    id: string;
    device_id: string;
    commit_sha: string | null;
    collected_at: string;
    reason: string | null;
  }[];
  allowed_transitions: string[];
}

// --- operations --------------------------------------------------------------------------

export type IntegrationKind = "netbox" | "ixpmanager" | "birdseye";

export interface IntegrationIn {
  kind: IntegrationKind;
  name: string;
  base_url: string;
  token?: string | null;
  options?: Record<string, unknown>;
  enabled?: boolean;
}

export interface Integration {
  id: string;
  kind: IntegrationKind | string;
  name: string;
  base_url: string;
  options: Record<string, unknown>;
  enabled: boolean;
  last_sync_at: string | null;
  last_sync_status: string | null;
  last_sync_detail: Record<string, unknown> | null;
}

export interface IxpVlan {
  vlan_id: number | null;
  vlan: string | null;
  ipv4: string | null;
  ipv6: string | null;
  rs_client_v4: boolean;
  rs_client_v6: boolean;
  as_macro: string | null;
  max_prefix_v4: number | null;
  max_prefix_v6: number | null;
}

export interface IxpConnection {
  state: string | null;
  ports: { switch: string | number | null; speed_mbps: number | null }[];
  vlans: IxpVlan[];
}

export interface IxpMember {
  id: string;
  asn: number;
  name: string;
  url: string | null;
  peering_policy: string | null;
  member_type: string | null;
  contacts: string[] | null;
  connections: IxpConnection[] | null;
  traffic: Record<string, unknown> | null;
}

export interface RouteServerClient {
  id: string;
  route_server: string;
  protocol: string;
  asn: number;
  member: string | null;
  neighbor: string;
  afi: string;
  state: string;
  accepted: number | null;
  filtered: number | null;
  exported: number | null;
  irr_filtered: number | null;
  rpki_invalid: number | null;
  /** per-route origin validation counts ({valid, invalid, unknown}); older collectors sent a status string */
  rpki: Record<string, number> | string | null;
  irr_status: string | null;
  since: string | null;
}

export const ALERT_EVENT_TYPES = [
  "backup_failed",
  "device_unreachable",
  "unauthorized_command",
  "compliance_failure",
  "config_drift",
  "login_failed",
  "tacacs_deploy_failed",
  "change_approved",
  "sync_failed",
] as const;

export interface AlertChannel {
  id: string;
  name: string;
  kind: string;
  enabled: boolean;
}

export interface AlertRule {
  id: string;
  name: string;
  event_type: string;
  min_severity: string;
  channel_ids: string[];
  filters: Record<string, unknown>;
  throttle_minutes: number;
  enabled: boolean;
}

export interface Alert {
  id: string;
  created_at: string;
  event_type: string;
  severity: string;
  title: string;
  body: string | null;
  device_id: string | null;
  delivered: unknown[];
  acknowledged_at: string | null;
}

export const REPORT_TYPES = [
  "device_changes",
  "config_changes",
  "user_activity",
  "compliance",
  "tacacs",
] as const;
export type ReportType = (typeof REPORT_TYPES)[number];
export const REPORT_PERIODS = ["daily", "weekly", "monthly"] as const;
export type ReportPeriod = (typeof REPORT_PERIODS)[number];

export interface ReportJson {
  title: string;
  columns: string[];
  rows: (string | number | boolean | null)[][];
  start: string;
  end: string;
}

export interface ReportSchedule {
  id: string;
  name: string;
  report_type: string;
  period: string;
  fmt: string;
  recipients: string[];
  enabled: boolean;
  last_run_at: string | null;
}

export interface Dashboard {
  devices: {
    total: number;
    by_vendor: { name: string; count: number }[];
    by_reachability: Record<string, number>;
    by_site: { name: string; count: number }[];
  };
  backups: {
    last: string | null;
    last_24h: number;
    failures_24h: number;
    devices_failing: number;
  };
  compliance: { score: number | null; trend: { t: string; score: number }[] };
  tacacs: { auth_24h: Record<string, number>; accounting_24h: number };
  top_users: { user: string; commands: number }[];
  top_devices: { device: string; commands: number }[];
  recent_changes: {
    id: string;
    device_id: string;
    device: string;
    at: string;
    author: string | null;
    reason: string | null;
    added: number;
    removed: number;
    risk: number | null;
    commit: string | null;
  }[];
  recent_audit: {
    at: string;
    actor: string;
    action: string;
    target: string | null;
  }[];
  open_changes: number;
  open_alerts: number;
}

export interface SearchResult {
  type: "device" | "site" | "user" | "change" | "ixp_member" | string;
  id: string;
  title: string;
  subtitle: string;
  href: string;
}
