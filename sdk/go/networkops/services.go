package networkops

import (
	"context"
	"iter"
	"net/http"
	"net/url"
	"time"
)

// ---------------------------------------------------------------------------------------------
// Devices

// DevicesService manages inventory devices (/devices). Results honour RBAC/ABAC scopes.
type DevicesService struct{ c *Client }

// DeviceListOptions filters device listings.
type DeviceListOptions struct {
	Q            string // substring of hostname / serial, prefix of management IP
	SiteID       string
	Platform     string // platform slug, e.g. "junos"
	Vendor       string // vendor slug, e.g. "juniper"
	Role         string
	Status       string
	GroupID      string
	BackupStatus string
	Limit        int
	Offset       int
}

func (o *DeviceListOptions) values() url.Values {
	q := query{}
	if o != nil {
		q.str("q", o.Q)
		q.str("site_id", o.SiteID)
		q.str("platform", o.Platform)
		q.str("vendor", o.Vendor)
		q.str("role", o.Role)
		q.str("status", o.Status)
		q.str("group_id", o.GroupID)
		q.str("backup_status", o.BackupStatus)
	}
	return url.Values(q)
}

// List returns one page of devices.
func (s *DevicesService) List(ctx context.Context, opts *DeviceListOptions) (*Page[Device], error) {
	limit, offset := 50, 0
	if opts != nil && opts.Limit > 0 {
		limit, offset = opts.Limit, opts.Offset
	}
	return getPage[Device](ctx, s.c, "/devices", opts.values(), limit, offset)
}

// All iterates over every matching device (pagination handled transparently).
func (s *DevicesService) All(ctx context.Context, opts *DeviceListOptions) iter.Seq2[Device, error] {
	size := 200
	if opts != nil && opts.Limit > 0 {
		size = opts.Limit
	}
	return paginate[Device](ctx, s.c, "/devices", opts.values(), size)
}

// Get fetches one device.
func (s *DevicesService) Get(ctx context.Context, id string) (*Device, error) {
	var d Device
	return &d, s.c.Do(ctx, http.MethodGet, "/devices/"+url.PathEscape(id), nil, nil, &d)
}

// Create adds a device.
func (s *DevicesService) Create(ctx context.Context, in *DeviceInput) (*Device, error) {
	var d Device
	return &d, s.c.Do(ctx, http.MethodPost, "/devices", nil, in, &d)
}

// Update patches a device; only the keys present in fields are changed.
func (s *DevicesService) Update(ctx context.Context, id string, fields map[string]any) (*Device, error) {
	var d Device
	return &d, s.c.Do(ctx, http.MethodPatch, "/devices/"+url.PathEscape(id), nil, fields, &d)
}

// Delete removes a device.
func (s *DevicesService) Delete(ctx context.Context, id string) error {
	return s.c.Do(ctx, http.MethodDelete, "/devices/"+url.PathEscape(id), nil, nil, nil)
}

// ---------------------------------------------------------------------------------------------
// Backups

// BackupsService covers configuration backups, history, diffs, drift and restore.
type BackupsService struct{ c *Client }

// BackupListOptions filters backup listings.
type BackupListOptions struct {
	DeviceID    string
	Status      string // success | unchanged | failed
	ChangedOnly bool
	Author      string
	Since       *time.Time
	Limit       int
	Offset      int
}

func (o *BackupListOptions) values() url.Values {
	q := query{}
	if o != nil {
		q.str("device_id", o.DeviceID)
		q.str("status", o.Status)
		q.boolTrue("changed_only", o.ChangedOnly)
		q.str("author", o.Author)
		q.time("since", o.Since)
	}
	return url.Values(q)
}

// List returns one page of backups.
func (s *BackupsService) List(ctx context.Context, opts *BackupListOptions) (*Page[Backup], error) {
	limit, offset := 50, 0
	if opts != nil && opts.Limit > 0 {
		limit, offset = opts.Limit, opts.Offset
	}
	return getPage[Backup](ctx, s.c, "/backups", opts.values(), limit, offset)
}

// All iterates over every matching backup.
func (s *BackupsService) All(ctx context.Context, opts *BackupListOptions) iter.Seq2[Backup, error] {
	return paginate[Backup](ctx, s.c, "/backups", opts.values(), 200)
}

// RunBackupRequest triggers a backup; empty DeviceIDs means all backup-enabled devices.
type RunBackupRequest struct {
	DeviceIDs       []string `json:"device_ids"`
	Reason          string   `json:"reason,omitempty"`
	ChangeRequestID string   `json:"change_request_id,omitempty"`
	RunAsync        bool     `json:"run_async"`
}

// RunBackupResult carries TaskID (async) or Backups (synchronous run).
type RunBackupResult struct {
	TaskID  string   `json:"task_id"`
	Backups []Backup `json:"backups"`
}

// Run triggers a backup.
func (s *BackupsService) Run(ctx context.Context, req *RunBackupRequest) (*RunBackupResult, error) {
	if req.DeviceIDs == nil {
		req.DeviceIDs = []string{}
	}
	var out RunBackupResult
	return &out, s.c.Do(ctx, http.MethodPost, "/backups/run", nil, req, &out)
}

// Config returns the stored configuration at a Git revision ("" = HEAD).
func (s *BackupsService) Config(ctx context.Context, deviceID, rev string) (string, error) {
	q := query{}
	q.str("rev", rev)
	var text string
	err := s.c.Do(ctx, http.MethodGet, "/devices/"+url.PathEscape(deviceID)+"/config", url.Values(q), nil, &text)
	return text, err
}

// DiffOptions selects the revisions to compare.
type DiffOptions struct {
	Old           string // required: commit sha, "HEAD~1", ...
	New           string // default "HEAD"
	Context       int
	IncludeInline bool
}

// Diff compares two revisions of a device configuration, including a risk analysis.
func (s *BackupsService) Diff(ctx context.Context, deviceID string, opts DiffOptions) (*Diff, error) {
	q := query{}
	q.str("old", opts.Old)
	q.str("new", opts.New)
	q.intNZ("context", opts.Context)
	q.boolTrue("include_inline", opts.IncludeInline)
	var d Diff
	return &d, s.c.Do(ctx, http.MethodGet, "/devices/"+url.PathEscape(deviceID)+"/diff", url.Values(q), nil, &d)
}

// RestoreRequest restores a backup. A real push needs DryRun=false and Confirm=true, and -
// unless the tenant disabled it - an approved change request covering the device.
type RestoreRequest struct {
	BackupID        string `json:"backup_id"`
	DryRun          bool   `json:"dry_run"`
	Confirm         bool   `json:"confirm"`
	ChangeRequestID string `json:"change_request_id,omitempty"`
}

// Restore previews (dry run) or pushes a stored configuration.
func (s *BackupsService) Restore(ctx context.Context, deviceID string, req *RestoreRequest) (*Restore, error) {
	var r Restore
	return &r, s.c.Do(ctx, http.MethodPost, "/devices/"+url.PathEscape(deviceID)+"/restore", nil, req, &r)
}

// ---------------------------------------------------------------------------------------------
// TACACS+

// TacacsService manages tac_plus-ng servers, rendering and deployment.
type TacacsService struct{ c *Client }

// Servers lists TACACS servers.
func (s *TacacsService) Servers(ctx context.Context) ([]TacacsServer, error) {
	var out []TacacsServer
	return out, s.c.Do(ctx, http.MethodGet, "/tacacs/servers", nil, nil, &out)
}

// CreateServerRequest registers a tac_plus-ng instance.
type CreateServerRequest struct {
	Name        string `json:"name"`
	Address     string `json:"address"`
	Port        int    `json:"port,omitempty"`
	Enabled     bool   `json:"enabled"`
	LDAPBackend bool   `json:"ldap_backend"`
}

// CreateServer registers a server; the returned AgentToken is shown only once.
func (s *TacacsService) CreateServer(ctx context.Context, req *CreateServerRequest) (*TacacsServer, error) {
	var out TacacsServer
	return &out, s.c.Do(ctx, http.MethodPost, "/tacacs/servers", nil, req, &out)
}

// Render previews the generated configuration (keys redacted). serverID may be "".
func (s *TacacsService) Render(ctx context.Context, serverID string) (*RenderResult, error) {
	q := query{}
	q.str("server_id", serverID)
	var out RenderResult
	return &out, s.c.Do(ctx, http.MethodGet, "/tacacs/render", url.Values(q), nil, &out)
}

// Deploy publishes a new revision for the agent to pull, validate (tac_plus-ng -P) and reload.
func (s *TacacsService) Deploy(ctx context.Context, serverID string) (*ConfigRevision, error) {
	var out ConfigRevision
	return &out, s.c.Do(ctx, http.MethodPost, "/tacacs/servers/"+url.PathEscape(serverID)+"/deploy", nil, nil, &out)
}

// Revisions lists the last 100 deployed revisions of a server.
func (s *TacacsService) Revisions(ctx context.Context, serverID string) ([]ConfigRevision, error) {
	var out []ConfigRevision
	return out, s.c.Do(ctx, http.MethodGet, "/tacacs/servers/"+url.PathEscape(serverID)+"/revisions", nil, nil, &out)
}

// RotateKey rotates a NAS client's shared secret and returns the new key (shown once).
func (s *TacacsService) RotateKey(ctx context.Context, nasID string) (string, error) {
	var out struct {
		Key string `json:"key"`
	}
	err := s.c.Do(ctx, http.MethodPost, "/tacacs/devices/"+url.PathEscape(nasID)+"/rotate-key", nil, nil, &out)
	return out.Key, err
}

// ---------------------------------------------------------------------------------------------
// Accounting

// AccountingService searches TACACS+ command accounting.
type AccountingService struct{ c *Client }

// CommandSearch filters command records. Command is a substring; prefix it with "~" for a regex.
type CommandSearch struct {
	User    string
	Device  string // hostname or management address
	Command string
	Result  string // accounted | denied
	Start   *time.Time
	End     *time.Time
	Limit   int
	Offset  int
}

func (o *CommandSearch) values() url.Values {
	q := query{}
	if o != nil {
		q.str("user", o.User)
		q.str("device", o.Device)
		q.str("command", o.Command)
		q.str("result", o.Result)
		q.time("start", o.Start)
		q.time("end", o.End)
	}
	return url.Values(q)
}

// Search returns one page of command records.
func (s *AccountingService) Search(ctx context.Context, opts *CommandSearch) (*Page[CommandRecord], error) {
	limit, offset := 100, 0
	if opts != nil && opts.Limit > 0 {
		limit, offset = opts.Limit, opts.Offset
	}
	return getPage[CommandRecord](ctx, s.c, "/accounting/commands", opts.values(), limit, offset)
}

// All iterates over every matching command record.
func (s *AccountingService) All(ctx context.Context, opts *CommandSearch) iter.Seq2[CommandRecord, error] {
	return paginate[CommandRecord](ctx, s.c, "/accounting/commands", opts.values(), 500)
}

// ---------------------------------------------------------------------------------------------
// Compliance

// ComplianceService manages compliance rules and runs.
type ComplianceService struct{ c *Client }

// Rules lists compliance rules.
func (s *ComplianceService) Rules(ctx context.Context) ([]ComplianceRule, error) {
	var out []ComplianceRule
	return out, s.c.Do(ctx, http.MethodGet, "/compliance/rules", nil, nil, &out)
}

// CreateRule adds a rule.
func (s *ComplianceService) CreateRule(ctx context.Context, r *ComplianceRule) (*ComplianceRule, error) {
	var out ComplianceRule
	return &out, s.c.Do(ctx, http.MethodPost, "/compliance/rules", nil, r, &out)
}

// Run evaluates all rules now.
func (s *ComplianceService) Run(ctx context.Context) (*ComplianceRun, error) {
	var out ComplianceRun
	return &out, s.c.Do(ctx, http.MethodPost, "/compliance/run", nil, nil, &out)
}

// Runs lists recent runs (newest first).
func (s *ComplianceService) Runs(ctx context.Context, limit int) ([]ComplianceRun, error) {
	q := query{}
	q.intNZ("limit", limit)
	var out []ComplianceRun
	return out, s.c.Do(ctx, http.MethodGet, "/compliance/runs", url.Values(q), nil, &out)
}

// ---------------------------------------------------------------------------------------------
// Changes

// ChangesService manages change requests
// (draft -> pending_approval -> approved -> implemented -> closed; reject / cancel).
type ChangesService struct{ c *Client }

// List returns one page of change requests.
func (s *ChangesService) List(ctx context.Context, state, q string, limit, offset int) (*Page[ChangeRequest], error) {
	qq := query{}
	qq.str("state", state)
	qq.str("q", q)
	if limit <= 0 {
		limit = 50
	}
	return getPage[ChangeRequest](ctx, s.c, "/changes", url.Values(qq), limit, offset)
}

// All iterates over change requests, optionally filtered by state.
func (s *ChangesService) All(ctx context.Context, state string) iter.Seq2[ChangeRequest, error] {
	qq := query{}
	qq.str("state", state)
	return paginate[ChangeRequest](ctx, s.c, "/changes", url.Values(qq), 100)
}

// Create opens a draft change request.
func (s *ChangesService) Create(ctx context.Context, in *ChangeInput) (*ChangeRequest, error) {
	if in.DeviceIDs == nil {
		in.DeviceIDs = []string{}
	}
	var out ChangeRequest
	return &out, s.c.Do(ctx, http.MethodPost, "/changes", nil, in, &out)
}

// Transition applies a workflow transition: submit, approve, reject, implement, close, cancel.
// approve/implement trigger pre/post-change backups unless takeBackup is false.
func (s *ChangesService) Transition(ctx context.Context, id, transition, comment string, takeBackup bool) (*ChangeRequest, error) {
	body := map[string]any{"transition": transition, "take_backup": takeBackup}
	if comment != "" {
		body["comment"] = comment
	}
	var out ChangeRequest
	return &out, s.c.Do(ctx, http.MethodPost, "/changes/"+url.PathEscape(id)+"/transition", nil, body, &out)
}

// Comment adds a comment and returns its id.
func (s *ChangesService) Comment(ctx context.Context, id, body string) (string, error) {
	var out struct {
		ID string `json:"id"`
	}
	err := s.c.Do(ctx, http.MethodPost, "/changes/"+url.PathEscape(id)+"/comments", nil, map[string]string{"body": body}, &out)
	return out.ID, err
}

// ---------------------------------------------------------------------------------------------
// Audit

// AuditService reads the tamper-evident audit trail.
type AuditService struct{ c *Client }

// AuditFilter filters audit events. Action may end in "*" for a prefix match.
type AuditFilter struct {
	Actor      string
	Action     string
	TargetType string
	TargetID   string
	Start      *time.Time
	End        *time.Time
}

func (o *AuditFilter) values() url.Values {
	q := query{}
	if o != nil {
		q.str("actor", o.Actor)
		q.str("action", o.Action)
		q.str("target_type", o.TargetType)
		q.str("target_id", o.TargetID)
		q.time("start", o.Start)
		q.time("end", o.End)
	}
	return url.Values(q)
}

// All iterates over matching audit events (newest first).
func (s *AuditService) All(ctx context.Context, f *AuditFilter) iter.Seq2[AuditEvent, error] {
	return paginate[AuditEvent](ctx, s.c, "/audit", f.values(), 500)
}

// Verify recomputes the per-tenant hash chain.
func (s *AuditService) Verify(ctx context.Context) (*AuditVerification, error) {
	var out AuditVerification
	return &out, s.c.Do(ctx, http.MethodGet, "/audit/verify", nil, nil, &out)
}

// ---------------------------------------------------------------------------------------------
// Misc

// Me returns the authenticated user and effective permissions.
func (c *Client) Me(ctx context.Context) (*Me, error) {
	var out Me
	return &out, c.Do(ctx, http.MethodGet, "/auth/me", nil, nil, &out)
}
