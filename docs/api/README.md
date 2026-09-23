# API reference

NetworkOps Manager is API-first: the UI, the TACACS agent and the SDKs all use the same REST API.

## Where to find the specification

| What | URL / path |
|---|---|
| Swagger UI (interactive) | `https://<host>/api/docs` |
| ReDoc | `https://<host>/api/redoc` |
| OpenAPI 3.1 document (live) | `https://<host>/api/v1/openapi.json` |
| OpenAPI document (committed) | [`docs/api/openapi.json`](openapi.json) - regenerate with `make openapi` (`python -m app.cli export-openapi`); CI fails if it is stale |
| Health / readiness / metrics | `/healthz`, `/readyz` (runs `SELECT 1`), `/metrics` (Prometheus; not routed by the proxy/ingress) - not part of the OpenAPI document |

Operations are grouped by tag: `auth`, `users`, `inventory`, `tacacs`, `configs`, `activity`,
`operations`.

## Conventions

* **Base path** `/api/v1`, JSON bodies (`Content-Type: application/json`) except
  `GET /devices/{id}/config` and `GET /tacacs/agent/config` (text/plain), report downloads
  (CSV/XLSX/PDF) and `POST /sessions` (multipart).
* **Authentication**: `Authorization: Bearer <token>` where the token is
  * a JWT access token from `POST /auth/login` (`{username, password, tenant?, otp?}` →
    `{access_token, refresh_token, expires_in}`), renewed with `POST /auth/refresh` (the refresh
    token rotates on every call - always store the new one; replaying an old one revokes the
    session family), or
  * an API token `nomt_...` from `POST /auth/tokens` (optionally scoped), or
  * for the agent endpoints only, a TACACS agent token `nomagent_...`.
* **Tenancy**: requests act in the caller's tenant. Platform superusers may add
  `X-Tenant: <tenant-slug>`. Objects of other tenants are reported as **404**.
* **Pagination**: list endpoints that can grow large return
  `{"items": [...], "total": n, "limit": l, "offset": o}` and accept `limit` / `offset`
  (per-endpoint maximum `limit`, e.g. 1000 for devices and accounting). Small catalogues
  (roles, policies, rules ...) return plain arrays.
* **Timestamps**: ISO 8601 with offset (UTC). Query parameters accept ISO 8601
  (`start=2026-09-23T00:00:00Z`).
* **Errors**: `{"detail": ...}` - a string, a list of validation errors (422, FastAPI format), or
  `{"code": "...", "message": "..."}` for authentication errors (`invalid_credentials`,
  `mfa_required`, `mfa_invalid`, `locked`, `token_reuse`). Status codes: 400, 401, 403, 404, 409
  (workflow conflicts), 422, 429 (`Retry-After`), 5xx (generic message; correlate with
  `X-Request-ID` in server logs).
* **Rate limits**: `X-RateLimit-Limit` / `X-RateLimit-Remaining` on `/api/v1` responses (defaults:
  10/min for login/refresh/MFA, 600/min otherwise, per client IP).
* **Tracing**: send `X-Request-ID` to correlate; the API echoes it (or generates one).

### Agent endpoints (TACACS host)

| Endpoint | Purpose |
|---|---|
| `GET /tacacs/agent/config` | rendered tac_plus-ng config; `If-None-Match: <sha256>` → 304; `ETag` = sha256, `X-Config-Version`; 404 = nothing deployed yet; 409 = current render differs from the deployed revision (redeploy) |
| `POST /tacacs/agent/heartbeat` | `{running_sha256, status: "ok"\|"error", message}`; `error` raises a `tacacs_deploy_failed` alert |
| `POST /accounting/ingest` | `{lines: [...]}` raw tac_plus-ng log lines (TSV or JSON lines) → `{accounting, auth, skipped}` |
| `POST /sessions` | multipart: `file` (asciicast v2), `username`, `device_address`, `source_address?`, `started_at?` |

The reference implementation is `tacacs-agent/` ([README](../../tacacs-agent/README.md)).

## Versioning and deprecation policy

* The major version is part of the path (`/api/v1`). Within v1, changes are **additive only**:
  new endpoints, new optional request fields, new response fields, new enum values in documented
  open sets. Clients must ignore unknown response fields (both SDKs do).
* Breaking changes (removing/renaming fields or endpoints, changing types or semantics, tightening
  validation) go to `/api/v2`, which will run side by side with v1 for at least **12 months**.
* Deprecation of a v1 endpoint or field is announced in the release notes and the OpenAPI document
  (`deprecated: true`), and responses of deprecated endpoints will carry `Deprecation` (RFC 9745)
  and `Sunset` (RFC 8594) headers with a `Link: <...>; rel="deprecation"` to the migration notes.
  **Status:** no endpoint is deprecated today and the header emission is not implemented yet;
  this section is the policy the project commits to.
* The OpenAPI `info.version` tracks the API contract; container images and SDKs follow semantic
  versioning of the release (`vX.Y.Z` tags).

## SDKs

| SDK | Location | Notes |
|---|---|---|
| Python `networkops` | [`sdk/python`](../../sdk/python) | hand-written, typed (`mypy --strict`), httpx; API token or username/password with automatic refresh/re-login, MFA via `otp_provider`, pagination iterators, typed error classes, retries |
| Go `github.com/tecsys-sol/decixtacs/sdk/go/networkops` | [`sdk/go/networkops`](../../sdk/go/networkops) | hand-written, stdlib only, `context`, `iter.Seq2` pagination, `*APIError` + helpers |
| Generated (openapi-generator) Python + Go | `make sdk` → `sdk/generated/` | every endpoint, generated from `docs/api/openapi.json`; see [`sdk/openapi-generator`](../../sdk/openapi-generator/README.md) |

Tagged releases attach the OpenAPI document, the Python wheel/sdist, the Go SDK source and both
generated clients to the GitHub release.

Quick examples:

```bash
# login, then list failed backups
TOKEN=$(curl -s https://nom.example.net/api/v1/auth/login -H 'Content-Type: application/json' \
  -d '{"username":"alice","password":"...","tenant":"exampleix"}' | jq -r .access_token)
curl -s "https://nom.example.net/api/v1/backups?status=failed&limit=20" -H "Authorization: Bearer $TOKEN" | jq

# who ran "request system reboot" in the last day (regex search)
curl -s -G https://nom.example.net/api/v1/accounting/commands -H "Authorization: Bearer $TOKEN" \
  --data-urlencode 'command=~^request system reboot' --data-urlencode "start=$(date -u -d '-1 day' +%FT%TZ)"
```

```python
from networkops import NetworkOpsClient
with NetworkOpsClient("https://nom.example.net", token="nomt_...") as nom:
    print(nom.backups.diff(nom.devices.find("mx204-fra1").id, old="HEAD~1").unified)
```

```go
c, _ := networkops.New("https://nom.example.net", networkops.WithToken(token))
rev, err := c.Tacacs.Deploy(ctx, serverID)
```
