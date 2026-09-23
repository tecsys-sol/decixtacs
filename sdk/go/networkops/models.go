package networkops

import (
	"encoding/json"
	"fmt"
	"time"
)

// Page is one page of a paginated list endpoint.
type Page[T any] struct {
	Items  []T `json:"items"`
	Total  int `json:"total"`
	Limit  int `json:"limit"`
	Offset int `json:"offset"`
}

// HasMore reports whether more items exist after this page.
func (p *Page[T]) HasMore() bool { return p.Offset+len(p.Items) < p.Total }

// Ref is a reference to a named object (site, vendor, group).
type Ref struct {
	ID   string `json:"id"`
	Name string `json:"name"`
}

// PlatformRef references a platform (junos, eos, ios, nxos, fortios, sfos, routeros ...).
type PlatformRef struct {
	ID   string `json:"id"`
	Slug string `json:"slug"`
	Name string `json:"name"`
}

// Me is the authenticated user with effective permissions.
type Me struct {
	ID          string   `json:"id"`
	TenantID    string   `json:"tenant_id"`
	Username    string   `json:"username"`
	Email       *string  `json:"email"`
	FullName    *string  `json:"full_name"`
	IsSuperuser bool     `json:"is_superuser"`
	MFAEnabled  bool     `json:"mfa_enabled"`
	AuthSource  string   `json:"auth_source"`
	Permissions []string `json:"permissions"`
	Groups      []string `json:"groups"`
}

// Device is an inventory device.
type Device struct {
	ID               string       `json:"id"`
	Hostname         string       `json:"hostname"`
	ManagementIP     string       `json:"management_ip"`
	Site             *Ref         `json:"site"`
	Platform         *PlatformRef `json:"platform"`
	Vendor           *Ref         `json:"vendor"`
	Serial           *string      `json:"serial"`
	OSVersion        *string      `json:"os_version"`
	Role             *string      `json:"role"`
	Status           string       `json:"status"`
	Reachability     string       `json:"reachability"`
	BackupEnabled    bool         `json:"backup_enabled"`
	SSHPort          int          `json:"ssh_port"`
	Tags             []string     `json:"tags"`
	NetboxID         *int         `json:"netbox_id"`
	CredentialID     *string      `json:"credential_id"`
	LastBackupAt     *time.Time   `json:"last_backup_at"`
	LastBackupStatus *string      `json:"last_backup_status"`
	Groups           []Ref        `json:"groups"`
	CreatedAt        time.Time    `json:"created_at"`
}

// DeviceInput is the body for creating a device. Zero values are omitted where optional.
type DeviceInput struct {
	Hostname      string   `json:"hostname"`
	ManagementIP  string   `json:"management_ip"`
	SiteID        string   `json:"site_id,omitempty"`
	RackID        string   `json:"rack_id,omitempty"`
	PlatformID    string   `json:"platform_id,omitempty"`
	VendorID      string   `json:"vendor_id,omitempty"`
	CredentialID  string   `json:"credential_id,omitempty"`
	Serial        string   `json:"serial,omitempty"`
	OSVersion     string   `json:"os_version,omitempty"`
	Role          string   `json:"role,omitempty"`
	Status        string   `json:"status,omitempty"`
	BackupEnabled *bool    `json:"backup_enabled,omitempty"`
	SSHPort       int      `json:"ssh_port,omitempty"`
	Tags          []string `json:"tags,omitempty"`
	GroupIDs      []string `json:"group_ids,omitempty"`
}

// Backup is one configuration collection result.
type Backup struct {
	ID              string    `json:"id"`
	DeviceID        string    `json:"device_id"`
	CollectedAt     time.Time `json:"collected_at"`
	Status          string    `json:"status"` // success | unchanged | failed
	Changed         bool      `json:"changed"`
	CommitSHA       *string   `json:"commit_sha"`
	SizeBytes       *int      `json:"size_bytes"`
	LinesAdded      int       `json:"lines_added"`
	LinesRemoved    int       `json:"lines_removed"`
	Author          *string   `json:"author"`
	Reason          *string   `json:"reason"`
	Trigger         string    `json:"trigger"`
	ChangeRequestID *string   `json:"change_request_id"`
	Error           *string   `json:"error"`
	DurationMS      *int      `json:"duration_ms"`
	RiskScore       *int      `json:"risk_score"`
}

// Diff is the comparison of two Git revisions of a device configuration.
type Diff struct {
	OldRev     string           `json:"old_rev"`
	NewRev     string           `json:"new_rev"`
	Unified    string           `json:"unified"`
	SideBySide []map[string]any `json:"side_by_side"`
	Inline     []map[string]any `json:"inline"`
	Added      int              `json:"added"`
	Removed    int              `json:"removed"`
	Risk       Risk             `json:"risk"`
}

// Risk is the change risk analysis of a diff.
type Risk struct {
	Score    int              `json:"score"`
	Level    string           `json:"level"`
	Findings []map[string]any `json:"findings"`
	Summary  string           `json:"summary"`
}

// Restore is the result of a (dry-run) configuration restore.
type Restore struct {
	ID                 string    `json:"id"`
	DeviceID           string    `json:"device_id"`
	BackupID           string    `json:"backup_id"`
	DryRun             bool      `json:"dry_run"`
	Status             string    `json:"status"` // diffed | pushed | failed
	DeviceDiff         *string   `json:"device_diff"`
	Output             *string   `json:"output"`
	PreRestoreBackupID *string   `json:"pre_restore_backup_id"`
	CreatedAt          time.Time `json:"created_at"`
}

// TacacsServer is a tac_plus-ng instance managed by the platform.
type TacacsServer struct {
	ID              string     `json:"id"`
	Name            string     `json:"name"`
	Address         string     `json:"address"`
	Port            int        `json:"port"`
	Enabled         bool       `json:"enabled"`
	LDAPBackend     bool       `json:"ldap_backend"`
	ConfigVersion   int        `json:"config_version"`
	ConfigSHA256    *string    `json:"config_sha256"`
	LastDeployedAt  *time.Time `json:"last_deployed_at"`
	LastHeartbeatAt *time.Time `json:"last_heartbeat_at"`
	// AgentToken is only returned by CreateServer (shown once).
	AgentToken string `json:"agent_token,omitempty"`
}

// RenderResult is a rendered tac_plus-ng configuration preview (keys redacted).
type RenderResult struct {
	SHA256   string   `json:"sha256"`
	Warnings []string `json:"warnings"`
	Content  string   `json:"content"`
}

// ConfigRevision is a deployed tac_plus-ng configuration revision.
type ConfigRevision struct {
	ID        string    `json:"id"`
	ServerID  string    `json:"server_id"`
	Version   int       `json:"version"`
	SHA256    string    `json:"sha256"`
	CreatedAt time.Time `json:"created_at"`
}

// CommandRecord is one TACACS+ accounting (or denied authorization) record.
type CommandRecord struct {
	ID            string    `json:"id"`
	Timestamp     time.Time `json:"timestamp"`
	Username      string    `json:"username"`
	DeviceID      *string   `json:"device_id"`
	DeviceAddress string    `json:"device_address"`
	DeviceName    *string   `json:"device_name"`
	SourceAddress *string   `json:"source_address"`
	Service       *string   `json:"service"`
	RecordType    string    `json:"record_type"`
	Command       string    `json:"command"`
	Result        string    `json:"result"`
	PrivLvl       *int      `json:"priv_lvl"`
	Dangerous     *string   `json:"dangerous"`
}

// ComplianceRun is one evaluation of all compliance rules.
type ComplianceRun struct {
	ID             string     `json:"id"`
	StartedAt      time.Time  `json:"started_at"`
	FinishedAt     *time.Time `json:"finished_at"`
	DevicesChecked int        `json:"devices_checked"`
	Score          *float64   `json:"score"`
}

// ComplianceRule is a regex based configuration rule.
type ComplianceRule struct {
	ID            string   `json:"id,omitempty"`
	Name          string   `json:"name"`
	Description   *string  `json:"description,omitempty"`
	RuleType      string   `json:"rule_type"` // must_match | must_not_match | count_at_least | block_must_match
	Pattern       string   `json:"pattern"`
	BlockStart    *string  `json:"block_start,omitempty"`
	MinCount      int      `json:"min_count,omitempty"`
	Platforms     []string `json:"platforms,omitempty"`
	DeviceGroupID *string  `json:"device_group_id,omitempty"`
	Severity      string   `json:"severity,omitempty"`
	Remediation   *string  `json:"remediation,omitempty"`
	Enabled       bool     `json:"enabled"`
}

// ChangeRequest is a change management ticket.
type ChangeRequest struct {
	ID                 string     `json:"id"`
	Number             int        `json:"number"`
	Title              string     `json:"title"`
	Description        *string    `json:"description"`
	State              string     `json:"state"`
	Risk               string     `json:"risk"`
	RequestedBy        string     `json:"requested_by"`
	ApprovedBy         *string    `json:"approved_by"`
	ApprovedAt         *time.Time `json:"approved_at"`
	ScheduledStart     *time.Time `json:"scheduled_start"`
	ScheduledEnd       *time.Time `json:"scheduled_end"`
	ImplementedAt      *time.Time `json:"implemented_at"`
	ClosedAt           *time.Time `json:"closed_at"`
	DeviceIDs          []string   `json:"device_ids"`
	ImplementationPlan *string    `json:"implementation_plan"`
	RollbackPlan       *string    `json:"rollback_plan"`
	PreBackupIDs       []string   `json:"pre_backup_ids"`
	PostBackupIDs      []string   `json:"post_backup_ids"`
	ExternalTicket     *string    `json:"external_ticket"`
	CreatedAt          time.Time  `json:"created_at"`
}

// Key returns the human readable key, e.g. "CHG-42".
func (c *ChangeRequest) Key() string { return fmt.Sprintf("CHG-%d", c.Number) }

// ChangeInput is the body for creating or editing a change request.
type ChangeInput struct {
	Title              string     `json:"title"`
	Description        string     `json:"description,omitempty"`
	Risk               string     `json:"risk,omitempty"`
	DeviceIDs          []string   `json:"device_ids"`
	ScheduledStart     *time.Time `json:"scheduled_start,omitempty"`
	ScheduledEnd       *time.Time `json:"scheduled_end,omitempty"`
	ImplementationPlan string     `json:"implementation_plan,omitempty"`
	RollbackPlan       string     `json:"rollback_plan,omitempty"`
	ExternalTicket     string     `json:"external_ticket,omitempty"`
}

// AuditEvent is one entry of the tamper-evident audit trail.
type AuditEvent struct {
	ID         string         `json:"id"`
	Timestamp  time.Time      `json:"timestamp"`
	ActorName  string         `json:"actor_name"`
	Action     string         `json:"action"`
	TargetType *string        `json:"target_type"`
	TargetID   *string        `json:"target_id"`
	TargetName *string        `json:"target_name"`
	SourceIP   *string        `json:"source_ip"`
	Before     map[string]any `json:"before"`
	After      map[string]any `json:"after"`
	Outcome    string         `json:"outcome"`
}

// AuditVerification is the result of recomputing the audit hash chain.
type AuditVerification struct {
	Intact         bool `json:"intact"`
	EventsVerified int  `json:"events_verified"`
}

type tokenPair struct {
	AccessToken  string `json:"access_token"`
	RefreshToken string `json:"refresh_token"`
	ExpiresIn    int    `json:"expires_in"`
}

// RawJSON is returned by endpoints without a typed model.
type RawJSON = json.RawMessage
