# networkops - Python client for NetworkOps Manager

Hand-written, typed (`py.typed`, `mypy --strict` clean), synchronous client built on `httpx`.
For a fully generated client covering every endpoint see `../openapi-generator/`.

```bash
pip install ./sdk/python        # or the wheel attached to a GitHub release
```

## Authentication

```python
from networkops import NetworkOpsClient

# 1) API token (recommended for automation; create it in the UI or with POST /api/v1/auth/tokens,
#    optionally restricted to scopes such as ["devices:read", "configs:backup"])
nom = NetworkOpsClient("https://nom.example.net", token="nomt_...")

# 2) username / password (local, LDAP or AD account) - logs in lazily, refreshes the 15-minute
#    access token before it expires with the rotating refresh token, re-logs in if the refresh
#    token was revoked. MFA: otp="123456" or otp_provider=lambda: pyotp.TOTP(seed).now()
nom = NetworkOpsClient("https://nom.example.net", username="alice", password="...", tenant="acme")

# Platform operators (superusers) can act inside another tenant:
nom = NetworkOpsClient("https://nom.example.net", token="nomt_...", act_as_tenant="customer-a")
```

Use it as a context manager (`with NetworkOpsClient(...) as nom:`) so password sessions are
logged out (refresh-token family revoked) and connections are closed.

## Examples

```python
from datetime import datetime, timedelta, UTC

with NetworkOpsClient("https://nom.example.net", token="nomt_...") as nom:
    # inventory - iter() follows pagination transparently
    for dev in nom.devices.iter(vendor="juniper", backup_status="failed"):
        print(dev.hostname, dev.management_ip, dev.last_backup_at)

    # backups, history and diffs (Git revisions: sha, HEAD, HEAD~1 ...)
    mx = nom.devices.find("mx204-fra1")
    nom.backups.run([mx.id], reason="before maintenance", run_async=False)
    d = nom.backups.diff(mx.id, old="HEAD~1")
    print(d.unified, d.risk["level"])
    print(nom.backups.search(peer_as=13335))            # Junos/EOS config intelligence

    # restore: dry run first, then push under an approved change
    preview = nom.backups.restore(mx.id, backup_id, dry_run=True)
    print(preview.device_diff)

    # TACACS+ render & deploy
    server = nom.tacacs.servers()[0]
    print(nom.tacacs.render(server.id).warnings)
    rev = nom.tacacs.deploy(server.id)

    # command accounting ("~" = regex)
    since = datetime.now(UTC) - timedelta(days=1)
    for cmd in nom.accounting.iter(command="~^request system", start=since):
        print(cmd.timestamp, cmd.username, cmd.device_name, cmd.command, cmd.dangerous)

    # compliance
    run = nom.compliance.run()
    print(run.score, nom.compliance.run_detail(run.id)["failures_by_rule"])

    # change management (four-eyes: someone else approves)
    chg = nom.changes.create(title="Add IX VLAN 2342", device_ids=[mx.id], risk="low")
    nom.changes.submit(chg.id, "ready for CAB")

    # audit trail
    assert nom.audit.verify()["intact"]
    for ev in nom.audit.iter(action="tacacs.*", max_items=20):
        print(ev.timestamp, ev.actor_name, ev.action, ev.target_name)
```

## Errors, retries, models

* HTTP errors raise `APIError` subclasses: `AuthenticationError` / `MFARequiredError` (401),
  `PermissionDeniedError` (403), `NotFoundError` (404 - also for objects of other tenants),
  `ConflictError` (409), `ValidationError` (422), `RateLimitError` (429, `.retry_after`),
  `ServerError` (5xx). Each carries `status_code`, `detail`, `code` and the server's `request_id`.
* GET/PUT/DELETE are retried (`max_retries=2`, exponential backoff) on connection errors and
  429/502/503/504; POST only on 429 (the server rejected it before doing anything).
* Responses are frozen dataclasses (`Device`, `Backup`, `Diff`, `TacacsServer`, `CommandRecord`,
  `ChangeRequest`, `AuditEvent` ...) with parsed `datetime`/`UUID` fields; unknown fields from newer
  servers are ignored and the original JSON is available as `.raw`. Endpoints that are not wrapped
  yet can be called with `nom.get("/path", params=...)` / `nom.post(...)`.

## Development

```bash
uv venv .venv && uv pip install -e ".[dev]"
.venv/bin/pytest && .venv/bin/ruff check src tests && .venv/bin/mypy
```
