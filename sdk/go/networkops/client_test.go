package networkops

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync"
	"testing"
	"time"
)

// fakeAPI is a tiny in-memory NetworkOps API used by the tests.
type fakeAPI struct {
	t        *testing.T
	mu       sync.Mutex
	calls    []*http.Request
	bodies   []string
	handlers map[string]http.HandlerFunc // "METHOD /path" (path without /api/v1)
}

func newFake(t *testing.T) (*fakeAPI, *httptest.Server) {
	f := &fakeAPI{t: t, handlers: map[string]http.HandlerFunc{}}
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		b, _ := io.ReadAll(r.Body)
		f.mu.Lock()
		f.calls = append(f.calls, r)
		f.bodies = append(f.bodies, string(b))
		h := f.handlers[r.Method+" "+strings.TrimPrefix(r.URL.Path, "/api/v1")]
		f.mu.Unlock()
		if h == nil {
			w.WriteHeader(http.StatusNotFound)
			fmt.Fprint(w, `{"detail":"no handler"}`)
			return
		}
		h(w, r)
	}))
	t.Cleanup(srv.Close)
	return f, srv
}

func (f *fakeAPI) on(key string, h http.HandlerFunc) { f.handlers[key] = h }

func (f *fakeAPI) last(key string) (*http.Request, string) {
	f.mu.Lock()
	defer f.mu.Unlock()
	for i := len(f.calls) - 1; i >= 0; i-- {
		r := f.calls[i]
		if r.Method+" "+strings.TrimPrefix(r.URL.Path, "/api/v1") == key {
			return r, f.bodies[i]
		}
	}
	return nil, ""
}

func (f *fakeAPI) count(key string) int {
	f.mu.Lock()
	defer f.mu.Unlock()
	n := 0
	for _, r := range f.calls {
		if r.Method+" "+strings.TrimPrefix(r.URL.Path, "/api/v1") == key {
			n++
		}
	}
	return n
}

func writeJSON(w http.ResponseWriter, status int, v any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(v)
}

func noSleep(context.Context, time.Duration) error { return nil }

func tokenClient(t *testing.T, srv *httptest.Server) *Client {
	c, err := New(srv.URL, WithToken("nomt_test"))
	if err != nil {
		t.Fatal(err)
	}
	c.sleep = noSleep
	return c
}

func device(i int) map[string]any {
	return map[string]any{
		"id": fmt.Sprintf("00000000-0000-0000-0000-%012d", i), "hostname": fmt.Sprintf("r%d", i),
		"management_ip": fmt.Sprintf("192.0.2.%d", i), "status": "active", "reachability": "up",
		"platform":       map[string]any{"id": "p", "slug": "junos", "name": "Juniper Junos"},
		"backup_enabled": true, "ssh_port": 22, "tags": []string{"ix"}, "groups": []any{},
		"last_backup_at": "2026-09-23T10:00:00Z", "created_at": "2026-09-01T00:00:00+00:00",
	}
}

func TestNewValidatesOptions(t *testing.T) {
	if _, err := New("https://nom.example.net"); err == nil {
		t.Fatal("expected error without credentials")
	}
	if _, err := New("https://nom.example.net", WithToken("a"), WithPassword("u", "p", "")); err == nil {
		t.Fatal("expected error with both auth methods")
	}
	if _, err := New("not a url", WithToken("a")); err == nil {
		t.Fatal("expected error for invalid URL")
	}
	c, err := New("https://nom.example.net/api/v1/", WithToken("a"))
	if err != nil || c.baseURL.String() != "https://nom.example.net/api/v1" {
		t.Fatalf("base url: %v %v", c, err)
	}
}

func TestTokenAuthAndHeaders(t *testing.T) {
	f, srv := newFake(t)
	f.on("GET /auth/me", func(w http.ResponseWriter, r *http.Request) {
		writeJSON(w, 200, map[string]any{"id": "u1", "tenant_id": "t1", "username": "alice", "permissions": []string{"devices:read"}})
	})
	c, _ := New(srv.URL, WithToken("nomt_test"), WithActAsTenant("customer-a"))
	me, err := c.Me(context.Background())
	if err != nil || me.Username != "alice" || me.Permissions[0] != "devices:read" {
		t.Fatalf("me: %+v %v", me, err)
	}
	r, _ := f.last("GET /auth/me")
	if r.Header.Get("Authorization") != "Bearer nomt_test" || r.Header.Get("X-Tenant") != "customer-a" {
		t.Fatalf("headers: %v", r.Header)
	}
	if !strings.HasPrefix(r.Header.Get("User-Agent"), "networkops-go/") {
		t.Fatalf("user agent: %q", r.Header.Get("User-Agent"))
	}
}

func TestPasswordLoginRefreshAndRotation(t *testing.T) {
	f, srv := newFake(t)
	n := 0
	issue := func(w http.ResponseWriter) {
		n++
		writeJSON(w, 200, map[string]any{"access_token": fmt.Sprintf("acc%d", n), "refresh_token": fmt.Sprintf("ref%d", n),
			"token_type": "bearer", "expires_in": 900})
	}
	f.on("POST /auth/login", func(w http.ResponseWriter, r *http.Request) { issue(w) })
	f.on("POST /auth/refresh", func(w http.ResponseWriter, r *http.Request) { issue(w) })
	f.on("GET /auth/me", func(w http.ResponseWriter, r *http.Request) {
		writeJSON(w, 200, map[string]any{"id": "u1", "tenant_id": "t1", "username": "alice"})
	})
	now := time.Unix(1_000_000, 0)
	c, err := New(srv.URL, WithPassword("alice", "pw", "acme"), WithOTP(func() string { return "123456" }))
	if err != nil {
		t.Fatal(err)
	}
	c.now = func() time.Time { return now }
	ctx := context.Background()

	if _, err := c.Me(ctx); err != nil {
		t.Fatal(err)
	}
	_, body := f.last("POST /auth/login")
	var login map[string]string
	_ = json.Unmarshal([]byte(body), &login)
	if login["tenant"] != "acme" || login["otp"] != "123456" || login["username"] != "alice" {
		t.Fatalf("login body: %s", body)
	}
	if r, _ := f.last("GET /auth/me"); r.Header.Get("Authorization") != "Bearer acc1" {
		t.Fatal("expected acc1")
	}

	now = now.Add(600 * time.Second) // still valid
	_, _ = c.Me(ctx)
	if f.count("POST /auth/refresh") != 0 {
		t.Fatal("refreshed too early")
	}
	now = now.Add(290 * time.Second) // inside the 30 s skew
	_, _ = c.Me(ctx)
	if _, b := f.last("POST /auth/refresh"); b != `{"refresh_token":"ref1"}` {
		t.Fatalf("refresh body: %s", b)
	}
	if r, _ := f.last("GET /auth/me"); r.Header.Get("Authorization") != "Bearer acc2" {
		t.Fatal("expected acc2 after refresh")
	}
	now = now.Add(2000 * time.Second)
	_, _ = c.Me(ctx)
	if _, b := f.last("POST /auth/refresh"); b != `{"refresh_token":"ref2"}` {
		t.Fatalf("rotated refresh token not used: %s", b)
	}
}

func TestRefreshFailureFallsBackToLogin(t *testing.T) {
	f, srv := newFake(t)
	logins := 0
	f.on("POST /auth/login", func(w http.ResponseWriter, r *http.Request) {
		logins++
		writeJSON(w, 200, map[string]any{"access_token": fmt.Sprintf("login%d", logins), "refresh_token": "r", "expires_in": 60})
	})
	f.on("POST /auth/refresh", func(w http.ResponseWriter, r *http.Request) {
		writeJSON(w, 401, map[string]any{"detail": map[string]string{"code": "token_reuse", "message": "reuse"}})
	})
	f.on("GET /audit/verify", func(w http.ResponseWriter, r *http.Request) {
		writeJSON(w, 200, map[string]any{"intact": true, "events_verified": 3})
	})
	now := time.Unix(0, 0)
	c, _ := New(srv.URL, WithPassword("alice", "pw", ""))
	c.now = func() time.Time { return now }
	_, _ = c.Audit.Verify(context.Background())
	now = now.Add(time.Hour)
	v, err := c.Audit.Verify(context.Background())
	if err != nil || !v.Intact || logins != 2 {
		t.Fatalf("verify=%+v err=%v logins=%d", v, err, logins)
	}
}

func TestUnexpected401RenewsOnce(t *testing.T) {
	f, srv := newFake(t)
	f.on("POST /auth/login", func(w http.ResponseWriter, r *http.Request) {
		writeJSON(w, 200, map[string]any{"access_token": "a", "refresh_token": "r", "expires_in": 900})
	})
	f.on("POST /auth/refresh", func(w http.ResponseWriter, r *http.Request) {
		writeJSON(w, 200, map[string]any{"access_token": "b", "refresh_token": "r2", "expires_in": 900})
	})
	calls := 0
	f.on("GET /auth/me", func(w http.ResponseWriter, r *http.Request) {
		calls++
		if r.Header.Get("Authorization") == "Bearer a" {
			writeJSON(w, 401, map[string]any{"detail": "invalid or expired token"})
			return
		}
		writeJSON(w, 200, map[string]any{"id": "u", "tenant_id": "t", "username": "alice"})
	})
	c, _ := New(srv.URL, WithPassword("alice", "pw", ""))
	if _, err := c.Me(context.Background()); err != nil || calls != 2 {
		t.Fatalf("err=%v calls=%d", err, calls)
	}
}

func TestMFARequired(t *testing.T) {
	f, srv := newFake(t)
	f.on("POST /auth/login", func(w http.ResponseWriter, r *http.Request) {
		writeJSON(w, 401, map[string]any{"detail": map[string]string{"code": "mfa_required", "message": "one-time password required"}})
	})
	c, _ := New(srv.URL, WithPassword("alice", "pw", ""))
	err := c.Login(context.Background())
	if !IsMFARequired(err) || !IsUnauthorized(err) {
		t.Fatalf("expected mfa_required, got %v", err)
	}
	if !strings.Contains(err.Error(), "one-time password required") {
		t.Fatalf("message: %v", err)
	}
}

func TestDevicesAllPaginates(t *testing.T) {
	f, srv := newFake(t)
	f.on("GET /devices", func(w http.ResponseWriter, r *http.Request) {
		var items []any
		off := r.URL.Query().Get("offset")
		switch off {
		case "0":
			items = []any{device(0), device(1)}
		case "2":
			items = []any{device(2), device(3)}
		case "4":
			items = []any{device(4)}
		}
		var o int
		fmt.Sscan(off, &o)
		writeJSON(w, 200, map[string]any{"items": items, "total": 5, "limit": 2, "offset": o})
	})
	c := tokenClient(t, srv)
	var names []string
	for d, err := range c.Devices.All(context.Background(), &DeviceListOptions{Vendor: "juniper", Limit: 2}) {
		if err != nil {
			t.Fatal(err)
		}
		names = append(names, d.Hostname)
		if d.Platform == nil || d.Platform.Slug != "junos" || d.LastBackupAt == nil {
			t.Fatalf("decoded device: %+v", d)
		}
	}
	if strings.Join(names, ",") != "r0,r1,r2,r3,r4" {
		t.Fatalf("names: %v", names)
	}
	if f.count("GET /devices") != 3 {
		t.Fatalf("expected 3 page requests, got %d", f.count("GET /devices"))
	}
	r, _ := f.last("GET /devices")
	if r.URL.Query().Get("vendor") != "juniper" || r.URL.Query().Get("limit") != "2" {
		t.Fatalf("query: %v", r.URL.RawQuery)
	}
}

func TestIteratorStopsEarlyAndReportsErrors(t *testing.T) {
	f, srv := newFake(t)
	f.on("GET /audit", func(w http.ResponseWriter, r *http.Request) {
		writeJSON(w, 503, map[string]any{"detail": "service unavailable"})
	})
	c := tokenClient(t, srv)
	var gotErr error
	for _, err := range c.Audit.All(context.Background(), &AuditFilter{Action: "tacacs.*"}) {
		gotErr = err
	}
	var apiErr *APIError
	if !errors.As(gotErr, &apiErr) || apiErr.StatusCode != 503 {
		t.Fatalf("expected 503 APIError, got %v", gotErr)
	}
	if n := f.count("GET /audit"); n != 3 { // 1 + 2 retries (GET is idempotent, 503 is retryable)
		t.Fatalf("expected 3 attempts, got %d", n)
	}
}

func TestBackupsDiffConfigRestore(t *testing.T) {
	f, srv := newFake(t)
	f.on("GET /devices/d1/config", func(w http.ResponseWriter, r *http.Request) {
		fmt.Fprint(w, "set system host-name r1\n")
	})
	f.on("GET /devices/d1/diff", func(w http.ResponseWriter, r *http.Request) {
		writeJSON(w, 200, map[string]any{"old_rev": "HEAD~1", "new_rev": "HEAD", "unified": "--- a\n+++ b\n",
			"side_by_side": []any{}, "added": 3, "removed": 1, "risk": map[string]any{"score": 40, "level": "medium"}})
	})
	f.on("POST /devices/d1/restore", func(w http.ResponseWriter, r *http.Request) {
		writeJSON(w, 200, map[string]any{"id": "x", "device_id": "d1", "backup_id": "b1", "dry_run": true,
			"status": "diffed", "device_diff": "[edit]", "created_at": "2026-09-23T10:00:00Z"})
	})
	c := tokenClient(t, srv)
	ctx := context.Background()
	cfg, err := c.Backups.Config(ctx, "d1", "abc")
	if err != nil || !strings.HasPrefix(cfg, "set system") {
		t.Fatalf("config %q %v", cfg, err)
	}
	if r, _ := f.last("GET /devices/d1/config"); r.URL.Query().Get("rev") != "abc" {
		t.Fatal("rev not sent")
	}
	d, err := c.Backups.Diff(ctx, "d1", DiffOptions{Old: "HEAD~1"})
	if err != nil || d.Added != 3 || d.Risk.Level != "medium" {
		t.Fatalf("diff %+v %v", d, err)
	}
	if r, _ := f.last("GET /devices/d1/diff"); r.URL.Query().Get("old") != "HEAD~1" || r.URL.Query().Has("new") {
		t.Fatalf("diff query %s", r.URL.RawQuery)
	}
	res, err := c.Backups.Restore(ctx, "d1", &RestoreRequest{BackupID: "b1", DryRun: true})
	if err != nil || res.Status != "diffed" {
		t.Fatalf("restore %+v %v", res, err)
	}
	if _, body := f.last("POST /devices/d1/restore"); body != `{"backup_id":"b1","dry_run":true,"confirm":false}`+"\n" && body != `{"backup_id":"b1","dry_run":true,"confirm":false}` {
		t.Fatalf("restore body %q", body)
	}
}

func TestTacacsRenderDeploy(t *testing.T) {
	f, srv := newFake(t)
	f.on("GET /tacacs/render", func(w http.ResponseWriter, r *http.Request) {
		writeJSON(w, 200, map[string]any{"sha256": strings.Repeat("f", 64), "warnings": []string{"mikrotik skipped"}, "content": `key = "***"`})
	})
	f.on("POST /tacacs/servers/s1/deploy", func(w http.ResponseWriter, r *http.Request) {
		writeJSON(w, 200, map[string]any{"id": "rev", "server_id": "s1", "version": 4, "sha256": strings.Repeat("f", 64),
			"created_at": "2026-09-23T10:00:00Z"})
	})
	c := tokenClient(t, srv)
	ren, err := c.Tacacs.Render(context.Background(), "s1")
	if err != nil || len(ren.Warnings) != 1 {
		t.Fatalf("render %+v %v", ren, err)
	}
	rev, err := c.Tacacs.Deploy(context.Background(), "s1")
	if err != nil || rev.Version != 4 || rev.CreatedAt.Year() != 2026 {
		t.Fatalf("deploy %+v %v", rev, err)
	}
	if f.count("POST /tacacs/servers/s1/deploy") != 1 {
		t.Fatal("deploy not called exactly once")
	}
}

func TestAccountingSearchQuery(t *testing.T) {
	f, srv := newFake(t)
	f.on("GET /accounting/commands", func(w http.ResponseWriter, r *http.Request) {
		writeJSON(w, 200, map[string]any{"items": []any{map[string]any{
			"id": "c1", "timestamp": "2026-09-23T10:01:02Z", "username": "alice", "device_address": "192.0.2.1",
			"command": "request system reboot", "result": "accounted", "record_type": "stop", "dangerous": "reboot"}},
			"total": 1, "limit": 100, "offset": 0})
	})
	c := tokenClient(t, srv)
	start := time.Date(2026, 9, 23, 0, 0, 0, 0, time.FixedZone("CEST", 7200))
	p, err := c.Accounting.Search(context.Background(), &CommandSearch{User: "alice", Command: "~^request", Start: &start})
	if err != nil || p.Total != 1 || p.HasMore() || *p.Items[0].Dangerous != "reboot" {
		t.Fatalf("search %+v %v", p, err)
	}
	q := func() map[string][]string { r, _ := f.last("GET /accounting/commands"); return r.URL.Query() }()
	if q["start"][0] != "2026-09-22T22:00:00Z" || q["command"][0] != "~^request" || q["user"][0] != "alice" {
		t.Fatalf("query %v", q)
	}
	if _, ok := q["device"]; ok {
		t.Fatal("empty filters must not be sent")
	}
}

func TestChangesTransitionAndConflict(t *testing.T) {
	f, srv := newFake(t)
	f.on("POST /changes", func(w http.ResponseWriter, r *http.Request) {
		writeJSON(w, 201, map[string]any{"id": "c1", "number": 42, "title": "Add IX VLAN", "state": "draft",
			"risk": "low", "requested_by": "u1", "device_ids": []string{}, "created_at": "2026-09-23T10:00:00Z"})
	})
	f.on("POST /changes/c1/transition", func(w http.ResponseWriter, r *http.Request) {
		var b map[string]any
		_ = json.NewDecoder(r.Body).Decode(&b)
		w.Header().Set("X-Request-ID", "rid-9")
		writeJSON(w, 409, map[string]any{"detail": "four-eyes principle: requester cannot approve their own change"})
	})
	c := tokenClient(t, srv)
	chg, err := c.Changes.Create(context.Background(), &ChangeInput{Title: "Add IX VLAN", Risk: "low"})
	if err != nil || chg.Key() != "CHG-42" {
		t.Fatalf("create %+v %v", chg, err)
	}
	if _, body := f.last("POST /changes"); !strings.Contains(body, `"device_ids":[]`) {
		t.Fatalf("device_ids must be sent as an empty list: %s", body)
	}
	_, err = c.Changes.Transition(context.Background(), "c1", "approve", "lgtm", true)
	if !IsConflict(err) {
		t.Fatalf("expected conflict, got %v", err)
	}
	var apiErr *APIError
	errors.As(err, &apiErr)
	if apiErr.RequestID != "rid-9" || !strings.Contains(apiErr.Error(), "four-eyes") {
		t.Fatalf("api error %+v", apiErr)
	}
	if f.count("POST /changes/c1/transition") != 1 {
		t.Fatal("POST 409 must not be retried")
	}
	_, body := f.last("POST /changes/c1/transition")
	if !strings.Contains(body, `"transition":"approve"`) || !strings.Contains(body, `"take_backup":true`) {
		t.Fatalf("transition body %s", body)
	}
}

func TestRetriesOn503And429(t *testing.T) {
	f, srv := newFake(t)
	n := 0
	f.on("GET /compliance/runs", func(w http.ResponseWriter, r *http.Request) {
		n++
		switch n {
		case 1:
			w.WriteHeader(503)
		case 2:
			w.Header().Set("Retry-After", "1")
			writeJSON(w, 429, map[string]any{"detail": "rate limit exceeded"})
		default:
			writeJSON(w, 200, []any{map[string]any{"id": "r", "started_at": "2026-09-23T02:30:00Z", "devices_checked": 3, "score": 97.5}})
		}
	})
	c := tokenClient(t, srv)
	var slept []time.Duration
	c.sleep = func(_ context.Context, d time.Duration) error { slept = append(slept, d); return nil }
	runs, err := c.Compliance.Runs(context.Background(), 1)
	if err != nil || len(runs) != 1 || *runs[0].Score != 97.5 {
		t.Fatalf("runs %+v %v", runs, err)
	}
	if len(slept) != 2 || slept[1] != time.Second {
		t.Fatalf("sleeps %v", slept)
	}
}

func TestErrorHelpers(t *testing.T) {
	f, srv := newFake(t)
	f.on("GET /devices/nope", func(w http.ResponseWriter, r *http.Request) {
		writeJSON(w, 404, map[string]any{"detail": "device not found"})
	})
	f.on("POST /devices", func(w http.ResponseWriter, r *http.Request) {
		writeJSON(w, 422, map[string]any{"detail": []any{map[string]any{"loc": []string{"body", "hostname"}, "msg": "required"}}})
	})
	c := tokenClient(t, srv)
	if _, err := c.Devices.Get(context.Background(), "nope"); !IsNotFound(err) {
		t.Fatalf("expected not found, got %v", err)
	}
	if _, err := c.Devices.Create(context.Background(), &DeviceInput{}); !IsValidation(err) {
		t.Fatalf("expected validation error, got %v", err)
	}
}

func TestContextCancellation(t *testing.T) {
	_, srv := newFake(t)
	c := tokenClient(t, srv)
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	if _, err := c.Me(ctx); !errors.Is(err, context.Canceled) {
		t.Fatalf("expected context.Canceled, got %v", err)
	}
}

func TestServerErrorIsNotRetried(t *testing.T) {
	f, srv := newFake(t)
	f.on("GET /audit/verify", func(w http.ResponseWriter, r *http.Request) {
		writeJSON(w, 500, map[string]any{"detail": "internal server error"})
	})
	c := tokenClient(t, srv)
	if _, err := c.Audit.Verify(context.Background()); err == nil || f.count("GET /audit/verify") != 1 {
		t.Fatalf("500 must fail without retry: %v (%d calls)", err, f.count("GET /audit/verify"))
	}
}
