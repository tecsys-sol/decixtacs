package networkops

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"iter"
	"math/rand/v2"
	"net/http"
	"net/url"
	"strconv"
	"strings"
	"sync"
	"time"
)

// Version of the SDK (sent in the User-Agent header).
const Version = "0.1.0"

// Client talks to one NetworkOps Manager instance. It is safe for concurrent use.
type Client struct {
	baseURL    *url.URL
	httpClient *http.Client
	userAgent  string
	actAs      string
	maxRetries int

	// authentication
	staticToken string
	username    string
	password    string
	tenant      string
	otp         func() string
	refreshSkew time.Duration

	mu           sync.Mutex
	accessToken  string
	refreshToken string
	expiresAt    time.Time

	now   func() time.Time
	sleep func(context.Context, time.Duration) error

	Devices    *DevicesService
	Backups    *BackupsService
	Tacacs     *TacacsService
	Accounting *AccountingService
	Compliance *ComplianceService
	Changes    *ChangesService
	Audit      *AuditService
}

// Option configures a Client.
type Option func(*Client) error

// WithToken authenticates with an API token ("nomt_...") created via POST /api/v1/auth/tokens.
func WithToken(token string) Option {
	return func(c *Client) error {
		if token == "" {
			return errors.New("networkops: empty token")
		}
		c.staticToken = token
		return nil
	}
}

// WithPassword authenticates with username/password (local, LDAP or AD). tenant is the tenant
// slug ("" = the platform's first tenant).
func WithPassword(username, password, tenant string) Option {
	return func(c *Client) error {
		if username == "" || password == "" {
			return errors.New("networkops: username and password are required")
		}
		c.username, c.password, c.tenant = username, password, tenant
		return nil
	}
}

// WithOTP supplies TOTP codes for accounts with MFA enabled (called on every login).
func WithOTP(provider func() string) Option {
	return func(c *Client) error { c.otp = provider; return nil }
}

// WithHTTPClient replaces the default *http.Client (timeouts, proxies, TLS config).
func WithHTTPClient(h *http.Client) Option {
	return func(c *Client) error { c.httpClient = h; return nil }
}

// WithActAsTenant sends X-Tenant so a platform superuser acts inside another tenant.
func WithActAsTenant(slug string) Option {
	return func(c *Client) error { c.actAs = slug; return nil }
}

// WithMaxRetries sets how often idempotent requests are retried (default 2).
func WithMaxRetries(n int) Option {
	return func(c *Client) error { c.maxRetries = n; return nil }
}

// WithUserAgent overrides the User-Agent header.
func WithUserAgent(ua string) Option {
	return func(c *Client) error { c.userAgent = ua; return nil }
}

// New creates a client. baseURL may be the site root ("https://nom.example.net") or already end
// in "/api/v1".
func New(baseURL string, opts ...Option) (*Client, error) {
	u, err := url.Parse(strings.TrimRight(baseURL, "/"))
	if err != nil || u.Scheme == "" || u.Host == "" {
		return nil, fmt.Errorf("networkops: invalid base URL %q", baseURL)
	}
	if !strings.HasSuffix(u.Path, "/api/v1") {
		u.Path += "/api/v1"
	}
	c := &Client{
		baseURL:     u,
		httpClient:  &http.Client{Timeout: 60 * time.Second},
		userAgent:   "networkops-go/" + Version,
		maxRetries:  2,
		refreshSkew: 30 * time.Second,
		now:         time.Now,
		sleep:       sleepCtx,
	}
	for _, o := range opts {
		if err := o(c); err != nil {
			return nil, err
		}
	}
	if c.staticToken != "" && c.username != "" {
		return nil, errors.New("networkops: use either WithToken or WithPassword, not both")
	}
	if c.staticToken == "" && c.username == "" {
		return nil, errors.New("networkops: authentication required (WithToken or WithPassword)")
	}
	c.Devices = &DevicesService{c}
	c.Backups = &BackupsService{c}
	c.Tacacs = &TacacsService{c}
	c.Accounting = &AccountingService{c}
	c.Compliance = &ComplianceService{c}
	c.Changes = &ChangesService{c}
	c.Audit = &AuditService{c}
	return c, nil
}

func sleepCtx(ctx context.Context, d time.Duration) error {
	t := time.NewTimer(d)
	defer t.Stop()
	select {
	case <-ctx.Done():
		return ctx.Err()
	case <-t.C:
		return nil
	}
}

// --- authentication ----------------------------------------------------------------------

func (c *Client) rawJSON(ctx context.Context, method, path string, body any) (*http.Response, []byte, error) {
	var rd io.Reader
	if body != nil {
		b, err := json.Marshal(body)
		if err != nil {
			return nil, nil, err
		}
		rd = bytes.NewReader(b)
	}
	req, err := http.NewRequestWithContext(ctx, method, c.baseURL.String()+path, rd)
	if err != nil {
		return nil, nil, err
	}
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("Accept", "application/json")
	req.Header.Set("User-Agent", c.userAgent)
	resp, err := c.httpClient.Do(req)
	if err != nil {
		return nil, nil, err
	}
	defer resp.Body.Close()
	data, err := io.ReadAll(resp.Body)
	return resp, data, err
}

func (c *Client) storeTokens(data []byte) error {
	var tp tokenPair
	if err := json.Unmarshal(data, &tp); err != nil {
		return fmt.Errorf("networkops: decoding token response: %w", err)
	}
	c.accessToken, c.refreshToken = tp.AccessToken, tp.RefreshToken
	c.expiresAt = c.now().Add(time.Duration(tp.ExpiresIn) * time.Second)
	return nil
}

func (c *Client) login(ctx context.Context) error {
	body := map[string]string{"username": c.username, "password": c.password}
	if c.tenant != "" {
		body["tenant"] = c.tenant
	}
	if c.otp != nil {
		body["otp"] = c.otp()
	}
	resp, data, err := c.rawJSON(ctx, http.MethodPost, "/auth/login", body)
	if err != nil {
		return err
	}
	if resp.StatusCode != http.StatusOK {
		return newAPIError(resp, data)
	}
	return c.storeTokens(data)
}

func (c *Client) refresh(ctx context.Context) bool {
	if c.refreshToken == "" {
		return false
	}
	resp, data, err := c.rawJSON(ctx, http.MethodPost, "/auth/refresh", map[string]string{"refresh_token": c.refreshToken})
	if err != nil || resp.StatusCode != http.StatusOK {
		c.accessToken, c.refreshToken = "", "" // expired, revoked or reuse detected
		return false
	}
	return c.storeTokens(data) == nil
}

func (c *Client) bearer(ctx context.Context, forceRenew bool) (string, error) {
	if c.staticToken != "" {
		return c.staticToken, nil
	}
	c.mu.Lock()
	defer c.mu.Unlock()
	stale := c.accessToken == "" || !c.now().Before(c.expiresAt.Add(-c.refreshSkew))
	if forceRenew || stale {
		if !c.refresh(ctx) {
			if err := c.login(ctx); err != nil {
				return "", err
			}
		}
	}
	return c.accessToken, nil
}

// Login authenticates eagerly (otherwise the first request does).
func (c *Client) Login(ctx context.Context) error {
	_, err := c.bearer(ctx, false)
	return err
}

// Logout revokes the refresh-token family of a password session.
func (c *Client) Logout(ctx context.Context) error {
	c.mu.Lock()
	defer c.mu.Unlock()
	if c.refreshToken == "" {
		return nil
	}
	resp, data, err := c.rawJSON(ctx, http.MethodPost, "/auth/logout", map[string]string{"refresh_token": c.refreshToken})
	c.accessToken, c.refreshToken = "", ""
	if err != nil {
		return err
	}
	if resp.StatusCode >= 300 {
		return newAPIError(resp, data)
	}
	return nil
}

// --- requests ----------------------------------------------------------------------------

func isIdempotent(method string) bool {
	switch method {
	case http.MethodGet, http.MethodHead, http.MethodOptions, http.MethodPut, http.MethodDelete:
		return true
	}
	return false
}

func retryable(status int) bool {
	return status == 429 || status == 502 || status == 503 || status == 504
}

func backoff(attempt int) time.Duration {
	d := time.Duration(500*(1<<(attempt-1))) * time.Millisecond
	if d > 8*time.Second {
		d = 8 * time.Second
	}
	return d/2 + time.Duration(rand.Int64N(int64(d/2)+1))
}

// Do performs an authenticated request against path (relative to /api/v1). query may be nil.
// body is JSON encoded when non-nil. out, when non-nil, receives the decoded JSON response; a
// *string receives the raw body. Use it for endpoints without a typed helper.
func (c *Client) Do(ctx context.Context, method, path string, query url.Values, body, out any) error {
	var payload []byte
	if body != nil {
		b, err := json.Marshal(body)
		if err != nil {
			return fmt.Errorf("networkops: encoding request: %w", err)
		}
		payload = b
	}
	target := c.baseURL.String() + path
	if len(query) > 0 {
		target += "?" + query.Encode()
	}
	renewed := false
	for attempt := 0; ; attempt++ {
		token, err := c.bearer(ctx, false)
		if err != nil {
			return err
		}
		var rd io.Reader
		if payload != nil {
			rd = bytes.NewReader(payload)
		}
		req, err := http.NewRequestWithContext(ctx, method, target, rd)
		if err != nil {
			return err
		}
		req.Header.Set("Authorization", "Bearer "+token)
		req.Header.Set("Accept", "application/json")
		req.Header.Set("User-Agent", c.userAgent)
		if payload != nil {
			req.Header.Set("Content-Type", "application/json")
		}
		if c.actAs != "" {
			req.Header.Set("X-Tenant", c.actAs)
		}
		resp, err := c.httpClient.Do(req)
		if err != nil {
			if ctx.Err() == nil && isIdempotent(method) && attempt < c.maxRetries {
				if serr := c.sleep(ctx, backoff(attempt+1)); serr != nil {
					return serr
				}
				continue
			}
			return err
		}
		data, rerr := io.ReadAll(resp.Body)
		resp.Body.Close()
		if rerr != nil {
			return rerr
		}
		if resp.StatusCode == http.StatusUnauthorized && c.staticToken == "" && !renewed {
			renewed = true
			c.mu.Lock()
			c.accessToken = ""
			c.mu.Unlock()
			attempt--
			continue
		}
		if retryable(resp.StatusCode) && attempt < c.maxRetries && (isIdempotent(method) || resp.StatusCode == 429) {
			wait := backoff(attempt + 1)
			if ra, err := strconv.Atoi(resp.Header.Get("Retry-After")); err == nil && resp.StatusCode == 429 {
				wait = time.Duration(ra) * time.Second
			}
			if serr := c.sleep(ctx, wait); serr != nil {
				return serr
			}
			continue
		}
		if resp.StatusCode >= 400 {
			return newAPIError(resp, data)
		}
		if out == nil || resp.StatusCode == http.StatusNoContent || len(data) == 0 {
			return nil
		}
		if s, ok := out.(*string); ok {
			*s = string(data)
			return nil
		}
		if err := json.Unmarshal(data, out); err != nil {
			return fmt.Errorf("networkops: decoding %s %s: %w", method, path, err)
		}
		return nil
	}
}

// --- pagination --------------------------------------------------------------------------

func getPage[T any](ctx context.Context, c *Client, path string, q url.Values, limit, offset int) (*Page[T], error) {
	qq := url.Values{}
	for k, v := range q {
		qq[k] = v
	}
	if limit > 0 {
		qq.Set("limit", strconv.Itoa(limit))
	}
	qq.Set("offset", strconv.Itoa(offset))
	var p Page[T]
	if err := c.Do(ctx, http.MethodGet, path, qq, nil, &p); err != nil {
		return nil, err
	}
	return &p, nil
}

// paginate yields every item of a paginated endpoint, fetching pages of pageSize lazily.
// Iteration stops at the first error, which is yielded with the zero value.
func paginate[T any](ctx context.Context, c *Client, path string, q url.Values, pageSize int) iter.Seq2[T, error] {
	if pageSize <= 0 {
		pageSize = 100
	}
	return func(yield func(T, error) bool) {
		offset := 0
		for {
			p, err := getPage[T](ctx, c, path, q, pageSize, offset)
			if err != nil {
				var zero T
				yield(zero, err)
				return
			}
			for _, it := range p.Items {
				if !yield(it, nil) {
					return
				}
			}
			offset += len(p.Items)
			if len(p.Items) == 0 || offset >= p.Total {
				return
			}
		}
	}
}

// --- query helpers -----------------------------------------------------------------------

type query url.Values

func (q query) str(k, v string) {
	if v != "" {
		url.Values(q).Set(k, v)
	}
}

func (q query) time(k string, t *time.Time) {
	if t != nil && !t.IsZero() {
		url.Values(q).Set(k, t.UTC().Format(time.RFC3339Nano))
	}
}

func (q query) boolTrue(k string, b bool) {
	if b {
		url.Values(q).Set(k, "true")
	}
}

func (q query) intNZ(k string, v int) {
	if v != 0 {
		url.Values(q).Set(k, strconv.Itoa(v))
	}
}
