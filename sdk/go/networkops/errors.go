package networkops

import (
	"encoding/json"
	"errors"
	"fmt"
	"net/http"
)

// APIError is returned for every non-2xx API response.
type APIError struct {
	StatusCode int
	// Detail is the decoded "detail" field: a string, a list of validation errors, or an object
	// with "code" and "message" for authentication errors.
	Detail     any
	Method     string
	Path       string
	RequestID  string
	RetryAfter string
}

func (e *APIError) Error() string {
	msg := e.Detail
	if m, ok := e.Detail.(map[string]any); ok && m["message"] != nil {
		msg = m["message"]
	}
	return fmt.Sprintf("networkops: %s %s -> HTTP %d: %v", e.Method, e.Path, e.StatusCode, msg)
}

// Code returns the machine readable error code of authentication errors
// ("mfa_required", "locked", "token_reuse", ...), or "".
func (e *APIError) Code() string {
	if m, ok := e.Detail.(map[string]any); ok {
		if c, ok := m["code"].(string); ok {
			return c
		}
	}
	return ""
}

func newAPIError(resp *http.Response, body []byte) *APIError {
	e := &APIError{
		StatusCode: resp.StatusCode,
		Method:     resp.Request.Method,
		Path:       resp.Request.URL.Path,
		RequestID:  resp.Header.Get("X-Request-ID"),
		RetryAfter: resp.Header.Get("Retry-After"),
	}
	var wrapped struct {
		Detail any `json:"detail"`
	}
	if json.Unmarshal(body, &wrapped) == nil && wrapped.Detail != nil {
		e.Detail = wrapped.Detail
	} else {
		e.Detail = string(body)
	}
	return e
}

func hasStatus(err error, status int) bool {
	var e *APIError
	return errors.As(err, &e) && e.StatusCode == status
}

// IsUnauthorized reports a 401 (bad credentials, expired or revoked token, MFA required).
func IsUnauthorized(err error) bool { return hasStatus(err, http.StatusUnauthorized) }

// IsForbidden reports a 403 (missing permission or cross-tenant access).
func IsForbidden(err error) bool { return hasStatus(err, http.StatusForbidden) }

// IsNotFound reports a 404 (also returned for objects of other tenants).
func IsNotFound(err error) bool { return hasStatus(err, http.StatusNotFound) }

// IsConflict reports a 409 (invalid workflow transition, restore without approved change ...).
func IsConflict(err error) bool { return hasStatus(err, http.StatusConflict) }

// IsValidation reports a 422.
func IsValidation(err error) bool { return hasStatus(err, http.StatusUnprocessableEntity) }

// IsRateLimited reports a 429.
func IsRateLimited(err error) bool { return hasStatus(err, http.StatusTooManyRequests) }

// IsMFARequired reports a login that needs a one-time password (use WithOTP).
func IsMFARequired(err error) bool {
	var e *APIError
	return errors.As(err, &e) && e.StatusCode == http.StatusUnauthorized && e.Code() == "mfa_required"
}
